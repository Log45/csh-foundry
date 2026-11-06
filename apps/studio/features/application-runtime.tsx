"use client";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  createFoundryClient,
  FoundryError,
  type FoundryClient,
  type components,
} from "@foundry/sdk";
import { browserRequest, type BrowserSession } from "@/lib/api";

export type AppDocument = components["schemas"]["ApplicationDocument-Output"];
export type AppWidget = AppDocument["pages"][number]["widgets"][number];
export type AppValue = AppDocument["actions"][number]["parameters"][string];
type Value = AppValue;
type ObjectRow = components["schemas"]["QueryObject"];
type Result =
  components["schemas"]["QueryPage"] | components["schemas"]["AggregateResult"];
type State = Record<string, unknown>;
export function objectProperty(row: ObjectRow | undefined, key: string) {
  return Object.hasOwn(row?.properties ?? {}, key)
    ? row!.properties[key]
    : undefined;
}

export function binding(value: Value, state: State): unknown {
  if (value.kind === "literal") return value.value;
  const item = state[value.state ?? ""];
  if (value.kind === "state") return item;
  if (!item || typeof item !== "object") return undefined;
  const row = item as ObjectRow;
  if (value.property === "$id") return row.object_id;
  if (value.property === "$version") return row.version;
  return Object.hasOwn(row.properties ?? {}, value.property ?? "")
    ? row.properties[value.property!]
    : undefined;
}
export function ApplicationSession({
  children,
}: {
  children: (client: FoundryClient) => ReactNode;
}) {
  const [session, setSession] = useState<BrowserSession>();
  const [error, setError] = useState("");
  const [generation] = useState(() => crypto.randomUUID());
  useEffect(() => {
    let live = true;
    void browserRequest<BrowserSession>("/auth/session")
      .then((s) => {
        if (live) setSession(s);
      })
      .catch(() => {
        if (live) setError("Sign in from the workspace to open applications.");
      });
    const expire = () => {
      setSession(undefined);
      setError("Session changed. Reopen this application from the workspace.");
    };
    window.addEventListener("session-expired", expire);
    return () => {
      live = false;
      window.removeEventListener("session-expired", expire);
    };
  }, []);
  const client = useMemo(
    () =>
      session?.tenant && session.me
        ? createFoundryClient({
            tenantId: session.tenant,
            principalId: session.me.principal.principal_id,
            sessionKey: generation,
            auth: { csrf: session.csrf },
            onSessionExpired: () => {
              setSession(undefined);
              setError("Session expired. Sign in again.");
            },
          })
        : undefined,
    [session, generation],
  );
  useEffect(() => {
    if (!session) return;
    const timer = setTimeout(
      () => {
        client?.invalidate();
        setSession(undefined);
        setError("Session expired. Sign in again.");
      },
      Math.max(0, session.expires - Date.now()),
    );
    // A focus check detects tenant changes made in another tab without polling.
    const check = () => {
      void browserRequest<BrowserSession>("/auth/session")
        .then((s) => {
          if (
            s.tenant !== session.tenant ||
            s.me?.principal.principal_id !==
              session.me?.principal.principal_id ||
            s.csrf !== session.csrf
          ) {
            client?.invalidate();
            setSession(undefined);
            setError("Session changed. Reopen this application.");
          }
        })
        .catch(() => {
          client?.invalidate();
          setSession(undefined);
        });
    };
    window.addEventListener("focus", check);
    return () => {
      clearTimeout(timer);
      window.removeEventListener("focus", check);
    };
  }, [session, client]);
  useEffect(() => {
    if (!client) return;
    const unsubscribe = client.subscribe(() => {
      if (!client.active) {
        setSession(undefined);
        setError(
          "Access or session changed. Reopen this application from the workspace.",
        );
      }
    });
    return () => {
      unsubscribe();
      client.invalidate();
    };
  }, [client]);
  return error ? (
    <p role="alert">
      {error} <a href="/">Workspace</a>
    </p>
  ) : client ? (
    <>{children(client)}</>
  ) : (
    <p role="status">Checking application session…</p>
  );
}

export function PublishedApplication({
  application,
  version,
}: {
  application: string;
  version: string;
}) {
  return (
    <ApplicationSession>
      {(client) => (
        <PublishedLoader
          key={client.cacheId}
          client={client}
          application={application}
          version={version}
        />
      )}
    </ApplicationSession>
  );
}
function PublishedLoader({
  client,
  application,
  version,
}: {
  client: FoundryClient;
  application: string;
  version: string;
}) {
  const [document, setDocument] = useState<AppDocument>();
  const [error, setError] = useState("");
  useEffect(() => {
    const cancel = new AbortController();
    void client.applications
      .runtime(
        { path: { application_id: application, version_id: version } },
        { signal: cancel.signal },
      )
      .then((v) => setDocument(v.document))
      .catch(() => {
        if (!cancel.signal.aborted)
          setError("Application unavailable or dependencies changed.");
      });
    return () => cancel.abort();
  }, [client, application, version]);
  return error ? (
    <p role="alert">{error}</p>
  ) : document ? (
    <ApplicationRuntime
      client={client}
      document={document}
      application={application}
      version={version}
    />
  ) : (
    <p role="status">Loading application…</p>
  );
}

export function ApplicationRuntime({
  client,
  document: doc,
  application,
  version,
}: {
  client: FoundryClient;
  document: AppDocument;
  application?: string;
  version?: string;
}) {
  const [pageId, setPage] = useState(doc.home);
  const [state, setState] = useState<State>(() =>
    Object.fromEntries(doc.states.map((s) => [s.id, s.initial])),
  );
  const [data, setData] = useState<Record<string, Result>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [sorts, setSorts] = useState<
    Record<string, components["schemas"]["Sort"]>
  >({});
  const [cursors, setCursors] = useState<Record<string, string>>({});
  const [feedback, setFeedback] = useState("");
  const [pending, setPending] = useState(false);
  const [confirmation, setConfirmation] = useState<string>();
  const [idempotency, setIdempotency] = useState(() => crypto.randomUUID());
  const page = doc.pages.find((p) => p.id === pageId);
  const sourceIds = useMemo(
    () =>
      Array.from(
        new Set(
          page?.widgets.flatMap((w) => (w.source ? [w.source] : [])) ?? [],
        ),
      ),
    [page],
  );
  useEffect(() => {
    const controller = new AbortController();
    let live = true;
    setData({});
    setErrors({});
    setLoading(true);
    // Four workers, one page of each active source; no eager background pages or polling.
    const queue = [...sourceIds];
    const run = async () => {
      while (queue.length && !controller.signal.aborted) {
        const id = queue.shift()!;
        const source = doc.sources.find((s) => s.id === id);
        if (!source) continue;
        try {
          let result: Result;
          if (application && version)
            result = await client.applications.query(
              {
                path: { application_id: application, version_id: version },
                body: {
                  source_id: id,
                  state: state as Record<string, never>,
                  cursor: cursors[id],
                  order_by: sorts[id] ? [sorts[id]] : undefined,
                },
              },
              { signal: controller.signal },
            );
          else {
            const dep = doc.dependencies.find(
              (d) => d.id === source.dependency,
            )!;
            const filters = Object.entries(source.filters).flatMap(
              ([property, value]) => {
                const resolved = binding(value, state);
                if (value.kind === "selected" && !resolved)
                  throw new Error("Select an object first.");
                return resolved === undefined ||
                  resolved === null ||
                  resolved === ""
                  ? []
                  : [
                      {
                        property,
                        operator: "eq" as const,
                        value: resolved as string,
                      },
                    ];
              },
            );
            if (source.query.filter)
              filters.unshift(source.query.filter as never);
            if (source.aggregate) {
              const combined = [...filters];
              if (source.aggregate.filter)
                combined.push(source.aggregate.filter as never);
              result = await client.objects.aggregate(
                {
                  path: { ontology_id: dep.ontology_id },
                  body: {
                    ...source.aggregate,
                    filter: combined.length ? { and: combined } : undefined,
                  },
                },
                { signal: controller.signal },
              );
            } else
              result = await client.objects.query(
                {
                  path: {
                    ontology_id: dep.ontology_id,
                    type_id: source.query.object_type,
                  },
                  body: {
                    ...source.query,
                    order_by: sorts[id] ? [sorts[id]] : source.query.order_by,
                    cursor: cursors[id],
                    filter: filters.length ? { and: filters } : undefined,
                  },
                },
                { signal: controller.signal },
              );
          }
          if (live) setData((current) => ({ ...current, [id]: result }));
        } catch (e) {
          if (
            e instanceof FoundryError &&
            (e.status === 404 ||
              e.code === "dependency_unavailable" ||
              e.code === "tenant_changed")
          )
            client.invalidate();
          if (live)
            setErrors((current) => ({
              ...current,
              [id]: e instanceof Error ? e.message : "Data unavailable",
            }));
        }
      }
    };
    const timer = setTimeout(() => {
      void Promise.all(
        Array.from({ length: Math.min(4, queue.length) }, run),
      ).finally(() => {
        if (live) setLoading(false);
      });
    }, 150);
    return () => {
      live = false;
      clearTimeout(timer);
      controller.abort();
    };
  }, [
    client,
    doc,
    application,
    version,
    state,
    pageId,
    refresh,
    cursors,
    sourceIds,
    sorts,
  ]);
  const update = (id: string, value: unknown) => {
    const declaration = doc.states.find((s) => s.id === id);
    if (!declaration) return;
    const kind = declaration.data_type;
    const valid =
      value === null ||
      (kind === "selection"
        ? typeof value === "object"
        : kind === "integer"
          ? typeof value === "number" && Number.isInteger(value)
          : kind === "float"
            ? typeof value === "number" && Number.isFinite(value)
            : typeof value === (kind === "boolean" ? "boolean" : "string"));
    if (!valid) {
      setFeedback("Value does not match declared state type.");
      return;
    }
    setState((s) => ({ ...s, [id]: value }));
    setCursors({});
    setConfirmation(undefined);
    setIdempotency(crypto.randomUUID());
  };
  function gesture(
    widget: AppWidget,
    event: "select" | "change" | "click",
    value?: unknown,
  ) {
    if (widget.state && event !== "click") update(widget.state, value);
    const interaction = doc.interactions.find(
      (i) => i.widget === widget.id && i.event === event,
    );
    if (!interaction) return;
    if (interaction.kind === "set") update(interaction.target, value);
    if (interaction.kind === "navigate") {
      setPage(interaction.target);
      setCursors({});
    }
    if (interaction.kind === "refresh") setRefresh((n) => n + 1);
  }
  async function invoke(id: string, preview: boolean) {
    const action = doc.actions.find((a) => a.id === id);
    if (!action) return;
    if (!preview && action.confirm && confirmation !== id) {
      setConfirmation(id);
      return;
    }
    setPending(true);
    setFeedback("");
    try {
      const parameters = Object.fromEntries(
        Object.entries(action.parameters).map(([key, value]) => [
          key,
          binding(value, state),
        ]),
      );
      if (Object.values(parameters).some((v) => v === undefined))
        throw new Error("Complete the form and select an object first.");
      const body = {
        parameters: parameters as Record<string, never>,
        idempotency_key: idempotency,
      };
      if (application && version) {
        const path = {
          application_id: application,
          version_id: version,
          binding_id: id,
        };
        const result = preview
          ? await client.applications.preview({ path, body })
          : await client.applications.execute({ path, body });
        setFeedback(
          preview
            ? `Preview: ${result.changes.length} proposed changes. Execution rechecks permissions.`
            : `Action committed. Execution ${result.execution_id}.`,
        );
      } else {
        const dep = doc.dependencies.find((d) => d.id === action.dependency)!;
        if (!preview) throw new Error("Publish before executing actions.");
        const result = await client.actions.preview({
          path: { ontology_id: dep.ontology_id, action_id: action.action_id },
          body,
        });
        setFeedback(`Preview: ${result.changes.length} proposed changes.`);
      }
      if (!preview) {
        setRefresh((n) => n + 1);
        setState((s) =>
          Object.fromEntries(
            Object.entries(s).map(([key, v]) => [
              key,
              doc.states.find((d) => d.id === key)?.data_type === "selection"
                ? null
                : v,
            ]),
          ),
        );
        setIdempotency(crypto.randomUUID());
      }
      setConfirmation(undefined);
    } catch (e) {
      setFeedback(e instanceof Error ? e.message : "Action failed");
    } finally {
      setPending(false);
    }
  }
  function children(parent: string | null = null): ReactNode {
    return page?.widgets
      .filter((w) => (w.parent ?? null) === parent)
      .map((w) => {
        if (w.visible) {
          const value = state[w.visible.state];
          if (
            w.visible.operator === "equals"
              ? value !== w.visible.value
              : value === undefined || value === null || value === ""
          )
            return null;
        }
        const renderer = renderers[w.kind];
        return (
          <section
            key={w.id}
            className="app-widget"
            aria-label={w.label || w.id}
          >
            {renderer({
              w,
              state,
              result: w.source ? data[w.source] : undefined,
              gesture,
              sort: (property) => {
                if (!w.source) return;
                const key = w.source;
                setSorts((current) => ({
                  ...current,
                  [key]: {
                    property,
                    direction:
                      current[key]?.property === property &&
                      current[key]?.direction === "asc"
                        ? "desc"
                        : "asc",
                  },
                }));
                setCursors({});
              },
              update,
              navigate: (id) => {
                setPage(id);
                setCursors({});
              },
              children,
              invoke,
              pending,
              confirmation,
            })}
            {w.source && errors[w.source] && (
              <p role="alert">{errors[w.source]}</p>
            )}
            {w.source && data[w.source] && "items" in data[w.source] && (
              <div className="row">
                <button
                  disabled={!cursors[w.source]}
                  onClick={() => setCursors((c) => ({ ...c, [w.source!]: "" }))}
                >
                  First page
                </button>
                <button
                  disabled={
                    !(data[w.source] as components["schemas"]["QueryPage"])
                      .next_cursor
                  }
                  onClick={() =>
                    setCursors((c) => ({
                      ...c,
                      [w.source!]: (
                        data[w.source!] as components["schemas"]["QueryPage"]
                      ).next_cursor!,
                    }))
                  }
                >
                  Next results
                </button>
              </div>
            )}
          </section>
        );
      });
  }
  if (doc.format_version !== 1)
    return <p role="alert">Unsupported application format.</p>;
  return (
    <article className="application-runtime">
      <header>
        <h1>{doc.title}</h1>
        <p>{doc.description}</p>
      </header>
      <nav aria-label="Application pages">
        {doc.pages.map((p) => (
          <button
            key={p.id}
            aria-current={p.id === pageId ? "page" : undefined}
            onClick={() => {
              setPage(p.id);
              setCursors({});
            }}
          >
            {p.title}
          </button>
        ))}
      </nav>
      <h2>{page?.title}</h2>
      <p>{page?.description}</p>
      <button onClick={() => setRefresh((n) => n + 1)}>
        Refresh application data
      </button>
      {loading && <p role="status">Loading authorized data…</p>}
      <div className="app-layout column">{children()}</div>
      {feedback && <p role="status">{feedback}</p>}
    </article>
  );
}
type RenderProps = {
  sort: (property: string) => void;
  w: AppWidget;
  state: State;
  result?: Result;
  gesture: (
    w: AppWidget,
    event: "select" | "change" | "click",
    value?: unknown,
  ) => void;
  update: (id: string, value: unknown) => void;
  navigate: (id: string) => void;
  children: (id: string) => ReactNode;
  invoke: (id: string, preview: boolean) => Promise<void>;
  pending: boolean;
  confirmation?: string;
};
const text = (value: unknown) =>
  value === undefined || value === null
    ? "—"
    : typeof value === "object"
      ? JSON.stringify(value)
      : String(value);
const input = ({ w, state, gesture }: RenderProps) => (
  <label>
    {w.label || w.id}
    <input
      type={
        w.kind === "number_input"
          ? "number"
          : w.kind === "date_input"
            ? "date"
            : w.kind === "checkbox"
              ? "checkbox"
              : "text"
      }
      value={w.kind === "checkbox" ? undefined : text(state[w.state!] ?? "")}
      checked={w.kind === "checkbox" ? !!state[w.state!] : undefined}
      onChange={(e) =>
        gesture(
          w,
          "change",
          w.kind === "checkbox"
            ? e.target.checked
            : w.kind === "number_input"
              ? e.target.value === ""
                ? null
                : Number(e.target.value)
              : e.target.value,
        )
      }
    />
  </label>
);
const detail = ({ w, state }: RenderProps) => {
  const selected = state[w.state!] as ObjectRow | undefined;
  if (!selected) return <p>Select an object to view details.</p>;
  return (
    <dl>
      {Object.entries(selected.properties ?? {})
        .filter(([key]) => !w.property || key === w.property)
        .map(([key, value]) => (
          <div key={key}>
            <dt>{key}</dt>
            <dd>{text(value)}</dd>
          </div>
        ))}
    </dl>
  );
};
const table = ({ w, result, gesture, sort }: RenderProps) => {
  if (!result || !("items" in result)) return <p>No data loaded.</p>;
  if (!result.items.length) return <p>No matching objects.</p>;
  // Only property names actually returned by the authorized service appear as headings.
  const visible = new Set(
    result.items.flatMap((row) => Object.keys(row.properties)),
  );
  const columns = (w.columns.length ? w.columns : [...visible]).filter((c) =>
    visible.has(c),
  );
  return (
    <div className="app-table">
      <table>
        <caption>{w.label}</caption>
        <thead>
          <tr>
            <th>Select</th>
            {columns.map((c) => (
              <th key={c}>
                <button onClick={() => sort(c)} aria-label={`Sort by ${c}`}>
                  {c}
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {result.items.map((row) => (
            <tr key={row.object_id}>
              <td>
                <button onClick={() => gesture(w, "select", row)}>
                  Select {row.object_id}
                </button>
              </td>
              {columns.map((c) => (
                <td key={c}>{text(objectProperty(row, c))}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};
const objectList = ({ w, result, gesture }: RenderProps) => {
  if (!result || !("items" in result)) return <p>No data loaded.</p>;
  if (!result.items.length) return <p>No matching objects.</p>;
  return (
    <ul aria-label={w.label}>
      {result.items.map((row) => (
        <li key={row.object_id}>
          <button onClick={() => gesture(w, "select", row)}>
            Select {row.object_id}
          </button>
          <dl>
            {Object.entries(row.properties)
              .filter(([key]) => !w.columns.length || w.columns.includes(key))
              .map(([key, value]) => (
                <div key={key}>
                  <dt>{key}</dt>
                  <dd>{text(value)}</dd>
                </div>
              ))}
          </dl>
        </li>
      ))}
    </ul>
  );
};
const container = ({ w, children }: RenderProps) => (
  <section role={w.kind === "form" ? "form" : undefined} aria-label={w.label}>
    <h3>{w.label}</h3>
    <div className={`app-layout ${w.layout} ${w.spacing} align-${w.align}`}>
      {children(w.id)}
    </div>
  </section>
);
export const renderers: Record<
  AppWidget["kind"],
  (props: RenderProps) => ReactNode
> = {
  heading: ({ w }) => <h3>{w.text || w.label}</h3>,
  text: ({ w }) => <p>{w.text || w.label}</p>,
  label: ({ w }) => <span>{w.text || w.label}</span>,
  table,
  list: objectList,
  detail,
  property: ({ w, state }) => (
    <p>
      {w.label}:{" "}
      {text(
        objectProperty(
          state[w.state!] as ObjectRow | undefined,
          w.property ?? "",
        ),
      )}
    </p>
  ),
  status: ({ w, state }) => (
    <output aria-label={w.label}>
      {text(
        objectProperty(
          state[w.state!] as ObjectRow | undefined,
          w.property ?? "operationalStatus",
        ),
      )}
    </output>
  ),
  metric: ({ w, result }) => (
    <div>
      <h3>{w.label}</h3>
      {result && "groups" in result ? (
        result.groups.map((g, i) => (
          <p key={i}>
            {text(g.key?.value)}{" "}
            {Object.entries(g.values)
              .map(([k, v]) => `${k}: ${text(v.value)}`)
              .join(", ")}
          </p>
        ))
      ) : (
        <p>Configure an aggregate source.</p>
      )}
    </div>
  ),
  navigation: ({ w, navigate, gesture }) => (
    <button
      onClick={() => {
        if (w.page) navigate(w.page);
        gesture(w, "click");
      }}
    >
      {w.label || "Continue"}
    </button>
  ),
  section: container,
  form: container,
  text_input: input,
  number_input: input,
  date_input: input,
  checkbox: input,
  select: ({ w, state, gesture }) => (
    <label>
      {w.label || w.id}
      <select
        value={String(state[w.state!] ?? "")}
        onChange={(e) => gesture(w, "change", e.target.value)}
      >
        <option value="">All / choose…</option>
        {w.options.map((v) => (
          <option key={v}>{v}</option>
        ))}
      </select>
    </label>
  ),
  action: ({ w, invoke, pending, confirmation }) => (
    <div>
      <button disabled={pending} onClick={() => void invoke(w.action!, true)}>
        Preview {w.label}
      </button>
      <button disabled={pending} onClick={() => void invoke(w.action!, false)}>
        {confirmation === w.action ? "Confirm " : "Execute "}
        {w.label}
      </button>
    </div>
  ),
};
