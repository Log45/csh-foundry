"use client";
import { useContext, useEffect, useState } from "react";
import type { Client } from "@/lib/api";
import type { components } from "@/lib/api-schema";
import { Field, Notice, useTask } from "@/components/ui";
import { ArtifactContext } from "./artifacts";

type Family = "media-sets" | "functions" | "automations";
type Definition =
  | components["schemas"]["FunctionDefinitionView"]
  | components["schemas"]["MediaSnapshotView"]
  | components["schemas"]["AutomationDefinitionView"];
type Item = components["schemas"]["ItemView"];
type Job = components["schemas"]["ExecutionJobView"];
type Receipt = components["schemas"]["ReceiptView"];
const examples = {
  "media-sets": { items: [] },
  functions: {
    implementation: "text.normalize.v1",
    input_schema: { text: { type: "string" } },
    output_schema: { result: { type: "string" } },
  },
  automations: {
    trigger: { kind: "interval", interval_seconds: 3600 },
    function_id: "",
    function_definition_id: "",
    inputs: { text: "scheduled" },
  },
};
export function CreateGovernedPanel({
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
  const [family, setFamily] = useState<Family>("media-sets");
  const [name, setName] = useState("");
  const task = useTask();
  return (
    <form
      aria-label="Create governed processing resource"
      onSubmit={(e) => {
        e.preventDefault();
        void task.run(async () => {
          await api(`/api/v1/projects/${project}/${family}`, "POST", {
            name,
            folder_id: folder,
          });
          setName("");
          reload();
        });
      }}
    >
      {task.error && <Notice>{task.error}</Notice>}
      <Field label="Processing resource type">
        <select
          value={family}
          onChange={(e) => setFamily(e.target.value as Family)}
        >
          <option value="media-sets">Media Set</option>
          <option value="functions">Function</option>
          <option value="automations">Automation</option>
        </select>
      </Field>
      <Field label="Processing resource name">
        <input
          value={name}
          required
          maxLength={200}
          onChange={(e) => setName(e.target.value)}
        />
      </Field>
      <button disabled={task.busy}>Create processing resource</button>
    </form>
  );
}

export function GovernedPanel({
  api,
  resource,
  family,
  writable,
}: {
  api: Client;
  resource: string;
  family: Family;
  writable: boolean;
}) {
  const context = useContext(ArtifactContext);
  const task = useTask();
  const [spec, setSpec] = useState(JSON.stringify(examples[family], null, 2));
  const [definitions, setDefinitions] = useState<Definition[]>([]);
  const [selected, setSelected] = useState("");
  const [inputs, setInputs] = useState('{"text":" Hello world "}');
  const [attachment, setAttachment] = useState(
    '{"artifact_id":"","artifact_version_id":"","media_type":"image/png"}',
  );
  const [items, setItems] = useState<Item[]>([]);
  const [runs, setRuns] = useState<Job[]>([]);
  const [receipts, setReceipts] = useState<Receipt[]>([]);
  const [details, setDetails] = useState<unknown>(null);
  const [message, setMessage] = useState("");
  const [offset, setOffset] = useState(0);
  const [definitionOffset, setDefinitionOffset] = useState(0);
  const [image, setImage] = useState("");
  const [watch, setWatch] = useState(false);
  const base = `/api/v1/${family}/${resource}`;
  useEffect(
    () => () => {
      if (image) URL.revokeObjectURL(image);
    },
    [image],
  );
  async function refresh(page = offset) {
    setDetails(null);
    setImage("");
    setDefinitions([]);
    setItems([]);
    setRuns([]);
    setReceipts([]);
    try {
      const versions = await api<Definition[]>(
        `${base}/definitions?limit=50&offset=${definitionOffset}`,
      );
      setDefinitions(versions);
      if (family === "media-sets")
        setItems(await api<Item[]>(`${base}/items?limit=50&offset=${page}`));
      else if (family === "functions")
        setRuns(await api<Job[]>(`${base}/runs?limit=50&offset=${page}`));
      else
        setReceipts(
          await api<Receipt[]>(`${base}/runs?limit=50&offset=${page}`),
        );
    } catch (error) {
      setDefinitions([]);
      setItems([]);
      setRuns([]);
      setReceipts([]);
      throw error;
    }
  }
  useEffect(() => {
    if (!watch || family !== "functions") return;
    let active = true,
      count = 0;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      if (!active || ++count > 120) {
        setWatch(false);
        return;
      }
      if (document.visibilityState === "hidden") {
        timer = setTimeout(poll, 2000);
        return;
      }
      try {
        // The BFF client retains its existing request cancellation/session protections.
        const next = await api<Job[]>(`${base}/runs?limit=50&offset=${offset}`);
        if (!active || controller.signal.aborted) return;
        setRuns(next);
        if (
          !next.some((j) =>
            ["QUEUED", "ADMITTED", "RUNNING", "CANCELLING"].includes(j.state),
          )
        ) {
          setWatch(false);
          return;
        }
        timer = setTimeout(poll, 2000);
      } catch {
        if (active) {
          setRuns([]);
          setDetails(null);
          setWatch(false);
        }
      }
    }
    timer = setTimeout(poll, 2000);
    return () => {
      active = false;
      controller.abort();
      clearTimeout(timer);
    };
  }, [watch, api, base, family, offset]);
  async function binary(item: Item, preview: boolean) {
    setImage("");
    const response = await fetch(
      `/bff/artifacts?${new URLSearchParams({ family: "media-sets", artifact: resource, version: item.id, operation: preview ? "preview" : "download" })}`,
      {
        method: "POST",
        cache: "no-store",
        headers: {
          "x-csrf-token": context.csrf,
          "x-expected-tenant": context.tenant,
        },
      },
    );
    if (!response.ok) {
      setItems([]);
      throw new Error("media_access_failed");
    }
    if (preview) {
      // Only bounded generated JPEG previews become object URLs; originals stream to disk.
      const reader = response.body!.getReader();
      const chunks: Uint8Array<ArrayBuffer>[] = [];
      let bytes = 0;
      try {
        while (true) {
          const part = await reader.read();
          if (part.done) break;
          bytes += part.value.byteLength;
          if (bytes > 1024 ** 2) throw new Error("preview_too_large");
          chunks.push(new Uint8Array(part.value));
        }
      } finally {
        await reader.cancel();
      }
      setImage(URL.createObjectURL(new Blob(chunks, { type: "image/jpeg" })));
    } else {
      if (!("showSaveFilePicker" in window)) {
        await response.body?.cancel();
        throw new Error("Use a browser with streaming file downloads");
      }
      const picker = window as unknown as {
        showSaveFilePicker: (options: unknown) => Promise<{
          createWritable: () => Promise<WritableStream<Uint8Array>>;
        }>;
      };
      try {
        const handle = await picker.showSaveFilePicker({
          suggestedName: item.filename,
        });
        await response.body!.pipeTo(await handle.createWritable());
      } catch (error) {
        await response.body?.cancel().catch(() => {});
        throw error;
      }
    }
  }
  return (
    <details>
      <summary>{family} versions and execution</summary>
      {task.error && <Notice>{task.error}</Notice>}
      <p role="status">{message}</p>
      <button
        disabled={task.busy}
        onClick={() => void task.run(() => refresh())}
      >
        Refresh {family}
      </button>
      <div className="row">
        <button
          disabled={!definitionOffset}
          onClick={() =>
            setDefinitionOffset(Math.max(0, definitionOffset - 50))
          }
        >
          Previous definitions
        </button>
        <button
          disabled={definitions.length < 50 || definitionOffset >= 9950}
          onClick={() => setDefinitionOffset(definitionOffset + 50)}
        >
          More definitions
        </button>
      </div>
      {writable && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void task.run(async () => {
              const result = await api<Definition>(
                `${base}/definitions`,
                "POST",
                JSON.parse(spec),
              );
              setSelected(result.id);
              await refresh();
              setMessage(`Published immutable version ${result.sequence}`);
            });
          }}
        >
          <Field label={`${family} definition JSON`}>
            <textarea
              rows={12}
              value={spec}
              onChange={(e) => setSpec(e.target.value)}
            />
          </Field>
          <button
            type="button"
            disabled={task.busy}
            onClick={() =>
              void task.run(async () => {
                await api(`${base}/validate`, "POST", JSON.parse(spec));
                setMessage("Definition valid");
              })
            }
          >
            Validate definition
          </button>
          <button disabled={task.busy}>Publish version</button>
        </form>
      )}
      <Field label="Published processing version">
        <select value={selected} onChange={(e) => setSelected(e.target.value)}>
          <option value="">Select immutable version</option>
          {definitions.map((v) => (
            <option key={v.id} value={v.id}>
              {v.sequence} · {v.id}
            </option>
          ))}
        </select>
      </Field>
      <button
        disabled={!selected || task.busy}
        onClick={() =>
          void task.run(async () =>
            setDetails(await api(`${base}/definitions/${selected}`)),
          )
        }
      >
        Inspect published definition
      </button>
      {family === "functions" && writable && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void task.run(async () => {
              const run = await api<Job>(`${base}/runs`, "POST", {
                definition_id: selected,
                inputs: JSON.parse(inputs),
                idempotency_key: crypto.randomUUID(),
              });
              await refresh();
              setWatch(true);
              setMessage(`Queued ${run.id}`);
            });
          }}
        >
          <Field label="Function inputs JSON">
            <textarea
              value={inputs}
              onChange={(e) => setInputs(e.target.value)}
            />
          </Field>
          <button disabled={!selected || task.busy}>Invoke function</button>
        </form>
      )}
      {family === "media-sets" && (
        <>
          <p>
            Upload sources using the Artifact workflow, then attach an
            authorized committed version. PNG/JPEG, PCM WAV, H.264/AAC MP4 and
            PDF are supported.
          </p>
          {writable && (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void task.run(async () => {
                  await api(`${base}/items`, "POST", JSON.parse(attachment));
                  await refresh();
                });
              }}
            >
              <Field label="Media artifact reference JSON">
                <textarea
                  value={attachment}
                  onChange={(e) => setAttachment(e.target.value)}
                />
              </Field>
              <button disabled={task.busy}>Attach media</button>
            </form>
          )}
          <button
            disabled={!selected || task.busy}
            onClick={() =>
              void task.run(async () =>
                setItems(
                  await api<Item[]>(
                    `${base}/items?version_id=${selected}&limit=50&offset=${offset}`,
                  ),
                ),
              )
            }
          >
            Inspect snapshot membership
          </button>
          {items.map((item) => (
            <article key={item.id}>
              <p>
                {item.filename} · {item.media_type} · {item.id}
              </p>
              <pre>{JSON.stringify(item.metadata, null, 2)}</pre>
              <button
                onClick={() =>
                  void task.run(async () =>
                    setDetails(await api(`${base}/items/${item.id}/lineage`)),
                  )
                }
              >
                Media provenance
              </button>
              <button onClick={() => void task.run(() => binary(item, false))}>
                Download original
              </button>
              {item.preview_version_id && (
                <button onClick={() => void task.run(() => binary(item, true))}>
                  Preview media
                </button>
              )}
              {writable && (
                <button
                  onClick={() =>
                    setSpec(
                      JSON.stringify(
                        {
                          items: [
                            ...new Set([
                              ...(JSON.parse(spec).items as string[]),
                              item.id,
                            ]),
                          ],
                        },
                        null,
                        2,
                      ),
                    )
                  }
                >
                  Include in next snapshot
                </button>
              )}
            </article>
          ))}
          {image && (
            <img src={image} alt="Authorized media preview" width={256} />
          )}
        </>
      )}
      {family === "automations" && (
        <>
          <p>
            Triggers: manual, interval (at least 60 seconds), daily in UTC, or
            scoped action.committed. Missed scheduled runs coalesce.
          </p>
          {writable && (
            <>
              <button
                disabled={!selected || task.busy}
                onClick={() =>
                  void task.run(async () =>
                    setDetails(
                      await api(`${base}/activation`, "PUT", {
                        definition_id: selected,
                        enabled: true,
                      }),
                    ),
                  )
                }
              >
                Enable automation
              </button>
              <button
                disabled={!selected || task.busy}
                onClick={() =>
                  void task.run(async () =>
                    setDetails(
                      await api(`${base}/activation`, "PUT", {
                        definition_id: selected,
                        enabled: false,
                      }),
                    ),
                  )
                }
              >
                Disable automation
              </button>
              <button
                disabled={task.busy}
                onClick={() =>
                  void task.run(async () => {
                    await api(`${base}/trigger`, "POST", {
                      idempotency_key: crypto.randomUUID(),
                    });
                    await refresh();
                  })
                }
              >
                Trigger manual automation
              </button>
            </>
          )}
          <button
            disabled={task.busy}
            onClick={() =>
              void task.run(async () =>
                setDetails(await api(`${base}/schedule`)),
              )
            }
          >
            Inspect schedule
          </button>
          {receipts.map((r) => (
            <article key={r.id}>
              <p>
                {r.trigger_kind} · {r.trigger_at} · {r.error ?? "dispatched"}
              </p>
              {r.job_id && (
                <button
                  onClick={() =>
                    void task.run(async () =>
                      setDetails(
                        await api(`/api/v1/execution/jobs/${r.job_id}`),
                      ),
                    )
                  }
                >
                  Inspect automation job
                </button>
              )}
            </article>
          ))}
        </>
      )}
      {family === "functions" && (
        <>
          <button disabled={!runs.length} onClick={() => setWatch(!watch)}>
            {watch ? "Stop monitoring" : "Monitor execution (120 polls)"}
          </button>
          {runs.map((run) => (
            <article key={run.id}>
              <p>
                {run.id} · {run.state} · attempts {run.attempts} · {run.error}
              </p>
              <pre>{JSON.stringify(run.metrics, null, 2)}</pre>
              {writable &&
                ["cancel", "retry"].map((op) => (
                  <button
                    key={op}
                    disabled={
                      task.busy ||
                      (op === "retry"
                        ? run.state !== "FAILED"
                        : !["QUEUED", "ADMITTED", "RUNNING"].includes(
                            run.state,
                          ))
                    }
                    onClick={() =>
                      void task.run(async () => {
                        await api(
                          `/api/v1/execution/jobs/${run.id}/${op}`,
                          "POST",
                        );
                        await refresh();
                      })
                    }
                  >
                    {op} function run
                  </button>
                ))}
              <button
                disabled={run.state !== "SUCCEEDED"}
                onClick={() =>
                  void task.run(async () =>
                    setDetails(
                      await api(`/api/v1/function-runs/${run.id}/result`),
                    ),
                  )
                }
              >
                Inspect function result
              </button>
              <button
                onClick={() =>
                  void task.run(async () =>
                    setDetails(
                      await api(`/api/v1/function-runs/${run.id}/provenance`),
                    ),
                  )
                }
              >
                Function provenance
              </button>
            </article>
          ))}
        </>
      )}
      <div className="row">
        <button
          disabled={!offset || task.busy}
          onClick={() => {
            setOffset(Math.max(0, offset - 50));
            void task.run(() => refresh(Math.max(0, offset - 50)));
          }}
        >
          Previous processing page
        </button>
        <button
          disabled={offset >= 9950 || task.busy}
          onClick={() => {
            setOffset(offset + 50);
            void task.run(() => refresh(offset + 50));
          }}
        >
          More processing history
        </button>
      </div>
      {details !== null && <pre>{JSON.stringify(details, null, 2)}</pre>}
    </details>
  );
}
