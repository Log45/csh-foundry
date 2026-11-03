"""Scan export identity cannot race with mutable tag changes."""

import hashlib
import importlib.util
import io
import json
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("scan_images", ROOT / "scripts/scan_images.py")
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize("scan_code", [0, 1])
def test_export_resolves_then_saves_immutable_image_and_preserves_gate(
    tmp_path, monkeypatch, scan_code
):
    identity = "sha256:" + "1" * 64
    config = b'{"architecture":"arm64"}'
    calls = []

    def inspect(args):
        calls.append(args)
        return json.dumps([{"Id": identity}]).encode()

    def run(args, **kwargs):
        calls.append(args)
        if args[:2] == ["docker", "save"]:
            assert args[-1] == identity
            with tarfile.open(args[3], "w") as archive:
                for name, content in [
                    ("manifest.json", b'[{"Config":"config.json"}]'),
                    ("config.json", config),
                ]:
                    info = tarfile.TarInfo(name)
                    info.size = len(content)
                    archive.addfile(info, io.BytesIO(content))
        elif "stdout" in kwargs:
            kwargs["stdout"].write("{}")
        return SimpleNamespace(returncode=scan_code if module.GRYPE in args else 0)

    monkeypatch.setattr(module.subprocess, "check_output", inspect)
    monkeypatch.setattr(module.subprocess, "run", run)
    shared = tmp_path / "shared-cache"
    monkeypatch.setattr(module, "DEFAULT_CACHE", shared)
    monkeypatch.setattr(
        sys, "argv", ["scan_images.py", "mutable:tag", "--output", str(tmp_path / "first")]
    )
    if scan_code:
        with pytest.raises(SystemExit) as error:
            module.main()
        assert error.value.code == 1
    else:
        module.main()
    result = json.loads((tmp_path / "first/results.json").read_text())["image-0"]
    assert calls[0] == ["docker", "image", "inspect", "mutable:tag"]
    assert result["image_id"] == identity
    assert result["config_digest"] == "sha256:" + hashlib.sha256(config).hexdigest()
    assert result["vulnerabilities"] == ("FAIL" if scan_code else "PASS")
    assert result["sbom"] == "PASS"
    assert not list(tmp_path.glob("*.tar"))

    # A second evidence directory must reuse exactly the same cache mount.
    monkeypatch.setattr(
        sys, "argv", ["scan_images.py", "mutable:tag", "--output", str(tmp_path / "second")]
    )
    if scan_code:
        with pytest.raises(SystemExit):
            module.main()
    else:
        module.main()
    grype_calls = [args for args in calls if module.GRYPE in args]
    assert len(grype_calls) == 2
    assert all(str(shared.resolve()) + ":/cache" in args for args in grype_calls)
    assert not (tmp_path / "first/cache").exists()
    assert not (tmp_path / "second/cache").exists()
