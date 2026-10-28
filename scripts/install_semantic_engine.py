"""Download v2.1.0 into ignored .external/ and verify committed upstream checksums."""

import hashlib
import platform
from pathlib import Path

import httpx

root = Path(__file__).resolve().parents[1]
targets = {
    ("Darwin", "arm64"): "aarch64-apple-darwin",
    ("Darwin", "x86_64"): "x86_64-apple-darwin",
    ("Linux", "x86_64"): "x86_64-unknown-linux-gnu",
}
target = targets.get((platform.system(), platform.machine()))
if target is None:
    raise SystemExit(
        "No pinned release binary for this platform; build pinned source with --locked"
    )
name = "open-ontologies-" + target
checksums = dict(
    line.split()[::-1]
    for line in (root / "integrations/open-ontologies/SHASUMS.txt").read_text().splitlines()
)
output = root / ".external" / "open-ontologies"
output.parent.mkdir(exist_ok=True)
url = "https://github.com/fabio-rovai/open-ontologies/releases/download/v2.1.0/" + name
response = httpx.get(url, timeout=60, follow_redirects=True)
response.raise_for_status()
data = response.content
if hashlib.sha256(data).hexdigest() != checksums[name]:
    raise SystemExit("Checksum mismatch; refusing to install")
output.write_bytes(data)
output.chmod(0o755)
print(f"PASS SHA256 {name}; installed {output}")
