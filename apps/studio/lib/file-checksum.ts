import { sha256 } from "@noble/hashes/sha2.js";

// File slicing keeps at most one 1 MiB buffer alive, including for a 1 GiB source.
export async function fileChecksum(
  file: Blob,
  progress: (percent: number) => void,
) {
  const hash = sha256.create();
  const chunk = 1024 * 1024;
  for (let offset = 0; offset < file.size; offset += chunk) {
    hash.update(
      new Uint8Array(await file.slice(offset, offset + chunk).arrayBuffer()),
    );
    progress(Math.min(100, Math.round(((offset + chunk) / file.size) * 100)));
  }
  return Array.from(hash.digest(), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}
