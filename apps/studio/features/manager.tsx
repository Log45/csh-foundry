"use client";
import { useEffect, useState } from "react";
import {
  ontologyPath,
  segment,
  type Client,
  type Schema,
  type Version,
  type ObjectType,
  type Property,
  type LinkType,
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
import { Development } from "@/features/development";
import { SchemaGraph } from "@/components/schema-graph";

function PropertyEditor({
  value,
  save,
  remove,
}: {
  value: Property;
  save: (p: Property) => void;
  remove: () => void;
}) {
  const [p, set] = useState(value),
    [advanced, options] = useState(
      json({
        enum: value.enum ?? [],
        default: value.default ?? null,
        has_default: value.has_default ?? false,
        max_length: value.max_length ?? null,
        precision: value.precision ?? null,
        scale: value.scale ?? null,
      }),
    );
  const [error, fail] = useState("");
  return (
    <details>
      <summary>
        {value.name} <code>{value.data_type}</code>
      </summary>
      <div className="grid">
        <Field label="Property ID">
          <input
            value={p.id}
            onChange={(e) => set({ ...p, id: e.target.value })}
          />
        </Field>
        <Field label="Property name">
          <input
            value={p.name}
            onChange={(e) => set({ ...p, name: e.target.value })}
          />
        </Field>
        <Field label="Data type">
          <select
            value={p.data_type}
            onChange={(e) =>
              set({ ...p, data_type: e.target.value as Property["data_type"] })
            }
          >
            {[
              "string",
              "integer",
              "float",
              "boolean",
              "date",
              "timestamp",
              "uuid",
              "decimal",
              "json",
            ].map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </Field>
        <div className="row">
          {(
            ["required", "nullable", "indexed", "unique", "array"] as const
          ).map((k) => (
            <label key={k}>
              <input
                type="checkbox"
                checked={!!p[k]}
                onChange={(e) => set({ ...p, [k]: e.target.checked })}
              />
              {k}
            </label>
          ))}
        </div>
        <JsonEditor
          label="Constraints and default (JSON)"
          value={advanced}
          onChange={options}
        />
      </div>
      {error && <Notice>{error}</Notice>}
      <div className="row">
        <button
          onClick={() => {
            try {
              const a = JSON.parse(advanced);
              const allowed = [
                "enum",
                "default",
                "has_default",
                "max_length",
                "precision",
                "scale",
              ];
              if (
                !a ||
                Array.isArray(a) ||
                Object.keys(a).some((k) => !allowed.includes(k))
              )
                throw Error("Use only the displayed constraint fields");
              save({ ...p, ...a });
              fail("");
            } catch (e) {
              fail(e instanceof Error ? e.message : "Invalid JSON");
            }
          }}
        >
          Apply property
        </button>
        <button className="danger" onClick={remove}>
          Remove property
        </button>
      </div>
    </details>
  );
}
function TypeEditor({
  value,
  save,
  remove,
}: {
  value: ObjectType;
  save: (t: ObjectType) => void;
  remove: () => void;
}) {
  return (
    <div className="panel inset">
      <h3>{value.name}</h3>
      <div className="grid">
        <Field label="Type ID">
          <input
            value={value.id}
            onChange={(e) => save({ ...value, id: e.target.value })}
          />
        </Field>
        <Field label="Type name">
          <input
            value={value.name}
            onChange={(e) => save({ ...value, name: e.target.value })}
          />
        </Field>
        <Field label="Description">
          <input
            value={value.description ?? ""}
            onChange={(e) =>
              save({ ...value, description: e.target.value || null })
            }
          />
        </Field>
        <Field label="Primary key">
          <select
            value={value.primary_key}
            onChange={(e) => save({ ...value, primary_key: e.target.value })}
          >
            {value.properties.map((p) => (
              <option key={p.id}>{p.id}</option>
            ))}
          </select>
        </Field>
      </div>
      {value.properties.map((p, i) => (
        <PropertyEditor
          key={`${i}-${p.id}`}
          value={p}
          save={(next) =>
            save({
              ...value,
              properties: value.properties.map((x, j) => (j === i ? next : x)),
            })
          }
          remove={() =>
            save({
              ...value,
              properties: value.properties.filter((_, j) => j !== i),
            })
          }
        />
      ))}
      <div className="row">
        <button
          onClick={() =>
            save({
              ...value,
              properties: [
                ...value.properties,
                {
                  id: `property${value.properties.length + 1}`,
                  name: "New property",
                  data_type: "string",
                },
              ],
            })
          }
        >
          Add property
        </button>
        <button className="danger" onClick={remove}>
          Remove type
        </button>
      </div>
    </div>
  );
}
export function Manager({
  api,
  id,
  tenant,
  can,
  refresh,
}: {
  api: Client;
  id: string;
  tenant: string;
  can: (p: string) => boolean;
  refresh: () => void;
}) {
  const [versions, setVersions] = useState<Version[]>([]),
    [version, selectVersion] = useState(""),
    [schema, setSchema] = useState<Schema>(),
    [saved, setSaved] = useState(""),
    [type, selectType] = useState(""),
    [nextVersion, next] = useState(""),
    [plan, setPlan] = useState(""),
    [result, setResult] = useState<unknown>(),
    [page, setPage] = useState(0);
  const task = useTask(),
    base = ontologyPath(id),
    vpath = `${base}/versions/${segment(version)}`;
  const current = versions.find((v) => v.definition.version === version),
    dirty = !!schema && json(schema) !== saved;
  async function load(preferred = version) {
    const list = await api<Version[]>(
      `${base}/versions?limit=100&offset=${page * 100}`,
    );
    setVersions(list);
    const chosen =
      list.find((v) => v.definition.version === preferred) ?? list[0];
    if (chosen) {
      selectVersion(chosen.definition.version);
      setSchema(chosen.definition);
      setSaved(json(chosen.definition));
      selectType(chosen.definition.object_types?.[0]?.id ?? "");
    } else {
      setSchema(undefined);
      selectVersion("");
    }
  }
  useEffect(() => {
    void task.run(() => load(""));
  }, [id, page]); // workspace remounts on tenant changes
  function choose(value: string) {
    if (dirty && !window.confirm("Discard unsaved schema changes?")) return;
    const v = versions.find((x) => x.definition.version === value);
    if (v) {
      selectVersion(value);
      setSchema(v.definition);
      setSaved(json(v.definition));
      setResult(undefined);
    }
  }
  useEffect(() => {
    const leave = (event: BeforeUnloadEvent) => {
      if (dirty) {
        event.preventDefault();
      }
    };
    const navigate = (event: Event) => {
      if (dirty && !window.confirm("Discard unsaved schema changes?"))
        event.preventDefault();
    };
    window.addEventListener("beforeunload", leave);
    window.addEventListener("workspace-navigation", navigate);
    return () => {
      window.removeEventListener("beforeunload", leave);
      window.removeEventListener("workspace-navigation", navigate);
    };
  }, [dirty]);
  const editable = current?.status === "DRAFT" && can("schema:write");
  async function lifecycle(operation: string, body?: unknown) {
    if (dirty) throw Error("Save the draft before validation or publication");
    const output = await api(`${vpath}/${operation}`, "POST", body);
    setResult(output);
    if (operation !== "validate") {
      await load();
      refresh();
    }
  }
  return (
    <>
      <Development
        api={api}
        ontology={id}
        versions={versions}
        can={can}
        refresh={refresh}
      />
      <Task title="Ontology Manager">
        <div className="row">
          <Field label="Schema version">
            <select value={version} onChange={(e) => choose(e.target.value)}>
              {versions.map((v) => (
                <option key={v.definition.version} value={v.definition.version}>
                  {v.definition.version} · {v.status}
                </option>
              ))}
            </select>
          </Field>
          <span className="badge">{current?.status ?? "No versions"}</span>
          {dirty && <span role="status">Unsaved changes</span>}
          <button
            disabled={task.busy}
            onClick={() => {
              if (!dirty || window.confirm("Discard unsaved changes?"))
                void task.run(() => load());
            }}
          >
            Refresh versions
          </button>
        </div>
        <div className="row">
          <button
            disabled={page === 0 || dirty}
            onClick={() => setPage(page - 1)}
          >
            Previous versions
          </button>
          <button
            disabled={versions.length < 100 || dirty}
            onClick={() => setPage(page + 1)}
          >
            More versions
          </button>
        </div>
        {current && (
          <p className="muted">
            Hash <code>{current.content_hash}</code>
            {current.published_at &&
              ` · Published ${current.published_at} by ${current.published_by}`}
          </p>
        )}
        {schema && (
          <>
            <SchemaGraph schema={schema} select={selectType} />
            <div className="row">
              <Field label="New draft version">
                <input
                  placeholder="2.0.0"
                  value={nextVersion}
                  onChange={(e) => next(e.target.value)}
                />
              </Field>
              <button
                disabled={task.busy || !can("schema:write") || dirty}
                onClick={() =>
                  void task.run(async () => {
                    const v = await api<Version>(`${base}/versions`, "POST", {
                      ...schema,
                      version: nextVersion,
                      tenant_id: tenant,
                    });
                    await load(v.definition.version);
                    next("");
                  })
                }
              >
                Create draft from version
              </button>
            </div>
            <fieldset disabled={!editable || task.busy}>
              <legend>Canonical schema editor</legend>
              <Field label="Ontology name">
                <input
                  value={schema.name}
                  onChange={(e) =>
                    setSchema({ ...schema, name: e.target.value })
                  }
                />
              </Field>
              <Field label="Object type">
                <select
                  value={type}
                  onChange={(e) => selectType(e.target.value)}
                >
                  <option value="">Select type</option>
                  {schema.object_types?.map((t) => (
                    <option key={t.id}>{t.id}</option>
                  ))}
                </select>
              </Field>
              {schema.object_types?.map(
                (t, i) =>
                  t.id === type && (
                    <TypeEditor
                      key={i}
                      value={t}
                      save={(value) => {
                        setSchema({
                          ...schema,
                          object_types: schema.object_types!.map((x, j) =>
                            j === i ? value : x,
                          ),
                        });
                        selectType(value.id);
                      }}
                      remove={() =>
                        setSchema({
                          ...schema,
                          object_types: schema.object_types!.filter(
                            (_, j) => j !== i,
                          ),
                        })
                      }
                    />
                  ),
              )}
              <button
                onClick={() => {
                  const typeId = `Type${(schema.object_types?.length ?? 0) + 1}`;
                  setSchema({
                    ...schema,
                    object_types: [
                      ...(schema.object_types ?? []),
                      {
                        id: typeId,
                        name: typeId,
                        primary_key: "id",
                        properties: [
                          {
                            id: "id",
                            name: "ID",
                            data_type: "string",
                            required: true,
                          },
                        ],
                      },
                    ],
                  });
                  selectType(typeId);
                }}
              >
                Add object type
              </button>
              <h3>Relationships</h3>
              {schema.link_types?.map((l, i) => (
                <div className="grid inset" key={i}>
                  {(
                    [
                      "id",
                      "name",
                      "source_type",
                      "target_type",
                      "cardinality",
                      "inverse_name",
                    ] as const
                  ).map((k) => (
                    <Field key={k} label={`Relationship ${k}`}>
                      {["source_type", "target_type", "cardinality"].includes(
                        k,
                      ) ? (
                        <select
                          value={l[k] ?? ""}
                          onChange={(e) =>
                            setSchema({
                              ...schema,
                              link_types: schema.link_types!.map((x, j) =>
                                i === j ? { ...x, [k]: e.target.value } : x,
                              ),
                            })
                          }
                        >
                          {(k === "cardinality"
                            ? [
                                "one_to_one",
                                "one_to_many",
                                "many_to_one",
                                "many_to_many",
                              ]
                            : (schema.object_types?.map((t) => t.id) ?? [])
                          ).map((x) => (
                            <option key={x}>{x}</option>
                          ))}
                        </select>
                      ) : (
                        <input
                          value={l[k] ?? ""}
                          onChange={(e) =>
                            setSchema({
                              ...schema,
                              link_types: schema.link_types!.map((x, j) =>
                                i === j
                                  ? { ...x, [k]: e.target.value || null }
                                  : x,
                              ),
                            })
                          }
                        />
                      )}
                    </Field>
                  ))}
                  <button
                    className="danger"
                    onClick={() =>
                      setSchema({
                        ...schema,
                        link_types: schema.link_types!.filter(
                          (_, j) => j !== i,
                        ),
                      })
                    }
                  >
                    Remove relationship
                  </button>
                </div>
              ))}
              <button
                disabled={!schema.object_types?.length}
                onClick={() => {
                  const first = schema.object_types![0].id;
                  setSchema({
                    ...schema,
                    link_types: [
                      ...(schema.link_types ?? []),
                      {
                        id: `link${(schema.link_types?.length ?? 0) + 1}`,
                        name: "New relationship",
                        source_type: first,
                        target_type: first,
                        cardinality: "many_to_many",
                      } as LinkType,
                    ],
                  });
                }}
              >
                Add relationship
              </button>
              <h3>Action types</h3>
              <p>
                Typed parameters, bindings, preconditions and supported
                transactional operations. Definitions are validated by the
                canonical registry.
              </p>
              <ActionEditor
                value={schema.action_types ?? []}
                save={(value) => setSchema({ ...schema, action_types: value })}
              />
              <button
                className="primary"
                disabled={!dirty}
                onClick={() =>
                  void task.run(async () => {
                    const value = await api<Version>(
                      vpath + `?expected_hash=${current?.content_hash}`,
                      "PUT",
                      schema,
                    );
                    setSaved(json(value.definition));
                    setSchema(value.definition);
                    setResult({ status: "Draft saved" });
                    await load();
                  })
                }
              >
                Save draft
              </button>
            </fieldset>
            <div className="row">
              <button
                disabled={task.busy || dirty || !can("schema:validate")}
                onClick={() => void task.run(() => lifecycle("validate"))}
              >
                Validate compatibility
              </button>
              <Field label="Approved migration plan ID (when required)">
                <input value={plan} onChange={(e) => setPlan(e.target.value)} />
              </Field>
              <button
                disabled={
                  task.busy ||
                  dirty ||
                  current?.status !== "DRAFT" ||
                  !can("schema:publish")
                }
                onClick={() => {
                  if (window.confirm(`Publish immutable schema ${version}?`))
                    void task.run(() =>
                      lifecycle("publish", { plan_id: plan || null }),
                    );
                }}
              >
                Publish schema
              </button>
              <button
                disabled={
                  task.busy ||
                  dirty ||
                  current?.status !== "PUBLISHED" ||
                  !can("schema:activate")
                }
                onClick={() => {
                  if (
                    window.confirm(
                      `Activate ${version} and validate existing objects in one transaction?`,
                    )
                  )
                    void task.run(() =>
                      lifecycle("activate", { plan_id: plan || null }),
                    );
                }}
              >
                Activate schema
              </button>
            </div>
          </>
        )}
        {task.busy && <p role="status">Working…</p>}
        {task.error && <Notice>{task.error}</Notice>}
        <Result value={result} />
      </Task>
      {schema && (
        <Interchange
          key={version}
          api={api}
          base={base}
          version={version}
          can={can}
          reload={() => load()}
        />
      )}
    </>
  );
}
function ActionEditor({
  value,
  save,
}: {
  value: NonNullable<Schema["action_types"]>;
  save: (v: NonNullable<Schema["action_types"]>) => void;
}) {
  const [text, set] = useState(json(value)),
    [error, fail] = useState("");
  useEffect(() => set(json(value)), [value]);
  return (
    <>
      <JsonEditor
        label="Action definitions (JSON array)"
        value={text}
        onChange={set}
      />
      <button
        onClick={() => {
          try {
            const parsed = JSON.parse(text);
            if (!Array.isArray(parsed)) throw Error("Expected array");
            save(parsed);
            fail("");
          } catch (e) {
            fail(String(e));
          }
        }}
      >
        Apply action definitions
      </button>
      {error && <Notice>{error}</Notice>}
    </>
  );
}
function Interchange({
  api,
  base,
  version,
  can,
  reload,
}: {
  api: Client;
  base: string;
  version: string;
  can: (p: string) => boolean;
  reload: () => Promise<void>;
}) {
  const [text, set] = useState(
      json({
        format: "turtle",
        mode: "PREVIEW_ONLY",
        content: "",
        version: "2.0.0",
        base_version: version,
        mappings: { classes: [], links: [] },
        namespace_mappings: {},
        conflict_choices: {},
      }),
    ),
    [key, setKey] = useState(""),
    [result, setResult] = useState<unknown>();
  const task = useTask();
  return (
    <Task title="OWL interchange & migration review">
      <p>
        Import Turtle or RDF/XML with explicit vocabulary mappings. Unsupported
        axioms remain in the original. Preview, draft creation, publication and
        activation are separate operations.
      </p>
      <JsonEditor
        label="Import and vocabulary mapping request"
        value={text}
        onChange={set}
      />
      <input
        aria-label="Load OWL file"
        type="file"
        accept=".ttl,.owl,.rdf,.xml"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file)
            void task.run(async () => {
              if (file.size > 60000)
                throw Error("File exceeds bounded HTTP import size");
              set(json({ ...JSON.parse(text), content: await file.text() }));
            });
        }}
      />
      <div className="row">
        {["PREVIEW_ONLY", "CREATE_DRAFT"].map((mode) => (
          <button
            key={mode}
            disabled={
              task.busy ||
              !can("ontology:import") ||
              (mode === "CREATE_DRAFT" && !can("schema:write"))
            }
            onClick={() =>
              void task.run(async () => {
                const value = await api<{ id: string }>(
                  `${base}/interchange/imports`,
                  "POST",
                  { ...JSON.parse(text), mode },
                );
                setResult(value);
                setKey(value.id);
                if (mode === "CREATE_DRAFT") await reload();
              })
            }
          >
            {mode === "PREVIEW_ONLY"
              ? "Preview import"
              : "Create imported draft"}
          </button>
        ))}
        <button
          disabled={task.busy || !can("schema:export")}
          onClick={() =>
            void task.run(async () =>
              setResult(
                await api(`${base}/interchange/exports/${segment(version)}`),
              ),
            )
          }
        >
          Export published OWL
        </button>
      </div>
      <Field label="Import ID">
        <input value={key} onChange={(e) => setKey(e.target.value)} />
      </Field>
      <div className="row">
        {["", "/original", "/vocabulary", "/diagnostics"].map((suffix) => (
          <button
            key={suffix}
            disabled={!key || task.busy || !can("ontology:import:read")}
            onClick={() =>
              void task.run(async () =>
                setResult(
                  await api(
                    `${base}/interchange/imports/${segment(key)}${suffix}`,
                  ),
                ),
              )
            }
          >
            {suffix.slice(1) || "Inspect import"}
          </button>
        ))}
      </div>
      <Migration api={api} base={base} version={version} can={can} />
      {task.error && <Notice>{task.error}</Notice>}
      <Result value={result} />
      <button
        disabled={result === undefined}
        onClick={() => {
          const a = document.createElement("a");
          a.href = URL.createObjectURL(
            new Blob([json(result)], { type: "application/json" }),
          );
          a.download = "ontology-interchange.json";
          a.click();
          URL.revokeObjectURL(a.href);
        }}
      >
        Download result and mappings
      </button>
      <button
        disabled={
          !result ||
          !(
            typeof result === "string" ||
            (typeof result === "object" &&
              "content" in result &&
              typeof result.content === "string")
          )
        }
        onClick={() => {
          const text =
            typeof result === "string"
              ? result
              : result && typeof result === "object" && "content" in result
                ? String(result.content)
                : "";
          const a = document.createElement("a");
          a.href = URL.createObjectURL(
            new Blob([text], { type: "text/plain;charset=utf-8" }),
          );
          a.download = "ontology.txt";
          a.click();
          URL.revokeObjectURL(a.href);
        }}
      >
        Download ontology text
      </button>
    </Task>
  );
}
function Migration({
  api,
  base,
  version,
  can,
}: {
  api: Client;
  base: string;
  version: string;
  can: (p: string) => boolean;
}) {
  const [updates, set] = useState('{"updates":[]}'),
    [id, key] = useState(""),
    [result, output] = useState<unknown>();
  const task = useTask();
  return (
    <details>
      <summary>Breaking schema migration plan</summary>
      <JsonEditor label="Migration updates" value={updates} onChange={set} />
      <button
        disabled={task.busy || !can("migration:plan")}
        onClick={() =>
          void task.run(async () => {
            const p = await api<{ id: string }>(
              `${base}/versions/${segment(version)}/migration-plans`,
              "POST",
              JSON.parse(updates),
            );
            output(p);
            key(p.id);
          })
        }
      >
        Create migration plan
      </button>
      <Field label="Migration plan to approve">
        <input value={id} onChange={(e) => key(e.target.value)} />
      </Field>
      <button
        disabled={task.busy || !id || !can("migration:approve")}
        onClick={() =>
          void task.run(async () =>
            output(
              await api(
                `${base}/migration-plans/${segment(id)}/approve`,
                "POST",
              ),
            ),
          )
        }
      >
        Approve migration plan
      </button>
      {task.error && <Notice>{task.error}</Notice>}
      <Result value={result} />
    </details>
  );
}
