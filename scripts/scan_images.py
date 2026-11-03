"""SBOMs and vulnerability scans with immutable scanner images and no Docker socket mount."""

import argparse
import fcntl
import hashlib
import json
import subprocess
import tarfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

GRYPE = "anchore/grype@sha256:621d56d1d68106b787022c81546f7e0a36202a25d1239f0c20195fab8c16f7ea"
SYFT = "anchore/syft@sha256:4cc92b64ca74ffca4c94d4c8fcc01f217731375300be14d0b6eeb2e82eaa110a"


DEFAULT_CACHE = Path(__file__).resolve().parents[1] / "artifacts/.cache/grype"


@contextmanager
def cache_lock(cache: Path) -> Iterator[None]:
    """Serialize shared DB updates; evidence outputs never own database-cache copies."""
    cache.mkdir(parents=True, exist_ok=True)
    with (cache / ".scan.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="+")
    parser.add_argument("--output", type=Path, default=Path("artifacts/supply-chain"))
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=DEFAULT_CACHE,
        help="Shared Grype DB cache; independent of per-run evidence output",
    )
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    cache = args.cache_dir.resolve()
    cache.mkdir(parents=True, exist_ok=True)
    results = {}
    for index, image in enumerate(args.images):
        name = "image-" + str(index)
        archive = root / (name + ".tar")
        identity = json.loads(subprocess.check_output(["docker", "image", "inspect", image]))[0][
            "Id"
        ]
        # Resolve before export and save by immutable ID: a concurrent tag update cannot
        # bind the report to a different image than the archive being scanned.
        subprocess.run(["docker", "save", "-o", str(archive), identity], check=True)
        with tarfile.open(archive) as exported:
            manifest_file = exported.extractfile("manifest.json")
            assert manifest_file is not None
            manifests = json.load(manifest_file)
            if len(manifests) != 1:
                raise ValueError("Exactly one platform image must be exported")
            config_file = exported.extractfile(manifests[0]["Config"])
            assert config_file is not None
            config_digest = "sha256:" + hashlib.sha256(config_file.read()).hexdigest()
        record = {
            "image": image,
            "image_id": identity,
            "config_digest": config_digest,
            "scanner": GRYPE,
            "sbom_tool": SYFT,
        }
        try:
            with (root / (name + ".sbom.json")).open("w") as out:
                sbom = subprocess.run(
                    [
                        "docker",
                        "run",
                        "--rm",
                        "--read-only",
                        "--cap-drop=ALL",
                        "--security-opt=no-new-privileges",
                        "--tmpfs",
                        "/tmp",
                        "-v",
                        f"{root}:/scan:ro",
                        SYFT,
                        "docker-archive:/scan/" + archive.name,
                        "-o",
                        "cyclonedx-json",
                    ],
                    stdout=out,
                )
            with cache_lock(cache), (root / (name + ".vulnerabilities.json")).open("w") as out:
                scan = subprocess.run(
                    [
                        "docker",
                        "run",
                        "--rm",
                        "--read-only",
                        "--cap-drop=ALL",
                        "--security-opt=no-new-privileges",
                        "--tmpfs",
                        "/tmp",
                        "-e",
                        "GRYPE_DB_CACHE_DIR=/cache",
                        "-v",
                        f"{cache}:/cache",
                        "-v",
                        f"{root}:/scan:ro",
                        GRYPE,
                        "docker-archive:/scan/" + archive.name,
                        "-o",
                        "json",
                        "--fail-on",
                        "high",
                    ],
                    stdout=out,
                )
            record.update(
                {
                    "sbom": "PASS" if sbom.returncode == 0 else "FAIL",
                    "vulnerabilities": "PASS" if scan.returncode == 0 else "FAIL",
                }
            )
        finally:
            archive.unlink(missing_ok=True)
        results[name] = record
    (root / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))
    if any(r["sbom"] != "PASS" or r["vulnerabilities"] != "PASS" for r in results.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
