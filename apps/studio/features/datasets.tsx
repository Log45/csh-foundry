"use client";
import { fileChecksum } from "@/lib/file-checksum";
import { useContext, useEffect, useState } from "react";
import type { Client } from "@/lib/api";
import type { components } from "@/lib/api-schema";
import { ArtifactContext } from "@/features/artifacts";
import { Field, Notice, useTask } from "@/components/ui";

type Version = components["schemas"]["DatasetVersionView"];
export function CreateDatasetPanel({
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
          await api(`/api/v1/projects/${project}/datasets`, "POST", {
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
      <Field label="New dataset name">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
          maxLength={200}
        />
      </Field>
      <button disabled={task.busy}>Create dataset</button>
    </form>
  );
}
export function DatasetPanel({
  api,
  dataset,
  writable,
}: {
  api: Client;
  dataset: string;
  writable: boolean;
}) {
  const context = useContext(ArtifactContext);
  const [versions, setVersions] = useState<Version[]>([]);
  const [offset, setOffset] = useState(0);
  const [file, setFile] = useState<File | null>(null);
  const [format, setFormat] = useState("csv");
  const [preview, setPreview] = useState<
    components["schemas"]["DatasetPreview"] | null
  >(null);
  const [progress, setProgress] = useState("");
  const [validationJobs, setValidationJobs] = useState<
    Record<string, components["schemas"]["ExecutionJobView"]>
  >({});
  useEffect(() => {
    const active = Object.entries(validationJobs).filter(([, job]) =>
      ["QUEUED", "ADMITTED", "RUNNING", "CANCELLING"].includes(job.state),
    );
    if (!active.length) return;
    let current = true;
    const timer = setTimeout(async () => {
      try {
        for (const [version, job] of active) {
          const status = await api<components["schemas"]["ExecutionJobView"]>(
            `/api/v1/execution/jobs/${job.id}`,
          );
          if (!current) return;
          setValidationJobs((previous) => ({ ...previous, [version]: status }));
          setProgress(
            `Validation ${status.state.toLowerCase()}${status.error ? `: ${status.error}` : ""}`,
          );
          if (["SUCCEEDED", "FAILED", "CANCELLED"].includes(status.state))
            await load(0);
        }
      } catch {
        if (current)
          setProgress("Status unavailable; refresh validation to retry");
      }
    }, 2000);
    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [api, validationJobs]);
  const task = useTask();
  const path = `/api/v1/datasets/${dataset}`;
  async function load(page = offset) {
    setPreview(null);
    setVersions([]);
    setVersions(
      await api<Version[]>(`${path}/versions?limit=50&offset=${page}`),
    );
  }
  async function transfer(version: string, operation: string, body?: File) {
    const response = await fetch(
      `/bff/artifacts?family=datasets&artifact=${dataset}&version=${version}&operation=${operation}`,
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
      <summary>Dataset versions, schema and preview</summary>
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
          <p>
            Format: {v.format} · Source: {v.artifact_state} · Validated:{" "}
            {v.validated_at ?? "pending"}
          </p>
          <p>SHA-256: {v.checksum}</p>
          <p>
            {v.created_by} · {v.created_at}
          </p>
          {v.state === "PENDING" && writable && (
            <button
              disabled={task.busy}
              onClick={() =>
                void task.run(async () => {
                  const job = await api<
                    components["schemas"]["ExecutionJobView"]
                  >(`${path}/versions/${v.id}/validate`, "POST", {});
                  setValidationJobs((previous) => ({
                    ...previous,
                    [v.id]: job,
                  }));
                  setProgress(`Validation ${job.state.toLowerCase()}`);
                  if (job.state === "SUCCEEDED" || job.state === "FAILED")
                    await load(0);
                })
              }
            >
              Refresh validation status
            </button>
          )}
          {v.state === "FAILED" && (
            <Notice>{String(v.result.message ?? "Validation failed")}</Notice>
          )}
          {v.state === "COMMITTED" && (
            <button
              disabled={task.busy}
              onClick={() =>
                void task.run(async () =>
                  setPreview(
                    await api(`${path}/versions/${v.id}/preview?limit=100`),
                  ),
                )
              }
            >
              Inspect schema and preview version {v.sequence}
            </button>
          )}
          {v.artifact_state === "COMMITTED" && (
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
      {preview && (
        <section aria-label="Dataset preview">
          <p>
            {preview.row_count} rows; showing first {preview.rows.length}
          </p>
          <div style={{ overflowX: "auto" }}>
            <table>
              <thead>
                <tr>
                  {preview.columns.map((c, i) => (
                    <th key={i}>
                      {String(c.name)} · {String(c.logical_type)} ·{" "}
                      {c.nullable ? "nullable" : "no observed nulls"}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {preview.rows.map((row, i) => (
                  <tr key={i}>
                    {row.map((cell, j) => (
                      <td key={j}>
                        {cell === null
                          ? "null"
                          : typeof cell === "object"
                            ? JSON.stringify(cell)
                            : String(cell)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
      {writable && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void task
              .run(async () => {
                if (!file || file.size > 1024 ** 3)
                  throw new Error(
                    "File limit is 1 GiB (administrator limits may be lower)",
                  );
                setProgress("Computing checksum…");
                const checksum = await fileChecksum(file, (percent) =>
                  setProgress(`Computing checksum: ${percent}%`),
                );
                const v = await api<Version>(`${path}/uploads`, "POST", {
                  filename: file.name,
                  size: file.size,
                  checksum,
                  format,
                });
                setProgress("Uploading bytes…");
                await transfer(v.id, "upload", file);
                setProgress("Verifying bytes and validating all records…");
                const committed = await api<Version>(
                  `${path}/versions/${v.id}/finalize`,
                  "POST",
                  {},
                );
                if (committed.state === "PENDING") {
                  const job = await api<
                    components["schemas"]["ExecutionJobView"]
                  >(`${path}/versions/${v.id}/validate`, "POST", {});
                  setValidationJobs((previous) => ({
                    ...previous,
                    [v.id]: job,
                  }));
                }
                setProgress(
                  committed.state === "COMMITTED"
                    ? "Committed validated dataset version"
                    : committed.state === "PENDING"
                      ? "Validation queued; refresh history for status"
                      : "Validation failed; inspect version errors",
                );
                await load(0);
                setOffset(0);
              })
              .catch(() =>
                setProgress("Upload failed; version remains uncommitted"),
              );
          }}
        >
          <Field label="Dataset format">
            <select value={format} onChange={(e) => setFormat(e.target.value)}>
              {["csv", "json", "ndjson", "parquet"].map((f) => (
                <option key={f}>{f}</option>
              ))}
            </select>
          </Field>
          <Field label="Dataset file (up to 1 GiB)">
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
