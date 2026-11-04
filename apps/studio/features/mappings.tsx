"use client";
import { useState } from "react";
import type { Client } from "@/lib/api";
import type { components } from "@/lib/api-schema";
import { Field, Notice, useTask } from "@/components/ui";

type Job = components["schemas"]["ExecutionJobView"];
type Definition = components["schemas"]["MappingDefinitionView"];
const example = JSON.stringify(
  {
    target_resource_id: "",
    ontology_id: "manufacturing",
    schema_version: "1.0.0",
    columns: { factoryId: "String", name: "String" },
    objects: [
      {
        object_type: "Factory",
        identity: {
          components: [{ column: "factoryId", conversion: "string" }],
        },
        properties: {
          factoryName: { column: "name", conversion: "string" },
          location: { constant: "Unknown", conversion: "string" },
        },
      },
    ],
    relationships: [],
    write_policy: "upsert_owned",
    duplicates: "reject",
  },
  null,
  2,
);

export function CreateMappingPanel({
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
          await api(`/api/v1/projects/${project}/mappings`, "POST", {
            name,
            folder_id: folder,
          });
          setName("");
          reload();
        });
      }}
    >
      {task.error && <Notice>{task.error}</Notice>}
      <Field label="New mapping name">
        <input
          required
          value={name}
          maxLength={200}
          onChange={(e) => setName(e.target.value)}
        />
      </Field>
      <button disabled={task.busy}>Create mapping</button>
    </form>
  );
}

export function MappingPanel({
  api,
  mapping,
  writable,
}: {
  api: Client;
  mapping: string;
  writable: boolean;
}) {
  const task = useTask();
  const [spec, setSpec] = useState(example);
  const [definitions, setDefinitions] = useState<Definition[]>([]);
  const [definition, setDefinition] = useState("");
  const [dataset, setDataset] = useState("");
  const [version, setVersion] = useState("");
  const [runs, setRuns] = useState<Job[]>([]);
  const [offset, setOffset] = useState(0);
  const [result, setResult] = useState<unknown>(null);
  const [objectType, setObjectType] = useState("Factory");
  const [objectId, setObjectId] = useState("");
  const base = `/api/v1/mappings/${mapping}`;
  const body = {
    definition_id: definition,
    dataset_id: dataset,
    version_id: version,
  };
  async function refresh(page = offset) {
    setDefinitions(
      await api<Definition[]>(`${base}/definitions?limit=50&offset=0`),
    );
    setRuns(await api<Job[]>(`${base}/runs?limit=50&offset=${page}`));
  }
  return (
    <details>
      <summary>Dataset mapping and materialization</summary>
      {task.error && <Notice>{task.error}</Notice>}
      <p>
        Use immutable dataset and ontology version references. Identity,
        properties, conversions and relationships are configured in the mapping
        JSON.
      </p>
      <button
        disabled={task.busy}
        onClick={() => void task.run(() => refresh())}
      >
        Refresh mapping
      </button>
      <Field label="Mapping specification JSON">
        <textarea
          rows={18}
          value={spec}
          onChange={(e) => setSpec(e.target.value)}
          readOnly={!writable}
        />
      </Field>
      <button
        disabled={task.busy}
        onClick={() =>
          void task.run(async () => {
            await api(`${base}/validate`, "POST", JSON.parse(spec));
            setResult({
              validation: "structural",
              message:
                "Target and mapping structure valid. Source rows have not been validated.",
            });
          })
        }
      >
        Validate mapping structure
      </button>
      {writable && (
        <button
          disabled={task.busy}
          onClick={() =>
            void task.run(async () => {
              const d = await api<Definition>(
                `${base}/definitions`,
                "POST",
                JSON.parse(spec),
              );
              setDefinition(d.id);
              await refresh();
              setResult({ published_definition: d.id });
            })
          }
        >
          Publish mapping definition
        </button>
      )}
      <Field label="Mapping definition version">
        <select
          value={definition}
          onChange={(e) => setDefinition(e.target.value)}
        >
          <option value="">Select immutable definition</option>
          {definitions.map((d) => (
            <option key={d.id} value={d.id}>
              {d.sequence} · {d.id}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Source dataset ID">
        <input value={dataset} onChange={(e) => setDataset(e.target.value)} />
      </Field>
      <Field label="Source dataset version ID">
        <input value={version} onChange={(e) => setVersion(e.target.value)} />
      </Field>
      <button
        disabled={task.busy || !dataset || !version}
        onClick={() =>
          void task.run(async () => {
            setResult(
              await api(`${base}/preview`, "POST", {
                dataset_id: dataset,
                version_id: version,
                specification: JSON.parse(spec),
              }),
            );
          })
        }
      >
        Preview draft sample
      </button>
      <button
        disabled={task.busy || !definition || !dataset || !version}
        onClick={() =>
          void task.run(async () => {
            setResult(await api(`${base}/preview`, "POST", body));
          })
        }
      >
        Preview mapped sample
      </button>
      {writable && (
        <>
          <button
            disabled={task.busy || !definition || !dataset || !version}
            onClick={() =>
              void task.run(async () => {
                setResult(
                  await api(`${base}/runs`, "POST", {
                    ...body,
                    mode: "full_validation",
                  }),
                );
                await refresh();
              })
            }
          >
            Validate full source
          </button>
          <button
            disabled={task.busy || !definition || !dataset || !version}
            onClick={() =>
              void task.run(async () => {
                setResult(await api(`${base}/runs`, "POST", body));
                await refresh();
              })
            }
          >
            Materialize dataset
          </button>
        </>
      )}
      <p>
        Samples do not prove full-source validity. Materialization commits
        visible batches; failed or cancelled runs can retain auditable partial
        results.
      </p>
      <pre aria-label="Mapping result">{JSON.stringify(result, null, 2)}</pre>
      {runs.map((run) => (
        <article key={run.id}>
          <p>
            {run.id} · {run.state} · attempt {run.attempts}
          </p>
          {run.error && <Notice>{run.error}</Notice>}
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
                Cancel materialization
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
              Retry materialization
            </button>
          )}
          <button
            onClick={() =>
              void task.run(async () =>
                setResult(
                  await api(
                    `/api/v1/materialization/runs/${run.id}/provenance?limit=50&offset=0`,
                  ),
                ),
              )
            }
          >
            View source provenance
          </button>
        </article>
      ))}
      <button
        disabled={offset === 0 || task.busy}
        onClick={() =>
          void task.run(async () => {
            const page = Math.max(0, offset - 50);
            setOffset(page);
            await refresh(page);
          })
        }
      >
        Previous mapping runs
      </button>
      <button
        disabled={runs.length < 50 || task.busy}
        onClick={() =>
          void task.run(async () => {
            const page = offset + 50;
            setOffset(page);
            await refresh(page);
          })
        }
      >
        Next mapping runs
      </button>
      <Field label="Materialized object type">
        <input
          value={objectType}
          onChange={(e) => setObjectType(e.target.value)}
        />
      </Field>
      <Field label="Materialized object ID">
        <input value={objectId} onChange={(e) => setObjectId(e.target.value)} />
      </Field>
      <button
        disabled={!objectId || !definition || task.busy}
        onClick={() =>
          void task.run(async () => {
            const selected = definitions.find((d) => d.id === definition);
            if (selected)
              setResult(
                await api(
                  `/api/v1/ontologies/${encodeURIComponent(selected.specification.ontology_id)}/objects/${encodeURIComponent(objectType)}/${encodeURIComponent(objectId)}`,
                ),
              );
          })
        }
      >
        Inspect materialized object
      </button>
    </details>
  );
}
