"use client";
import { createContext, useContext, useState } from "react";
import type { Client } from "@/lib/api";
import type { components } from "@/lib/api-schema";
import { Field, Notice, useTask } from "@/components/ui";
export const ArtifactContext = createContext({ csrf: "", tenant: "" });
type Version = components["schemas"]["ArtifactVersionView"];
export function CreateArtifactPanel({
  api,
  project,
  folder,
  reload,
}: {
  api: Client;
  project: string;
  folder: string | null;
  reload: () => void;
}) {
  const [name, setName] = useState("");
  const task = useTask();
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        void task.run(async () => {
          await api(`/api/v1/projects/${project}/artifacts`, "POST", {
            name,
            folder_id: folder,
          });
          setName("");
          reload();
        });
      }}
    >
      {task.error && (
        <Notice>
          {task.error}. Storage may be unavailable or access denied.
        </Notice>
      )}
      <Field label="New artifact name">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
          maxLength={200}
        />
      </Field>
      <button disabled={task.busy}>Create artifact</button>
    </form>
  );
}
export function ArtifactPanel({
  api,
  artifact,
  writable,
}: {
  api: Client;
  artifact: string;
  writable: boolean;
}) {
  const context = useContext(ArtifactContext);
  const [versions, setVersions] = useState<Version[]>([]);
  const [offset, setOffset] = useState(0);
  const [file, setFile] = useState<File | null>(null);
  const [progress, setProgress] = useState("");
  const task = useTask();
  const path = `/api/v1/artifacts/${artifact}`;
  async function load(page = offset) {
    setVersions(
      await api<Version[]>(`${path}/versions?limit=50&offset=${page}`),
    );
  }
  async function transfer(version: string, operation: string, body?: File) {
    const response = await fetch(
      `/bff/artifacts?artifact=${artifact}&version=${version}&operation=${operation}`,
      {
        method: "POST",
        headers: {
          "x-csrf-token": context.csrf,
          "x-expected-tenant": context.tenant,
          "content-type": "application/octet-stream",
        },
        body,
      },
    );
    if (!response.ok)
      throw new Error((await response.json()).error?.code ?? "transfer_failed");
    return response;
  }
  return (
    <details>
      <summary>Artifact versions and files</summary>
      {task.error && (
        <Notice>
          {task.error}. Check permissions and storage availability; pending
          uploads can be retried.
        </Notice>
      )}
      <p role="status">
        {task.error
          ? "Operation failed; refresh version history to check committed state"
          : progress}
      </p>
      <button disabled={task.busy} onClick={() => void task.run(() => load())}>
        Load versions
      </button>
      {versions.map((v) => (
        <article key={v.id}>
          <p>
            Version {v.sequence} · {v.state} · {v.filename} · {v.size} bytes ·{" "}
            {v.media_type}
          </p>
          <p>SHA-256: {v.checksum}</p>
          <p>
            {v.created_by} · {v.created_at}
          </p>
          {v.state === "COMMITTED" && (
            <button
              disabled={task.busy}
              onClick={() =>
                void task.run(async () => {
                  const response = await transfer(v.id, "download");
                  const url = URL.createObjectURL(await response.blob());
                  const a = document.createElement("a");
                  a.href = url;
                  a.download = v.filename;
                  a.click();
                  setTimeout(() => URL.revokeObjectURL(url), 1000);
                })
              }
            >
              Download version {v.sequence}
            </button>
          )}
          {writable && v.state === "PENDING" && (
            <button
              disabled={task.busy}
              onClick={() =>
                void task.run(async () => {
                  await api(`${path}/versions/${v.id}/finalize`, "POST", {});
                  await load();
                })
              }
            >
              Retry finalization {v.sequence}
            </button>
          )}
        </article>
      ))}
      <button
        disabled={!offset || task.busy}
        onClick={() =>
          void task.run(async () => {
            const n = offset - 50;
            await load(n);
            setOffset(n);
          })
        }
      >
        Previous versions
      </button>
      <button
        disabled={versions.length < 50 || offset >= 10000 || task.busy}
        onClick={() =>
          void task.run(async () => {
            const n = offset + 50;
            await load(n);
            setOffset(n);
          })
        }
      >
        More versions
      </button>
      {writable && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void task
              .run(async () => {
                if (!file || file.size > 64 * 1024 * 1024)
                  throw new Error("File limit is 64 MiB");
                setProgress("Computing checksum…");
                const checksum = Array.from(
                  new Uint8Array(
                    await crypto.subtle.digest(
                      "SHA-256",
                      await file.arrayBuffer(),
                    ),
                  ),
                  (b) => b.toString(16).padStart(2, "0"),
                ).join("");
                const v = await api<Version>(`${path}/uploads`, "POST", {
                  filename: file.name,
                  size: file.size,
                  checksum,
                });
                setProgress("Uploading bytes…");
                await transfer(v.id, "upload", file);
                setProgress("Verifying stored bytes…");
                await api(`${path}/versions/${v.id}/finalize`, "POST", {});
                setProgress("Committed immutable version");
                await load(0);
                setOffset(0);
              })
              .catch(() =>
                setProgress("Upload failed; version remains uncommitted"),
              );
          }}
        >
          <Field label="Artifact file (up to 64 MiB)">
            <input
              type="file"
              required
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </Field>
          <button disabled={task.busy || !file}>Upload new version</button>
        </form>
      )}
    </details>
  );
}
