"""Fixed-format parsing inside the bounded child. No metadata paths or URLs are opened."""

import hashlib
import warnings
import wave
from pathlib import Path
from typing import Any, cast

from ontology_platform.functions.contracts import GSettings


def extract(request: dict[str, Any], directory: Path) -> dict[str, Any]:
    import PIL
    from PIL import Image, ImageOps

    limits = GSettings.model_validate(request["media_limits"])
    source = directory / "source"
    if source.stat().st_size > limits.media_bytes:
        raise ValueError("Media size exceeded")
    with source.open("rb") as handle:
        signature = handle.read(16)
    declared = request["media_type"]
    metadata: dict[str, Any] = {}
    preview = None
    Image.MAX_IMAGE_PIXELS = limits.pixels
    warnings.simplefilter("error", Image.DecompressionBombWarning)
    if declared in {"image/png", "image/jpeg"}:
        if (declared == "image/png" and not signature.startswith(b"\x89PNG\r\n\x1a\n")) or (
            declared == "image/jpeg" and not signature.startswith(b"\xff\xd8\xff")
        ):
            raise ValueError("Signature mismatch")
        expected = "PNG" if declared == "image/png" else "JPEG"
        with Image.open(source, formats=[expected]) as image:
            if image.width * image.height > limits.pixels:
                raise ValueError("Pixel limit")
            image.verify()
        with Image.open(source, formats=[expected]) as image:
            metadata = {
                "width": image.width,
                "height": image.height,
                "format": image.format,
                "mode": image.mode,
                "orientation": image.getexif().get(274),
                "parser": "Pillow:" + PIL.__version__,
            }
            image.load()
            preview = ImageOps.exif_transpose(image).convert("RGB")
    elif declared == "audio/wav":
        if signature[:4] != b"RIFF" or signature[8:12] != b"WAVE":
            raise ValueError("Signature mismatch")
        with wave.open(str(source), "rb") as audio:
            if (
                audio.getcomptype() != "NONE"
                or audio.getnframes() <= 0
                or not 1 <= audio.getnchannels() <= 8
                or not 1 <= audio.getsampwidth() <= 4
                or not 1 <= audio.getframerate() <= 192000
            ):
                raise ValueError("Only nonempty PCM WAV supported")
            expected_bytes = audio.getnframes() * audio.getnchannels() * audio.getsampwidth()
            actual = 0
            while data := audio.readframes(8192):
                actual += len(data)
                if actual > limits.media_bytes:
                    raise ValueError("Audio size limit")
            if actual != expected_bytes:
                raise ValueError("Truncated PCM")
            metadata = {
                "duration": audio.getnframes() / audio.getframerate(),
                "container": "wav",
                "codec": "pcm",
                "sample_rate": audio.getframerate(),
                "channels": audio.getnchannels(),
                "parser": "python-wave-v1",
            }
    elif declared == "video/mp4":
        import av

        if signature[4:8] != b"ftyp":
            raise ValueError("Signature mismatch")
        with (
            source.open("rb") as handle,
            av.open(
                handle,
                format="mov",
                options={
                    "protocol_whitelist": "file",
                    "enable_drefs": "0",
                    "use_absolute_path": "0",
                    "probesize": "1048576",
                    "analyzeduration": "2000000",
                },
            ) as container,
        ):
            streams = list(container.streams)
            video = list(container.streams.video)
            if len(video) != 1 or len(streams) > 2:
                raise ValueError("Unsupported stream count")
            stream = video[0]
            if stream.codec_context.name != "h264" or any(
                s.type not in {"video", "audio"}
                or (s.type == "audio" and s.codec_context.name != "aac")
                for s in streams
            ):
                raise ValueError("Only H.264/AAC MP4 supported")
            if (
                stream.width * stream.height > limits.pixels
                or not stream.width
                or not stream.height
            ):
                raise ValueError("Video dimensions exceed budget")
            duration = (
                float(stream.duration * stream.time_base)
                if stream.duration and stream.time_base
                else None
            )
            if duration is None or duration <= 0:
                raise ValueError("Video duration unavailable")
            metadata = {
                "duration": duration,
                "container": "mp4",
                "codec": "h264",
                "width": stream.width,
                "height": stream.height,
                "frame_rate": float(stream.average_rate) if stream.average_rate else None,
                "parser": "PyAV:" + av.__version__,
            }
            stream.thread_type = "NONE"
            stream.codec_context.thread_count = 1
            frame = next(cast(av.container.InputContainer, container).decode(stream))
            if frame.width * frame.height > limits.pixels:
                raise ValueError("Decoded frame exceeds budget")
            preview = cast(Any, frame).to_image().convert("RGB")
    elif declared == "application/pdf":
        import pypdf
        from pypdf import PdfReader

        if not signature.startswith(b"%PDF-"):
            raise ValueError("Signature mismatch")
        with source.open("rb") as handle:
            reader = PdfReader(handle, strict=True)
            if reader.is_encrypted:
                raise ValueError("Encrypted PDF unsupported")
            count = len(reader.pages)
            if count > 1000:
                raise ValueError("PDF page budget exceeded")
            metadata = {"container": "pdf", "pages": count, "parser": "pypdf:" + pypdf.__version__}
    else:
        raise ValueError("Unsupported media format")
    result: dict[str, Any] = {"metadata": metadata}
    if preview is not None:
        preview.thumbnail((512, 512))
        # Copy pixels only; derived previews contain no EXIF/ICC/text payloads.
        clean = Image.new("RGB", preview.size)
        clean.paste(preview)
        output = directory / "preview.jpg"
        clean.save(output, "JPEG", quality=80)
        if output.stat().st_size > limits.preview_bytes:
            raise ValueError("Preview limit exceeded")
        with output.open("rb") as handle:
            checksum = hashlib.file_digest(handle, "sha256").hexdigest()
        result["preview"] = {"size": output.stat().st_size, "checksum": checksum}
    return result
