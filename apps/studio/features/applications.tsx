"use client";
import { manufacturingApplication } from "./application-example";
import { useEffect, useState } from "react";
import type { FoundryClient, components } from "@foundry/sdk";
import type { Client } from "@/lib/api";
import { Field, Notice, useTask } from "@/components/ui";
import {
  ApplicationRuntime,
  ApplicationSession,
  renderers,
  type AppDocument,
  type AppWidget,
  type AppValue,
} from "./application-runtime";
type Resource = components["schemas"]["ResourceView"];
type Schema = components["schemas"]["OntologyDefinition"];
type Value = AppValue;
const id = (prefix: string) =>
  `${prefix}_${crypto.randomUUID().replaceAll("-", "").slice(0, 12)}`;
const empty: AppDocument = {
  format_version: 1,
  title: "New application",
  description: "",
  home: "home",
  pages: [
    { id: "home", title: "Home", description: "", parameters: [], widgets: [] },
  ],
  states: [],
  sources: [],
  dependencies: [],
  actions: [],
  interactions: [],
};
export function CreateApplicationPanel({
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
    <details>
      <summary>Create application</summary>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void task.run(async () => {
            await api(`/api/v1/projects/${project}/applications`, "POST", {
              name,
              folder_id: folder,
            });
            setName("");
            reload();
          });
        }}
      >
        <Field label="Application name">
          <input
            required
            value={name}
            maxLength={200}
            onChange={(e) => setName(e.target.value)}
          />
        </Field>
        <button disabled={task.busy}>Create application</button>
        {task.error && <Notice>{task.error}</Notice>}
      </form>
    </details>
  );
}
export function ApplicationPanel({
  application,
  project,
  writable,
}: {
  application: string;
  project: string;
  writable: boolean;
}) {
  return (
    <details>
      <summary>Open application builder</summary>
      <ApplicationSession>
        {(client) => (
          <ApplicationEditor
            key={client.cacheId}
            client={client}
            application={application}
            project={project}
            writable={writable}
          />
        )}
      </ApplicationSession>
    </details>
  );
}
function ApplicationEditor({
  client,
  application,
  project,
  writable,
}: {
  client: FoundryClient;
  application: string;
  project: string;
  writable: boolean;
}) {
  const [doc, setDoc] = useState<AppDocument>(structuredClone(empty));
  const [revision, setRevision] = useState(0),
    [dirty, setDirty] = useState(false),
    [status, setStatus] = useState("Loading…");
  const [pageId, setPage] = useState("home"),
    [selected, select] = useState("");
  const [palette, setPalette] = useState<AppWidget["kind"]>("heading");
  const [diagnostics, setDiagnostics] = useState<
    components["schemas"]["ApplicationValidation"]["diagnostics"]
  >([]);
  const [history, setHistory] = useState<
    components["schemas"]["PublishedApplicationVersion"][]
  >([]);
  const [preview, setPreview] = useState(false);
  const [resources, setResources] = useState<Resource[]>([]),
    [resourceOffset, setResourceOffset] = useState(0),
    [resourceId, setResourceId] = useState("");
  const [schema, setSchema] = useState<Schema>(),
    [objectType, setObjectType] = useState(""),
    [actionId, setActionId] = useState("");
  const task = useTask();
  const path = { application_id: application };
  const page = doc.pages.find((p) => p.id === pageId) ?? doc.pages[0];
  const widget = page?.widgets.find((w) => w.id === selected);
  const change = (mutate: (d: AppDocument) => void) => {
    setDoc((current) => {
      const d = structuredClone(current);
      mutate(d);
      return d;
    });
    setDirty(true);
    setStatus("Unsaved");
    setDiagnostics([]);
  };
  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      const versions = await client.applications.versions(
        { path, query: { limit: 50 } },
        { signal: controller.signal },
      );
      if (!controller.signal.aborted) setHistory(versions);
      if (writable) {
        const draft = await client.applications.draft(
          { path },
          { signal: controller.signal },
        );
        if (draft && !controller.signal.aborted) {
          setDoc(draft.document);
          setRevision(draft.revision);
          setPage(draft.document.home);
        }
      }
      if (!controller.signal.aborted) setStatus("Saved");
    })().catch(() => {
      if (!controller.signal.aborted)
        setStatus("Application or dependency unavailable.");
    });
    return () => controller.abort();
  }, [client, application, writable]);
  useEffect(() => {
    const controller = new AbortController();
    void Promise.all(
      [false, true].map((shared) =>
        client.projects.resources(
          {
            path: { project_id: project },
            query: { limit: 100, offset: resourceOffset, shared },
          },
          { signal: controller.signal },
        ),
      ),
    )
      .then((lists) => {
        if (!controller.signal.aborted)
          setResources(
            lists
              .flat()
              .filter((r) =>
                [
                  "ONTOLOGY_VERSION",
                  "ONTOLOGY_OBJECT_TYPE",
                  "ONTOLOGY_ACTION",
                ].includes(r.resource_type),
              ),
          );
      })
      .catch(() => {
        if (!controller.signal.aborted) setResources([]);
      });
    return () => controller.abort();
  }, [client, project, resourceOffset]);
  useEffect(() => {
    setSchema(undefined);
    const r = resources.find((r) => r.id === resourceId);
    if (!r?.ontology_id || !r.schema_version) return;
    const controller = new AbortController();
    void client.ontologies
      .version(
        { path: { ontology_id: r.ontology_id, version: r.schema_version } },
        { signal: controller.signal },
      )
      .then((v) => {
        if (!controller.signal.aborted) {
          setSchema(v.definition);
          setObjectType(v.definition.object_types?.[0]?.id ?? "");
          setActionId(v.definition.action_types?.[0]?.id ?? "");
        }
      })
      .catch(() => {});
    return () => controller.abort();
  }, [client, resourceId, resources]);
  function patchWidget(update: Partial<AppWidget>) {
    change((d) => {
      const w = d.pages
        .find((p) => p.id === page!.id)!
        .widgets.find((w) => w.id === selected)!;
      Object.assign(w, update);
    });
  }
  function addDependency(d: AppDocument) {
    const r = resources.find((r) => r.id === resourceId)!;
    let dep = d.dependencies.find((v) => v.resource_id === r.id);
    if (!dep) {
      dep = {
        id: id("dep"),
        resource_id: r.id,
        ontology_id: r.ontology_id!,
        schema_version: r.schema_version!,
        policy: "exact_active",
      };
      d.dependencies.push(dep);
    }
    return dep.id;
  }
  function addWidget() {
    const key = id("widget");
    change((d) => {
      const w: AppWidget = {
        id: key,
        kind: palette,
        label: palette.replaceAll("_", " "),
        text: "",
        columns: [],
        options: [],
        layout: "column",
        spacing: "normal",
        align: "stretch",
        parent: null,
        source: null,
        state: null,
        property: null,
        page: null,
        action: null,
        visible: null,
      };
      const inputTypes: Partial<
        Record<AppWidget["kind"], AppDocument["states"][number]["data_type"]>
      > = {
        text_input: "string",
        number_input: "float",
        checkbox: "boolean",
        select: "string",
        date_input: "date",
        table: "selection",
        list: "selection",
        detail: "selection",
        property: "selection",
        status: "selection",
      };
      if (inputTypes[palette]) {
        const sid = id("state");
        d.states.push({
          id: sid,
          data_type: inputTypes[palette]!,
          initial: palette === "checkbox" ? false : null,
        });
        w.state = sid;
      }
      d.pages.find((p) => p.id === page!.id)!.widgets.push(w);
    });
    select(key);
  }
  function move(delta: number) {
    change((d) => {
      const list = d.pages.find((p) => p.id === page!.id)!.widgets;
      const i = list.findIndex((w) => w.id === selected);
      const j = i + delta;
      if (j >= 0 && j < list.length) [list[i], list[j]] = [list[j], list[i]];
    });
  }
  const stateOptions = doc.states.map((s) => (
    <option key={s.id} value={s.id}>
      {s.id} ({s.data_type})
    </option>
  ));
  return (
    <section
      className="application-editor"
      aria-label="Visual application builder"
    >
      <h3>Visual application builder</h3>
      <p role="status">
        {status}
        {dirty ? " · local edits" : ""} · revision {revision}
      </p>
      {task.error && <Notice>{task.error}</Notice>}
      <div className="row">
        <button
          disabled={task.busy}
          onClick={() => {
            if (preview) {
              setPreview(false);
              return;
            }
            void task.run(async () => {
              const result = await client.applications.validate({
                path,
                body: doc as components["schemas"]["ApplicationDocument-Input"],
              });
              setDiagnostics(result.diagnostics);
              if (result.valid) setPreview(true);
              else setStatus("Invalid");
            });
          }}
        >
          {preview ? "Return to editor" : "Preview application"}
        </button>
        {writable && (
          <>
            <button
              disabled={task.busy}
              onClick={() =>
                void task.run(async () => {
                  const saved = await client.applications.saveDraft({
                    path,
                    body: {
                      expected_revision: revision,
                      document:
                        doc as components["schemas"]["ApplicationDocument-Input"],
                    },
                  });
                  setRevision(saved.revision);
                  setDirty(false);
                  setStatus("Saved draft");
                })
              }
            >
              Save application draft
            </button>
            <button
              onClick={() =>
                void task.run(async () => {
                  const result = await client.applications.validate({
                    path,
                    body: doc as components["schemas"]["ApplicationDocument-Input"],
                  });
                  setDiagnostics(result.diagnostics);
                  setStatus(result.valid ? "Valid" : "Invalid");
                })
              }
            >
              Validate application
            </button>
            <button
              disabled={dirty || !revision || task.busy}
              onClick={() =>
                void task.run(async () => {
                  const published = await client.applications.publish({
                    path,
                    body: { expected_revision: revision },
                  });
                  setHistory((h) => [
                    published,
                    ...h.filter((v) => v.id !== published.id),
                  ]);
                  setStatus(`Published version ${published.sequence}`);
                })
              }
            >
              Publish application
            </button>
          </>
        )}
      </div>
      {diagnostics.length > 0 && (
        <ul aria-label="Application diagnostics">
          {diagnostics.map((v, i) => (
            <li key={i} role="alert">
              {v.node}: {v.message}
            </li>
          ))}
        </ul>
      )}
      {preview ? (
        <ApplicationRuntime
          key={`${revision}-${dirty}`}
          client={client}
          document={doc}
        />
      ) : (
        writable && (
          <fieldset disabled={task.busy}>
            <legend>Application document</legend>
            <Field label="Application title">
              <input
                value={doc.title}
                onChange={(e) =>
                  change((d) => {
                    d.title = e.target.value;
                  })
                }
              />
            </Field>
            <Field label="Application description">
              <textarea
                value={doc.description}
                onChange={(e) =>
                  change((d) => {
                    d.description = e.target.value;
                  })
                }
              />
            </Field>
            <div className="app-editor-grid">
              <section>
                <h4>Pages and component tree</h4>
                <Field label="Editing page">
                  <select
                    value={page?.id}
                    onChange={(e) => {
                      setPage(e.target.value);
                      select("");
                    }}
                  >
                    {doc.pages.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.title}
                      </option>
                    ))}
                  </select>
                </Field>
                <button
                  onClick={() => {
                    const key = id("page");
                    change((d) => {
                      d.pages.push({
                        id: key,
                        title: `Page ${d.pages.length + 1}`,
                        description: "",
                        widgets: [],
                        parameters: [],
                      });
                    });
                    setPage(key);
                    select("");
                  }}
                >
                  Add page
                </button>
                <button
                  disabled={page?.id === doc.home || doc.pages.length <= 1}
                  onClick={() => {
                    change((d) => {
                      d.pages = d.pages.filter((p) => p.id !== page?.id);
                    });
                    setPage(doc.home);
                  }}
                >
                  Delete page
                </button>
                {page && (
                  <>
                    <Field label="Page description">
                      <textarea
                        value={page.description}
                        onChange={(e) =>
                          change((d) => {
                            d.pages.find((p) => p.id === page.id)!.description =
                              e.target.value;
                          })
                        }
                      />
                    </Field>
                    <Field label="Page parameters (up to 16 typed states)">
                      <select
                        multiple
                        value={page.parameters}
                        onChange={(e) => {
                          const values = Array.from(
                            e.target.selectedOptions,
                            (o) => o.value,
                          ).slice(0, 16);
                          change((d) => {
                            d.pages.find((p) => p.id === page.id)!.parameters =
                              values;
                          });
                        }}
                      >
                        {stateOptions}
                      </select>
                    </Field>
                    <Field label="Page title">
                      <input
                        value={page.title}
                        onChange={(e) =>
                          change((d) => {
                            d.pages.find((p) => p.id === page.id)!.title =
                              e.target.value;
                          })
                        }
                      />
                    </Field>
                    <button
                      onClick={() =>
                        change((d) => {
                          d.home = page.id;
                        })
                      }
                    >
                      Make home page
                    </button>
                  </>
                )}
                <Field label="Widget palette">
                  <select
                    value={palette}
                    onChange={(e) =>
                      setPalette(e.target.value as AppWidget["kind"])
                    }
                  >
                    {Object.keys(renderers).map((kind) => (
                      <option key={kind}>{kind}</option>
                    ))}
                  </select>
                </Field>
                <button onClick={addWidget}>Insert widget</button>
                <ol>
                  {page?.widgets.map((w) => (
                    <li key={w.id}>
                      <button
                        aria-pressed={selected === w.id}
                        onClick={() => select(w.id)}
                      >
                        {w.label || w.kind} ({w.kind})
                      </button>
                    </li>
                  ))}
                </ol>
                <button disabled={!widget} onClick={() => move(-1)}>
                  Move widget up
                </button>
                <button disabled={!widget} onClick={() => move(1)}>
                  Move widget down
                </button>
                <button
                  disabled={!widget}
                  onClick={() => {
                    change((d) => {
                      const p = d.pages.find((p) => p.id === page!.id)!;
                      p.widgets = p.widgets.filter((w) => w.id !== selected);
                    });
                    select("");
                  }}
                >
                  Delete widget
                </button>
              </section>
              <section>
                <h4>Widget inspector</h4>
                {widget ? (
                  <>
                    <p>Stable ID: {widget.id}</p>
                    <Field label="Widget label">
                      <input
                        value={widget.label}
                        onChange={(e) => patchWidget({ label: e.target.value })}
                      />
                    </Field>
                    <Field label="Widget text">
                      <textarea
                        value={widget.text}
                        onChange={(e) => patchWidget({ text: e.target.value })}
                      />
                    </Field>
                    <Field label="Container parent">
                      <select
                        value={widget.parent ?? ""}
                        onChange={(e) =>
                          patchWidget({ parent: e.target.value || null })
                        }
                      >
                        <option value="">Page root</option>
                        {page?.widgets
                          .filter(
                            (w) =>
                              ["section", "form"].includes(w.kind) &&
                              w.id !== widget.id,
                          )
                          .map((w) => (
                            <option key={w.id} value={w.id}>
                              {w.label}
                            </option>
                          ))}
                      </select>
                    </Field>
                    <Field label="Layout">
                      <select
                        value={widget.layout}
                        onChange={(e) =>
                          patchWidget({
                            layout: e.target.value as AppWidget["layout"],
                          })
                        }
                      >
                        {["column", "row", "grid"].map((v) => (
                          <option key={v}>{v}</option>
                        ))}
                      </select>
                    </Field>
                    <Field label="Alignment">
                      <select
                        value={widget.align}
                        onChange={(e) =>
                          patchWidget({
                            align: e.target.value as AppWidget["align"],
                          })
                        }
                      >
                        {["start", "center", "stretch"].map((v) => (
                          <option key={v}>{v}</option>
                        ))}
                      </select>
                    </Field>
                    <Field label="Spacing">
                      <select
                        value={widget.spacing}
                        onChange={(e) =>
                          patchWidget({
                            spacing: e.target.value as AppWidget["spacing"],
                          })
                        }
                      >
                        {["compact", "normal", "large"].map((v) => (
                          <option key={v}>{v}</option>
                        ))}
                      </select>
                    </Field>
                    <Field label="Data source">
                      <select
                        value={widget.source ?? ""}
                        onChange={(e) =>
                          patchWidget({ source: e.target.value || null })
                        }
                      >
                        <option value="">None</option>
                        {doc.sources.map((s) => (
                          <option key={s.id}>{s.id}</option>
                        ))}
                      </select>
                    </Field>
                    <Field label="State / selected object">
                      <select
                        value={widget.state ?? ""}
                        onChange={(e) =>
                          patchWidget({ state: e.target.value || null })
                        }
                      >
                        <option value="">None</option>
                        {stateOptions}
                      </select>
                    </Field>
                    <Field label="Property / metric">
                      <input
                        value={widget.property ?? ""}
                        onChange={(e) =>
                          patchWidget({ property: e.target.value || null })
                        }
                      />
                    </Field>
                    <Field label="Table columns (comma separated)">
                      <input
                        value={widget.columns.join(",")}
                        onChange={(e) =>
                          patchWidget({
                            columns: e.target.value
                              .split(",")
                              .map((v) => v.trim())
                              .filter(Boolean),
                          })
                        }
                      />
                    </Field>
                    <Field label="Select choices (comma separated)">
                      <input
                        value={widget.options.join(",")}
                        onChange={(e) =>
                          patchWidget({
                            options: e.target.value
                              .split(",")
                              .map((v) => v.trim())
                              .filter(Boolean),
                          })
                        }
                      />
                    </Field>
                    <Field label="Navigate to page">
                      <select
                        value={widget.page ?? ""}
                        onChange={(e) =>
                          patchWidget({ page: e.target.value || null })
                        }
                      >
                        <option value="">None</option>
                        {doc.pages.map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.title}
                          </option>
                        ))}
                      </select>
                    </Field>
                    <Field label="Action binding">
                      <select
                        value={widget.action ?? ""}
                        onChange={(e) =>
                          patchWidget({ action: e.target.value || null })
                        }
                      >
                        <option value="">None</option>
                        {doc.actions.map((a) => (
                          <option key={a.id}>{a.id}</option>
                        ))}
                      </select>
                    </Field>
                    <Field label="Visible when state has value">
                      <select
                        value={widget.visible?.state ?? ""}
                        onChange={(e) =>
                          patchWidget({
                            visible: e.target.value
                              ? {
                                  state: e.target.value,
                                  operator: "not_empty",
                                  value: null,
                                }
                              : null,
                          })
                        }
                      >
                        <option value="">Always</option>
                        {stateOptions}
                      </select>
                    </Field>
                    <h5>Interaction</h5>
                    <p>
                      Inputs and tables update their bound state directly.
                      Navigation uses the page binding.
                    </p>
                    <Field label="Refresh source on click">
                      <select
                        value={
                          doc.interactions.find((i) => i.widget === widget.id)
                            ?.target ?? ""
                        }
                        onChange={(e) =>
                          change((d) => {
                            d.interactions = d.interactions.filter(
                              (i) => i.widget !== widget.id,
                            );
                            if (e.target.value)
                              d.interactions.push({
                                id: id("event"),
                                widget: widget.id,
                                event: "click",
                                kind: "refresh",
                                target: e.target.value,
                              });
                          })
                        }
                      >
                        <option value="">None</option>
                        {doc.sources.map((s) => (
                          <option key={s.id}>{s.id}</option>
                        ))}
                      </select>
                    </Field>
                  </>
                ) : (
                  <p>Select a component to configure it.</p>
                )}
              </section>
            </div>
            <section>
              <h4>Governed ontology dependencies</h4>
              <Field label="Registered ontology resource">
                <select
                  value={resourceId}
                  onChange={(e) => setResourceId(e.target.value)}
                >
                  <option value="">Choose authorized resource</option>
                  {resources.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.name} · {r.schema_version}
                    </option>
                  ))}
                </select>
              </Field>
              <button
                disabled={!resourceOffset}
                onClick={() => setResourceOffset((n) => Math.max(0, n - 100))}
              >
                Previous dependencies
              </button>
              <button
                disabled={resourceOffset >= 10000}
                onClick={() => setResourceOffset((n) => n + 100)}
              >
                More dependencies
              </button>
              {schema && (
                <>
                  <button
                    onClick={() =>
                      void task.run(async () => {
                        const example = manufacturingApplication(
                          resources.find((r) => r.id === resourceId)!,
                          schema,
                        );
                        setDoc(example);
                        setPage(example.home);
                        setDirty(true);
                        setStatus("Unsaved manufacturing example");
                      })
                    }
                  >
                    Insert manufacturing dashboard
                  </button>
                  <Field label="Query object type">
                    <select
                      value={objectType}
                      onChange={(e) => setObjectType(e.target.value)}
                    >
                      {schema.object_types?.map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.name}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <button
                    onClick={() =>
                      change((d) => {
                        d.sources.push({
                          id: id("query"),
                          kind: "query",
                          aggregate: null,
                          dependency: addDependency(d),
                          filters: {},
                          query: {
                            object_type: objectType,
                            limit: 25,
                            order_by: [],
                            traverse: [],
                            pagination: "cursor",
                            offset: 0,
                          },
                        });
                      })
                    }
                  >
                    Add object query
                  </button>
                  <button
                    onClick={() =>
                      change((d) => {
                        d.sources.push({
                          id: id("metric"),
                          kind: "aggregate",
                          dependency: addDependency(d),
                          filters: {},
                          query: {
                            object_type: objectType,
                            limit: 25,
                            order_by: [],
                            traverse: [],
                            pagination: "cursor",
                            offset: 0,
                          },
                          aggregate: {
                            object_type: objectType,
                            traverse: [],
                            metrics: [{ name: "count", operator: "count" }],
                            max_groups: 100,
                          },
                        });
                      })
                    }
                  >
                    Add count metric
                  </button>
                  <Field label="Published action type">
                    <select
                      value={actionId}
                      onChange={(e) => setActionId(e.target.value)}
                    >
                      {schema.action_types?.map((a) => (
                        <option key={a.id} value={a.id}>
                          {a.name}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <button
                    disabled={!actionId}
                    onClick={() =>
                      change((d) => {
                        const a = schema.action_types?.find(
                          (a) => a.id === actionId,
                        )!;
                        const parameters: Record<string, Value> = {};
                        const parameter_types: Record<string, string> = {};
                        a.parameters?.forEach((p) => {
                          parameters[p.id] = {
                            kind: "literal",
                            value: (p.default ?? null) as Value["value"],
                            state: null,
                            property: null,
                          };
                          parameter_types[p.id] = p.data_type;
                        });
                        d.actions.push({
                          id: id("action"),
                          dependency: addDependency(d),
                          action_id: actionId,
                          parameters,
                          parameter_types,
                          confirm: true,
                          refresh: d.sources.map((s) => s.id),
                        });
                      })
                    }
                  >
                    Add governed action binding
                  </button>
                </>
              )}
            </section>
            {doc.dependencies.map((dependency) => (
              <fieldset key={dependency.id}>
                <legend>Dependency {dependency.id}</legend>
                <Field label={`Dependency ${dependency.id} resource`}>
                  <select
                    value={dependency.resource_id}
                    onChange={(e) => {
                      const resource = resources.find(
                        (r) => r.id === e.target.value,
                      );
                      if (!resource?.ontology_id || !resource.schema_version)
                        return;
                      change((d) => {
                        const target = d.dependencies.find(
                          (v) => v.id === dependency.id,
                        )!;
                        target.resource_id = resource.id;
                        target.ontology_id = resource.ontology_id!;
                        target.schema_version = resource.schema_version!;
                      });
                      setResourceId(resource.id);
                    }}
                  >
                    <option value={dependency.resource_id}>
                      Current: {dependency.ontology_id} ·{" "}
                      {dependency.schema_version}
                    </option>
                    {resources
                      .filter(
                        (r) =>
                          r.ontology_id === dependency.ontology_id &&
                          r.id !== dependency.resource_id,
                      )
                      .map((r) => (
                        <option key={r.id} value={r.id}>
                          {r.name} · {r.schema_version}
                        </option>
                      ))}
                  </select>
                </Field>
                <button
                  disabled={
                    doc.sources.some((s) => s.dependency === dependency.id) ||
                    doc.actions.some((a) => a.dependency === dependency.id)
                  }
                  onClick={() =>
                    change((d) => {
                      d.dependencies = d.dependencies.filter(
                        (v) => v.id !== dependency.id,
                      );
                    })
                  }
                >
                  Remove unused dependency {dependency.id}
                </button>
              </fieldset>
            ))}
            {doc.sources.map((source) => (
              <SourceInspector
                key={source.id}
                source={source}
                doc={doc}
                change={change}
                schema={schema}
              />
            ))}
            {doc.actions.map((action) => (
              <fieldset key={action.id}>
                <legend>
                  Action {action.action_id} · {action.id}
                </legend>
                {Object.entries(action.parameters).map(([name, value]) => (
                  <BindingEditor
                    key={name}
                    label={`${name} (${action.parameter_types[name]})`}
                    value={value}
                    doc={doc}
                    set={(value) =>
                      change((d) => {
                        d.actions.find((a) => a.id === action.id)!.parameters[
                          name
                        ] = value;
                      })
                    }
                  />
                ))}
                <button
                  onClick={() =>
                    change((d) => {
                      d.actions = d.actions.filter((a) => a.id !== action.id);
                    })
                  }
                >
                  Remove action binding
                </button>
              </fieldset>
            ))}
          </fieldset>
        )
      )}
      <h4>Immutable published versions</h4>
      {history.length === 0 && <p>No publications yet.</p>}
      <ol>
        {history.map((v) => (
          <li key={v.id}>
            <a href={`/applications/${application}/versions/${v.id}`}>
              Open version {v.sequence}
            </a>{" "}
            · {v.digest.slice(0, 12)} · {v.created_by}
          </li>
        ))}
      </ol>
    </section>
  );
}
function BindingEditor({
  label,
  value,
  doc,
  set,
}: {
  label: string;
  value: Value;
  doc: AppDocument;
  set: (v: Value) => void;
}) {
  return (
    <fieldset>
      <legend>{label}</legend>
      <Field label={`${label} source`}>
        <select
          value={value.kind}
          onChange={(e) =>
            set({
              kind: e.target.value as Value["kind"],
              value: null,
              property: null,
              state:
                e.target.value === "literal"
                  ? null
                  : (doc.states[0]?.id ?? null),
            })
          }
        >
          {["literal", "state", "selected"].map((v) => (
            <option key={v}>{v}</option>
          ))}
        </select>
      </Field>
      {value.kind === "literal" ? (
        <Field label={`${label} value`}>
          <input
            value={String(value.value ?? "")}
            onChange={(e) => {
              const raw = e.target.value;
              set({
                ...value,
                value:
                  /integer|float/.test(label) && raw !== ""
                    ? Number(raw)
                    : /boolean/.test(label)
                      ? raw === "true"
                      : raw,
              });
            }}
          />
        </Field>
      ) : (
        <>
          <Field label={`${label} state`}>
            <select
              value={value.state ?? ""}
              onChange={(e) => set({ ...value, state: e.target.value })}
            >
              <option value="">Select state</option>
              {doc.states.map((s) => (
                <option key={s.id}>{s.id}</option>
              ))}
            </select>
          </Field>
          {value.kind === "selected" && (
            <Field label={`${label} selected property ($id / $version)`}>
              <input
                value={value.property ?? ""}
                onChange={(e) => set({ ...value, property: e.target.value })}
              />
            </Field>
          )}
        </>
      )}
    </fieldset>
  );
}
function SourceInspector({
  source,
  doc,
  change,
  schema,
}: {
  source: AppDocument["sources"][number];
  doc: AppDocument;
  change: (fn: (d: AppDocument) => void) => void;
  schema?: Schema;
}) {
  const [filter, setFilter] = useState("operationalStatus");
  const patch = (fn: (s: typeof source) => void) =>
    change((d) => fn(d.sources.find((s) => s.id === source.id)!));
  return (
    <fieldset>
      <legend>Data source {source.id}</legend>
      <Field label="Projected properties (comma separated)">
        <input
          value={source.query.select?.join(",") ?? ""}
          onChange={(e) =>
            patch((s) => {
              s.query.select = e.target.value
                ? e.target.value.split(",").map((v) => v.trim())
                : null;
            })
          }
        />
      </Field>
      <Field label="Sort property">
        <input
          value={source.query.order_by?.[0]?.property ?? ""}
          onChange={(e) =>
            patch((s) => {
              s.query.order_by = e.target.value
                ? [{ property: e.target.value, direction: "asc" }]
                : [];
            })
          }
        />
      </Field>
      <Field label="Sort direction">
        <select
          value={source.query.order_by?.[0]?.direction ?? "asc"}
          onChange={(e) =>
            patch((s) => {
              if (s.query.order_by?.[0])
                s.query.order_by[0].direction = e.target.value as
                  "asc" | "desc";
            })
          }
        >
          <option>asc</option>
          <option>desc</option>
        </select>
      </Field>
      <Field label="Result page size">
        <input
          type="number"
          min={1}
          max={100}
          value={source.query.limit}
          onChange={(e) =>
            patch((s) => {
              s.query.limit = Number(e.target.value);
            })
          }
        />
      </Field>
      <Field label="Relationship direction">
        <select
          value={source.query.traverse?.[0]?.direction ?? "forward"}
          onChange={(e) =>
            patch((s) => {
              if (s.query.traverse?.[0])
                s.query.traverse[0].direction = e.target.value as
                  "forward" | "inverse";
            })
          }
        >
          <option>forward</option>
          <option>inverse</option>
        </select>
      </Field>
      <Field label="Traverse relationship">
        <select
          value={source.query.traverse?.[0]?.link ?? ""}
          onChange={(e) =>
            patch((s) => {
              s.query.traverse = e.target.value
                ? [{ link: e.target.value, direction: "forward" }]
                : [];
            })
          }
        >
          <option value="">None</option>
          {schema?.link_types?.map((l) => (
            <option key={l.id} value={l.id}>
              {l.name}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Filter property">
        <input value={filter} onChange={(e) => setFilter(e.target.value)} />
      </Field>
      <button
        disabled={!filter}
        onClick={() =>
          patch((s) => {
            s.filters[filter] = {
              kind: "literal",
              value: "",
              state: null,
              property: null,
            };
          })
        }
      >
        Add filter binding
      </button>
      {Object.entries(source.filters).map(([name, value]) => (
        <BindingEditor
          key={name}
          label={name}
          value={value}
          doc={doc}
          set={(value) =>
            patch((s) => {
              s.filters[name] = value;
            })
          }
        />
      ))}
      <button
        onClick={() =>
          change((d) => {
            d.sources = d.sources.filter((s) => s.id !== source.id);
          })
        }
      >
        Remove data source
      </button>
    </fieldset>
  );
}
