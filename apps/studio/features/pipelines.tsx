"use client";
import { useEffect, useState } from "react";
import type { Client } from "@/lib/api";
import type { components } from "@/lib/api-schema";
import { Field, Notice, useTask } from "@/components/ui";
import { PipelineBuilder } from "@/features/pipeline-builder";

type Job = components["schemas"]["ExecutionJobView"];
type Definition = components["schemas"]["DefinitionView"];
const example = JSON.stringify(
  {
    engine: "polars",
    inputs: [{ name: "source", columns: {} }],
    steps: [{ op: "select", columns: ["id"] }],
    output_columns: {},
  },
  null,
  2,
);
export function CreatePipelinePanel({
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
          await api(`/api/v1/projects/${project}/pipelines`, "POST", {
            name,
            folder_id: folder,
          });
          setName("");
          reload();
        });
      }}
    >
      {task.error && <Notice>{task.error}</Notice>}
      <Field label="New pipeline name">
        <input
          required
          value={name}
          maxLength={200}
          onChange={(e) => setName(e.target.value)}
        />
      </Field>
      <button disabled={task.busy}>Create pipeline</button>
    </form>
  );
}
export function PipelinePanel({
  api,
  project,
  pipeline,
  writable,
}: {
  api: Client;
  project: string;
  pipeline: string;
  writable: boolean;
}) {
  const task = useTask();
  const [spec, setSpec] = useState(example);
  const [definitions, setDefinitions] = useState<Definition[]>([]);
  const [definition, setDefinition] = useState("");
  const [inputs, setInputs] = useState(
    '[{"name":"source","dataset_id":"","version_id":""}]',
  );
  const [output, setOutput] = useState("");
  const [isDag, setIsDag] = useState(false);
  const [runs, setRuns] = useState<Job[]>([]);
  const [offset, setOffset] = useState(0);
  const [message, setMessage] = useState("");
  const [lineage, setLineage] = useState<unknown>(null);
  const [outputPreview, setOutputPreview] = useState<unknown>(null);
  const path = `/api/v1/pipelines/${pipeline}`;
  function selectPublished(item?: Definition) {
    setDefinition(item?.id ?? "");
    const specification = item?.specification;
    if (specification && "format_version" in specification) {
      setIsDag(true);
      setInputs(
        JSON.stringify(
          specification.inputs.map(({ name, dataset_id, version_id }) => ({
            name,
            dataset_id,
            version_id,
          })),
          null,
          2,
        ),
      );
    } else setIsDag(false);
  }
  async function refresh(page = offset) {
    setDefinitions(
      await api<Definition[]>(`${path}/definitions?limit=50&offset=0`),
    );
    setRuns(await api<Job[]>(`${path}/runs?limit=50&offset=${page}`));
  }
  useEffect(() => {
    const active = runs.filter((run) =>
      ["QUEUED", "ADMITTED", "RUNNING", "CANCELLING"].includes(run.state),
    );
    if (!active.length) return;
    let cancelled = false;
    let count = 0;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const updates: Job[] = [];
        for (let index = 0; index < active.length; index += 2) {
          if (cancelled) return;
          updates.push(
            ...(await Promise.all(
              active
                .slice(index, index + 2)
                .map((run) => api<Job>(`/api/v1/execution/jobs/${run.id}`)),
            )),
          );
        }
        if (cancelled) return;
        setRuns((current) =>
          current.map(
            (run) => updates.find((update) => update.id === run.id) ?? run,
          ),
        );
        count++;
        if (
          count < 120 &&
          updates.some((run) =>
            ["QUEUED", "ADMITTED", "RUNNING", "CANCELLING"].includes(run.state),
          )
        )
          timer = setTimeout(poll, 2000);
      } catch {
        /* Current session errors are handled by the shared client. */
      }
    }
    timer = setTimeout(poll, 2000);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [
    api,
    runs
      .map(
        (run) =>
          `${run.id}:${["SUCCEEDED", "FAILED", "CANCELLED"].includes(run.state)}`,
      )
      .join(","),
  ]);
  return (
    <details>
      <summary>Pipeline definitions and runs</summary>
      {task.error && <Notice>{task.error}</Notice>}
      <p role="status">{message}</p>
      <button
        disabled={task.busy}
        onClick={() => void task.run(() => refresh())}
      >
        Refresh pipeline
      </button>
      <PipelineBuilder
        api={api}
        project={project}
        pipeline={pipeline}
        writable={writable}
        onPublished={(published, compilation) => {
          setDefinition(published.id);
          setIsDag(
            compilation.specification != null &&
              "format_version" in compilation.specification,
          );
          setInputs(JSON.stringify(compilation.inputs, null, 2));
          setOutput(compilation.output_dataset_id ?? "");
          setMessage(
            `Published immutable visual definition ${published.sequence}`,
          );
          void task.run(() => refresh());
        }}
      />
      <details>
        <summary>
          Advanced canonical JSON editor and compatibility fallback
        </summary>
        {writable && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void task.run(async () => {
                const v = await api<Definition>(
                  `${path}/definitions`,
                  "POST",
                  JSON.parse(spec),
                );
                selectPublished(v);
                setMessage(`Published immutable definition ${v.sequence}`);
                await refresh();
              });
            }}
          >
            <Field label="Transformation specification JSON">
              <textarea
                rows={14}
                value={spec}
                onChange={(e) => setSpec(e.target.value)}
              />
            </Field>
            <button
              type="button"
              disabled={task.busy}
              onClick={() =>
                void task.run(async () => {
                  await api(`${path}/validate`, "POST", JSON.parse(spec));
                  setMessage(
                    "Definition grammar valid; run planning checks input columns and types",
                  );
                })
              }
            >
              Validate definition
            </button>
            <button disabled={task.busy}>Publish definition version</button>
          </form>
        )}
      </details>
      <Field label="Published definition">
        <select
          value={definition}
          onChange={(e) => {
            selectPublished(definitions.find((d) => d.id === e.target.value));
          }}
        >
          <option value="">Select immutable version</option>
          {definitions.map((d) => (
            <option key={d.id} value={d.id}>
              {d.sequence} · {d.id}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Pinned input dataset versions JSON">
        <textarea
          rows={5}
          value={inputs}
          onChange={(e) => setInputs(e.target.value)}
        />
      </Field>
      <Field label="Output dataset ID">
        <input value={output} onChange={(e) => setOutput(e.target.value)} />
      </Field>
      <button
        disabled={task.busy || !writable || !definition || (!isDag && !output)}
        onClick={() =>
          void task.run(async () => {
            const j = await api<Job>(`${path}/runs`, "POST", {
              definition_id: definition,
              inputs: JSON.parse(inputs),
              output_dataset_id: isDag ? null : output,
            });
            setMessage(`Queued run ${j.id}`);
            await refresh();
          })
        }
      >
        Launch run
      </button>
      {runs.map((run) => (
        <article key={run.id}>
          <p>
            {run.id} · {run.state} · attempt {run.attempts}
          </p>
          {run.error && <Notice>{run.error}</Notice>}
          {run.plan_digest && (
            <p>
              Execution plan: <code>{run.plan_digest}</code>
            </p>
          )}
          {run.publication_state && (
            <p>
              Publication: {run.publication_state} ·{" "}
              {run.prepared_output_count ?? 0} prepared outputs
            </p>
          )}
          <ul>
            {run.nodes?.map((node) => (
              <li key={node.node_id}>
                {node.node_id} · {node.state} · attempt {node.attempt}
                {node.error ? ` · ${node.error}` : ""}
              </li>
            ))}
          </ul>
          {run.outputs?.map((item) => (
            <div key={item.output_id}>
              <p>
                Committed output {item.output_id}: {item.dataset_id} /{" "}
                {item.version_id}
              </p>
              <button
                onClick={() =>
                  void task.run(async () =>
                    setOutputPreview(
                      await api(
                        `/api/v1/datasets/${item.dataset_id}/versions/${item.version_id}/preview?limit=20`,
                      ),
                    ),
                  )
                }
              >
                Preview output {item.output_id}
              </button>
              <button
                onClick={() =>
                  void task.run(async () =>
                    setLineage(
                      await api(
                        `/api/v1/datasets/${item.dataset_id}/versions/${item.version_id}/lineage?limit=50`,
                      ),
                    ),
                  )
                }
              >
                {run.outputs?.length === 1
                  ? "Inspect lineage"
                  : `Lineage output ${item.output_id}`}
              </button>
            </div>
          ))}
          <pre>{JSON.stringify(run.metrics, null, 2)}</pre>
          {writable &&
            ["QUEUED", "ADMITTED", "RUNNING"].includes(run.state) && (
              <button
                onClick={() =>
                  void task.run(async () => {
                    await api(
                      `/api/v1/execution/jobs/${run.id}/cancel`,
                      "POST",
                      {},
                    );
                    await refresh();
                  })
                }
              >
                Cancel run
              </button>
            )}
          {writable && run.state === "FAILED" && (
            <button
              onClick={() =>
                void task.run(async () => {
                  await api(
                    `/api/v1/execution/jobs/${run.id}/retry`,
                    "POST",
                    {},
                  );
                  await refresh();
                })
              }
            >
              Retry run
            </button>
          )}
          {run.output_version_id && (
            <>
              <p>Output version: {run.output_version_id}</p>
              <button
                onClick={() =>
                  void task.run(async () =>
                    setOutputPreview(
                      await api(
                        `/api/v1/datasets/${run.output_dataset_id}/versions/${run.output_version_id}/preview?limit=20`,
                      ),
                    ),
                  )
                }
              >
                Inspect output preview
              </button>
              <button
                onClick={() =>
                  void task.run(async () =>
                    setLineage(
                      await api(
                        `/api/v1/datasets/${run.output_dataset_id}/versions/${run.output_version_id}/lineage?limit=50`,
                      ),
                    ),
                  )
                }
              >
                Inspect lineage
              </button>
            </>
          )}
        </article>
      ))}
      <button
        disabled={task.busy || offset === 0}
        onClick={() => {
          const p = Math.max(0, offset - 50);
          setOffset(p);
          void task.run(() => refresh(p));
        }}
      >
        Previous runs
      </button>
      <button
        disabled={task.busy || runs.length < 50}
        onClick={() => {
          const p = offset + 50;
          setOffset(p);
          void task.run(() => refresh(p));
        }}
      >
        Next runs
      </button>
      {outputPreview !== null && (
        <pre>{JSON.stringify(outputPreview, null, 2)}</pre>
      )}
      {lineage !== null && <pre>{JSON.stringify(lineage, null, 2)}</pre>}
    </details>
  );
}
