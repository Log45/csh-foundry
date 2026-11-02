"""SBOMs and vulnerability scans with immutable scanner images and no Docker socket mount."""

import argparse
import json
import subprocess
from pathlib import Path

GRYPE = "anchore/grype@sha256:621d56d1d68106b787022c81546f7e0a36202a25d1239f0c20195fab8c16f7ea"
SYFT = "anchore/syft@sha256:4cc92b64ca74ffca4c94d4c8fcc01f217731375300be14d0b6eeb2e82eaa110a"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="+")
    parser.add_argument("--output", type=Path, default=Path("artifacts/supply-chain"))
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / "cache").mkdir(exist_ok=True)
    results = {}
    for index, image in enumerate(args.images):
        name = "image-" + str(index)
        archive = root / (name + ".tar")
        subprocess.run(["docker", "save", "-o", str(archive), image], check=True)
        identity = json.loads(subprocess.check_output(["docker", "image", "inspect", image]))[0][
            "Id"
        ]
        record = {"image": image, "image_id": identity, "scanner": GRYPE, "sbom_tool": SYFT}
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
            with (root / (name + ".vulnerabilities.json")).open("w") as out:
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
                        f"{root / 'cache'}:/cache",
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
