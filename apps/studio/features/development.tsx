"use client";
import { useEffect, useState } from "react";
import type { components } from "@/lib/api-schema";
import {
  ontologyPath,
  segment,
  type Client,
  type Schema,
  type Version,
} from "@/lib/api";
import {
  Field,
  JsonEditor,
  Notice,
  Result,
  Task,
  json,
  useTask,
} from "@/components/ui";
import { SchemaGraph } from "@/components/schema-graph";

type Branch = components["schemas"]["BranchView"];
type Revision = components["schemas"]["RevisionView"];
type Preview = components["schemas"]["MergePreview"];
type MergeInput = components["schemas"]["MergeInput"];
type Resolution = components["schemas"]["Resolution"];
type Artifact =
  components["schemas"]["ontology_platform__sdk__service__ArtifactView"];
type Download = components["schemas"]["Download"];

export function Development({
  api,
  ontology,
  versions,
  can,
  refresh,
}: {
  api: Client;
  ontology: string;
  versions: Version[];
  can: (permission: string) => boolean;
  refresh: () => void;
}) {
  const base = ontologyPath(ontology),
    task = useTask();
  const [branches, setBranches] = useState<Branch[]>([]),
    [branchId, selectBranch] = useState("");
  const [name, setName] = useState(""),
    [version, setVersion] = useState("");
  const [head, setHead] = useState<Revision | null>(null),
    [draft, setDraft] = useState("");
  const [sourceId, setSourceId] = useState(""),
    [preview, setPreview] = useState<Preview | null>(null);
  const [resolutions, resolve] = useState<Resolution[]>([]),
    [output, result] = useState<unknown>();
  const [nextVersion, setNextVersion] = useState(""),
    [page, setPage] = useState(0);
  const [language, setLanguage] = useState<"python" | "typescript">("python"),
    [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [previousVersion, setPreviousVersion] = useState("");
  const published = versions.filter((v) => v.status === "PUBLISHED");
  const selectedVersion = version || published[0]?.definition.version || "";
  const branch = branches.find((b) => b.id === branchId);
  const source = branches.find((b) => b.id === sourceId);
  const editable = branch?.state === "ACTIVE" && can("schema:write");
  const dirty =
    !!head && head.branch_id === branchId && draft !== json(head.definition);
  useEffect(() => {
    const leave = (event: BeforeUnloadEvent) => {
      if (dirty) event.preventDefault();
    };
    const navigate = (event: Event) => {
      if (dirty && !window.confirm("Discard unsaved branch changes?"))
        event.preventDefault();
    };
    window.addEventListener("beforeunload", leave);
    window.addEventListener("workspace-navigation", navigate);
    return () => {
      window.removeEventListener("beforeunload", leave);
      window.removeEventListener("workspace-navigation", navigate);
    };
  }, [dirty]);

  async function load() {
    const [b, a] = await Promise.all([
      api<Branch[]>(`${base}/branches?limit=50&offset=${page * 50}`),
      api<Artifact[]>(`${base}/sdk/artifacts?limit=50&offset=0`),
    ]);
    setBranches(b);
    setArtifacts(a);
  }
  useEffect(() => {
    void task.run(load);
  }, [api, ontology, page]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    setHead(null);
    setDraft("");
    setPreview(null);
    resolve([]);
    result(undefined);
    if (branchId)
      void task.run(async () => {
        const value = await api<Revision>(
          `${base}/branches/${segment(branchId)}/head`,
        );
        setHead(value);
        setDraft(json(value.definition));
      });
  }, [branchId]); // eslint-disable-line react-hooks/exhaustive-deps
  const request = (): MergeInput => {
    if (!head || !source) throw Error("Select target and source branches");
    return {
      source_branch: source.id,
      source_revision: source.head_revision,
      target_revision: head.revision,
      resolutions,
    };
  };
  function resolution(
    conflict: string,
    strategy: Resolution["strategy"],
    value?: Resolution["value"],
  ) {
    resolve((old) => [
      ...old.filter((r) => r.conflict !== conflict),
      { conflict, strategy, value },
    ]);
    setPreview(null);
  }
  async function download(artifact: Artifact) {
    const value = await api<Download>(
      `${base}/sdk/artifacts/${segment(artifact.id)}/download`,
    );
    const bytes = Uint8Array.from(atob(value.archive_base64), (c) =>
      c.charCodeAt(0),
    );
    const url = URL.createObjectURL(
      new Blob([bytes], { type: value.media_type }),
    );
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = value.filename;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return (
    <Task title="Schema branches and SDKs">
      <p>
        Branch drafts and merge previews are development schemas. Publication
        and activation require separate governed steps.
      </p>
      <Field label="Published SDK / branch base version">
        <select
          value={selectedVersion}
          onChange={(e) => setVersion(e.target.value)}
        >
          {!published.length && (
            <option value="">Publish a schema first</option>
          )}
          {published.map((v) => (
            <option key={v.definition.version}>{v.definition.version}</option>
          ))}
        </select>
      </Field>
      <div className="row">
        <Field label="New branch name">
          <input value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <button
          disabled={
            task.busy || !can("schema:write") || !name || !selectedVersion
          }
          onClick={() =>
            void task.run(async () => {
              const created = await api<Branch>(`${base}/branches`, "POST", {
                name,
                base_version: selectedVersion,
              });
              await load();
              selectBranch(created.id);
              setName("");
            })
          }
        >
          Create schema branch
        </button>
        <button disabled={task.busy} onClick={() => void task.run(load)}>
          Refresh development schemas
        </button>
      </div>
      <Field label="Target branch">
        <select
          disabled={task.busy}
          value={branchId}
          onChange={(e) => {
            if (
              !head ||
              draft === json(head.definition) ||
              window.confirm("Discard unsaved branch edits?")
            )
              selectBranch(e.target.value);
          }}
        >
          <option value="">Select branch</option>
          {branches.map((b) => (
            <option key={b.id} value={b.id}>
              {b.name} · {b.state} · revision {b.head_revision}
            </option>
          ))}
        </select>
      </Field>
      <div className="row">
        <button disabled={!page || task.busy} onClick={() => setPage(page - 1)}>
          Previous branches
        </button>
        <button
          disabled={branches.length < 50 || task.busy}
          onClick={() => setPage(page + 1)}
        >
          More branches
        </button>
      </div>
      {branch && head && head.branch_id === branch.id && (
        <>
          <p>
            Branch draft · {branch.name} · {branch.state} · base{" "}
            {branch.base_version} · revision {head.revision}
          </p>
          <p className="muted">
            Created by {branch.created_by} at {branch.created_at}. Head hash:{" "}
            {head.content_hash}
          </p>
          <SchemaGraph schema={head.definition as Schema} select={() => {}} />
          <JsonEditor
            label="Branch canonical schema (JSON)"
            value={draft}
            onChange={(value) => {
              setDraft(value);
              setPreview(null);
            }}
          />
          <div className="row">
            <button
              disabled={!editable || task.busy}
              onClick={() =>
                void task.run(async () => {
                  await api(`${base}/branches/${branch.id}/edit`, "POST", {
                    expected_revision: head.revision,
                    definition: JSON.parse(draft),
                    summary: "Ontology Manager edit",
                  });
                  const next = await api<Revision>(
                    `${base}/branches/${branch.id}/head`,
                  );
                  setHead(next);
                  setDraft(json(next.definition));
                  setPreview(null);
                  await load();
                })
              }
            >
              Save branch revision
            </button>
            <button
              disabled={task.busy}
              onClick={() =>
                void task.run(async () =>
                  result(
                    await api(
                      `${base}/branches/${branch.id}/compare`,
                      "POST",
                      {},
                    ),
                  ),
                )
              }
            >
              Compare branch to base
            </button>
            <button
              disabled={task.busy}
              onClick={() =>
                void task.run(async () =>
                  result(
                    await api(`${base}/branches/${branch.id}/compare`, "POST", {
                      active: true,
                    }),
                  ),
                )
              }
            >
              Compare branch to active
            </button>
            <button
              disabled={task.busy}
              onClick={() =>
                void task.run(async () =>
                  result(
                    await api(
                      `${base}/branches/${branch.id}/revisions?limit=50&offset=0`,
                    ),
                  ),
                )
              }
            >
              Inspect branch history
            </button>
            <button
              disabled={!editable || task.busy}
              onClick={() =>
                void task.run(async () => {
                  if (
                    !window.confirm(
                      "Abandon this branch and preserve its history?",
                    )
                  )
                    return;
                  await api(`${base}/branches/${branch.id}/abandon`, "POST", {
                    expected_revision: head.revision,
                  });
                  await load();
                  setPreview(null);
                })
              }
            >
              Abandon branch
            </button>
          </div>
          <Field label="Source branch for merge">
            <select
              value={sourceId}
              onChange={(e) => {
                setSourceId(e.target.value);
                setPreview(null);
                resolve([]);
              }}
            >
              <option value="">Select source</option>
              {branches
                .filter((b) => b.id !== branch.id && b.state === "ACTIVE")
                .map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name} · revision {b.head_revision}
                  </option>
                ))}
            </select>
          </Field>
          <button
            disabled={
              !editable ||
              !source ||
              task.busy ||
              draft !== json(head.definition)
            }
            onClick={() =>
              void task.run(async () => {
                setPreview(
                  await api<Preview>(
                    `${base}/branches/${branch.id}/merge-preview`,
                    "POST",
                    request(),
                  ),
                );
              })
            }
          >
            Preview resolved merge
          </button>
          {resolutions.length > 0 && (
            <p>
              Selected {resolutions.length} resolutions. Generate a new preview
              before merging.
            </p>
          )}
          {preview && (
            <div className="panel inset">
              <h3>Merge preview · no publication or activation</h3>
              <Result value={preview} />
              {preview.conflicts.map((conflict) => (
                <div key={conflict.id}>
                  <p>
                    {conflict.id} · {conflict.category} ·{" "}
                    {conflict.resolved ? "Resolved" : "Unresolved"}
                  </p>
                  <button onClick={() => resolution(conflict.id, "target")}>
                    Keep target {conflict.id}
                  </button>
                  <button onClick={() => resolution(conflict.id, "source")}>
                    Use source {conflict.id}
                  </button>
                  <button
                    onClick={() => {
                      const value = window.prompt(
                        "Resolved JSON value for " + conflict.id,
                        json(conflict.target),
                      );
                      if (value !== null)
                        void task.run(async () =>
                          resolution(conflict.id, "manual", JSON.parse(value)),
                        );
                    }}
                  >
                    Manually resolve {conflict.id}
                  </button>
                </div>
              ))}
              <button
                disabled={
                  !editable ||
                  task.busy ||
                  !preview.definition ||
                  preview.diagnostics.length > 0 ||
                  preview.conflicts.some((c) => !c.resolved)
                }
                onClick={() =>
                  void task.run(async () => {
                    if (
                      !window.confirm(
                        "Merge source into target branch? This preserves history and does not publish or activate.",
                      )
                    )
                      return;
                    result(
                      await api(`${base}/branches/${branch.id}/merge`, "POST", {
                        ...request(),
                        preview_hash: preview.preview_hash,
                      }),
                    );
                    setPreview(null);
                    resolve([]);
                    const next = await api<Revision>(
                      `${base}/branches/${branch.id}/head`,
                    );
                    setHead(next);
                    setDraft(json(next.definition));
                    await load();
                  })
                }
              >
                Confirm branch merge
              </button>
              <button
                onClick={() => {
                  setPreview(null);
                  resolve([]);
                }}
              >
                Abort merge
              </button>
            </div>
          )}
          <div className="row">
            <Field label="Merged draft version">
              <input
                value={nextVersion}
                placeholder="1.1.0"
                onChange={(e) => setNextVersion(e.target.value)}
              />
            </Field>
            <button
              disabled={
                !can("schema:write") ||
                branch.state === "ABANDONED" ||
                !nextVersion ||
                task.busy
              }
              onClick={() =>
                void task.run(async () => {
                  result(
                    await api(`${base}/branches/${branch.id}/draft`, "POST", {
                      expected_revision: head.revision,
                      version: nextVersion,
                    }),
                  );
                  refresh();
                })
              }
            >
              Create governed draft from branch
            </button>
          </div>
        </>
      )}
      <button
        disabled={task.busy}
        onClick={() =>
          void task.run(async () =>
            result(await api(`${base}/merges?limit=50&offset=0`)),
          )
        }
      >
        Inspect merge provenance
      </button>
      <h3>Published schema SDK generation</h3>
      <Field label="SDK language">
        <select
          value={language}
          onChange={(e) =>
            setLanguage(e.target.value as "python" | "typescript")
          }
        >
          <option value="python">Python</option>
          <option value="typescript">TypeScript</option>
        </select>
      </Field>
      <button
        disabled={!can("schema:read") || !selectedVersion || task.busy}
        onClick={() =>
          void task.run(async () => {
            result(
              await api<Artifact>(`${base}/sdk/generate`, "POST", {
                version: selectedVersion,
                language,
              }),
            );
            await load();
          })
        }
      >
        Generate published SDK
      </button>
      <Field label="Previous published version for SDK compatibility">
        <select
          value={previousVersion}
          onChange={(e) => setPreviousVersion(e.target.value)}
        >
          <option value="">Select previous version</option>
          {published.map((v) => (
            <option key={v.definition.version}>{v.definition.version}</option>
          ))}
        </select>
      </Field>
      <button
        disabled={task.busy || !previousVersion || !selectedVersion}
        onClick={() =>
          void task.run(async () =>
            result(
              await api(`${base}/sdk/compatibility`, "POST", {
                previous_version: previousVersion,
                version: selectedVersion,
              }),
            ),
          )
        }
      >
        Inspect SDK compatibility
      </button>
      {artifacts.map((a) => (
        <div className="panel inset" key={a.id}>
          <p>
            {a.language} · {a.schema_version} · {a.status} · {a.created_at}
          </p>
          <code>{a.content_hash}</code>
          <details>
            <summary>SDK artifact manifest</summary>
            <Result value={a.manifest} />
          </details>
          <button
            disabled={task.busy}
            onClick={() => void task.run(() => download(a))}
          >
            Download {a.language} SDK {a.schema_version}
          </button>
        </div>
      ))}
      <details>
        <summary>Manufacturing SDK usage examples</summary>
        <pre>{`Python: from ontology_sdk import OntologyClient
client = OntologyClient(base_url, token_provider, tenant_id)
machine = await client.Machine.get("MCH-005")

TypeScript: import { OntologyClient } from "@ontology/generated-sdk";
const client = new OntologyClient({baseUrl, tokenProvider, tenantId});
const machines = await client.Machine.query()
  .where(client.Machine.fields.temperatureCelsius.gt("80")).execute();`}</pre>
        <p>
          Use platform API bearer credentials outside the browser. SDKs contain
          no browser session or API tokens. Package README and manifest describe
          source symbols and schema alignment.
        </p>
      </details>
      {task.error && <Notice>{task.error}</Notice>}
      {task.busy && <p role="status">Working on development schema request…</p>}
      {output !== undefined && <Result value={output} />}
    </Task>
  );
}
