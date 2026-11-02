"""Stream a logical PostgreSQL dump directly into age encryption; no plaintext backup file."""

import argparse
import hashlib
import os
import subprocess
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument(
        "--recipient", required=True, help="age public recipient, never a private key"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with os.fdopen(
        os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb"
    ) as output:
        dump = subprocess.Popen(
            [
                "docker",
                "exec",
                args.container,
                "pg_dump",
                "-Fc",
                "-U",
                args.user,
                "-d",
                args.database,
            ],
            stdout=subprocess.PIPE,
        )
        try:
            encrypted = subprocess.run(
                ["age", "-r", args.recipient], stdin=dump.stdout, stdout=output, check=False
            )
            assert dump.stdout is not None
            dump.stdout.close()
            code = dump.wait()
            if code or encrypted.returncode:
                raise RuntimeError("Backup failed; partial artifact discarded")
            output.flush()
            os.fsync(output.fileno())
        except BaseException:
            dump.terminate()
            dump.wait()
            args.output.unlink(missing_ok=True)
            raise
    digest = hashlib.file_digest(args.output.open("rb"), "sha256").hexdigest()
    args.output.with_suffix(args.output.suffix + ".sha256").write_text(digest + "\n")
    print("PASS encrypted logical backup and ciphertext SHA256; restore drill is a separate check")


if __name__ == "__main__":
    main()
