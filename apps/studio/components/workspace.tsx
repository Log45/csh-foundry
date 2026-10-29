"use client";
import { useCallback, useEffect, useMemo, useState, useRef } from "react";
import {
  browserRequest,
  client,
  ontologyPath,
  type BrowserSession,
  type Ontology,
  type Version,
} from "@/lib/api";
import { Field, Notice, Task, useTask } from "./ui";
import { Manager } from "@/features/manager";
import { Explorer, Actions } from "@/features/explorer";
import { Operations } from "@/features/operations";
const navigate = () =>
  window.dispatchEvent(new Event("workspace-navigation", { cancelable: true }));
export function Workspace() {
  const [tenantOffset, setTenantOffset] = useState(0);
  const [session, setSession] = useState<BrowserSession>(),
    [expired, setExpired] = useState(false),
    [ontologies, setOntologies] = useState<Ontology[]>([]),
    [id, setId] = useState(""),
    [active, setActive] = useState<Version>(),
    [tab, setTab] = useState("manager"),
    [create, setCreate] = useState({
      id: "",
      name: "",
      namespace: "https://example.org/ontology/",
      version: "1.0.0",
    }),
    [offset, setOffset] = useState(0);
  const task = useTask(),
    api = useMemo(
      () => client(session?.csrf ?? "", session?.tenant ?? ""),
      [session?.csrf, session?.tenant],
    ),
    can = useCallback(
      (p: string) => !!session?.me?.permissions.includes(p),
      [session],
    );
  async function auth(operation: string, body?: unknown) {
    return browserRequest(`/auth/${operation}`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-csrf-token": session?.csrf ?? "",
      },
      body: JSON.stringify(body ?? {}),
    });
  }
  async function loadSession(page = tenantOffset) {
    setSession(
      await browserRequest<BrowserSession>(`/auth/session?offset=${page}`),
    );
    setExpired(false);
  }
  const tenantRef = useRef(session?.tenant);
  tenantRef.current = session?.tenant;
  async function loadOntologies() {
    const selectedTenant = session?.tenant;
    const list = await api<Ontology[]>(
      `/api/v1/ontologies?limit=100&offset=${offset}`,
    );
    if (tenantRef.current !== selectedTenant) return;
    setOntologies(list);
    setId((current) =>
      list.some((o) => o.id === current) ? current : (list[0]?.id ?? ""),
    );
  }
  useEffect(() => {
    void task.run(loadSession);
    const listener = () => {
      setExpired(true);
      setSession(undefined);
      setOntologies([]);
      setActive(undefined);
    };
    window.addEventListener("session-expired", listener);
    return () => window.removeEventListener("session-expired", listener);
  }, []);
  useEffect(() => {
    if (session?.tenant) void task.run(loadOntologies);
  }, [session?.tenant, offset]);
  useEffect(() => {
    setActive(undefined);
    const selected = ontologies.find((o) => o.id === id);
    let valid = true;
    if (selected?.active_version)
      void api<Version>(
        `${ontologyPath(id)}/versions/${selected.active_version}`,
      )
        .then((v) => {
          if (valid) setActive(v);
        })
        .catch(() => {});
    return () => {
      valid = false;
    };
  }, [id, ontologies, api]);
  if (!session || expired)
    return (
      <main className="login">
        <div className="brand">
          ◈ FOUNDRY <span>OPEN ONTOLOGY PLATFORM</span>
        </div>
        <h1>
          Your ontology.
          <br />
          Operational.
        </h1>
        <p>
          Author a shared model. Explore connected data.
          <br />
          Make governed changes with confidence.
        </p>
        {task.busy ? (
          <p role="status">Checking session…</p>
        ) : (
          <button
            className="primary"
            onClick={() =>
              void task.run(async () => {
                const result = await browserRequest<{ authorization: string }>(
                  "/auth/login",
                  { method: "POST" },
                );
                window.location.assign(result.authorization);
              })
            }
          >
            Sign in with OpenID Connect
          </button>
        )}
        {expired && <Notice>Your session expired. Sign in to continue.</Notice>}
        {task.error && !["session_expired"].includes(task.error) && (
          <Notice>{task.error}</Notice>
        )}
        <p className="muted">
          Access requires a provisioned platform membership.
        </p>
      </main>
    );
  const navigation = [
    ["manager", "Ontology Manager", "schema:read"],
    ["explorer", "Objects & Object Sets", "object:query"],
    ["actions", "Actions", "action:invoke"],
    ["objects", "Details & aggregates", "object:read"],
    ["ingestion", "Ingestion", "ingestion:history"],
    ["semantic", "Semantic results", "semantic:history"],
  ].filter(([, , permission]) => can(permission));
  return (
    <div className="shell">
      <a className="skip" href="#main">
        Skip to workspace
      </a>
      <aside>
        <div className="brand">
          ◈ FOUNDRY<span>DEVELOPER WORKSPACE</span>
        </div>
        <Field label="Tenant">
          <select
            value={session.tenant ?? ""}
            onChange={(e) => {
              if (!navigate()) return;
              void task.run(async () => {
                await auth("tenant", { tenant: e.target.value });
                setId("");
                setActive(undefined);
                setOntologies([]);
                await loadSession();
              });
            }}
          >
            <option value="" disabled>
              Select tenant
            </option>
            {session.tenants.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        </Field>
        <div className="row">
          <button
            disabled={tenantOffset === 0 || task.busy}
            onClick={() =>
              void task.run(async () => {
                const n = Math.max(0, tenantOffset - 100);
                setTenantOffset(n);
                await loadSession(n);
              })
            }
          >
            Previous tenants
          </button>
          <button
            disabled={
              session.tenants.length < 100 || tenantOffset >= 10000 || task.busy
            }
            onClick={() =>
              void task.run(async () => {
                const n = tenantOffset + 100;
                setTenantOffset(n);
                await loadSession(n);
              })
            }
          >
            More tenants
          </button>
        </div>
        <Field label="Ontology">
          <select
            value={id}
            onChange={(e) => {
              if (navigate()) setId(e.target.value);
            }}
          >
            <option value="" disabled>
              Select ontology
            </option>
            {ontologies.map((o) => (
              <option key={o.id}>{o.id}</option>
            ))}
          </select>
        </Field>
        <div className="row">
          <button
            disabled={!offset || task.busy}
            onClick={() => setOffset(Math.max(0, offset - 100))}
          >
            Previous
          </button>
          <button
            disabled={ontologies.length < 100 || task.busy}
            onClick={() => setOffset(offset + 100)}
          >
            More
          </button>
        </div>
        <nav aria-label="Workspaces">
          {navigation.map(([key, label]) => (
            <button
              key={key}
              aria-current={tab === key ? "page" : undefined}
              onClick={() => {
                if (navigate()) setTab(key);
              }}
            >
              {label}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <p>PostgreSQL canonical registry</p>
          <button onClick={() => void task.run(loadSession)}>
            Refresh permissions
          </button>
          <button
            onClick={() =>
              void task.run(async () => {
                await auth("logout");
                setSession(undefined);
                setOntologies([]);
                setActive(undefined);
              })
            }
          >
            Sign out
          </button>
        </div>
      </aside>
      <main id="main">
        <header>
          <div>
            <p className="eyebrow">
              {tab === "manager" ? "MODEL & GOVERN" : "EXPLORE & OPERATE"}
            </p>
            <h1>{id || "Welcome to Foundry"}</h1>
          </div>
          <span className="badge">
            {active
              ? `Active ${active.definition.version}`
              : "No active schema"}
          </span>
        </header>
        {task.error && <Notice>{task.error}</Notice>}
        {task.busy && <p role="status">Loading workspace…</p>}
        {!session.tenant && (
          <Task title="Choose your tenant">
            <p>Select an authorized tenant to open its ontologies.</p>
            {!session.tenants.length && (
              <p>
                No enabled memberships. Ask a platform administrator to
                provision access.
              </p>
            )}
          </Task>
        )}
        {session.tenant && can("ontology:create") && (
          <details className="panel">
            <summary>Create ontology</summary>
            <div className="grid">
              {(["id", "name", "namespace", "version"] as const).map((k) => (
                <Field key={k} label={`Ontology ${k}`}>
                  <input
                    value={create[k]}
                    onChange={(e) =>
                      setCreate({ ...create, [k]: e.target.value })
                    }
                  />
                </Field>
              ))}
            </div>
            <button
              disabled={task.busy}
              onClick={() =>
                void task.run(async () => {
                  await api("/api/v1/ontologies", "POST", {
                    ...create,
                    tenant_id: session.tenant,
                    object_types: [],
                    link_types: [],
                    action_types: [],
                  });
                  await loadOntologies();
                  setId(create.id);
                  setTab("manager");
                })
              }
            >
              Create ontology draft
            </button>
          </details>
        )}
        {id && session.tenant && (
          <div key={`${session.tenant}-${id}-${tab}`}>
            {tab === "manager" && can("schema:read") && (
              <Manager
                api={api}
                id={id}
                tenant={session.tenant}
                can={can}
                refresh={() => void task.run(loadOntologies)}
              />
            )}
            {tab !== "manager" && !active && (
              <Task title="Publish and activate a schema">
                <p>
                  Operational tools require an active published schema. Use
                  Ontology Manager to author, validate, publish and activate a
                  version.
                </p>
              </Task>
            )}
            {active && tab === "explorer" && can("object:query") && (
              <Explorer api={api} id={id} schema={active.definition} />
            )}
            {active && tab === "actions" && can("action:invoke") && (
              <Actions api={api} id={id} schema={active.definition} can={can} />
            )}
            {active && ["objects", "ingestion", "semantic"].includes(tab) && (
              <Operations
                kind={tab as "objects" | "ingestion" | "semantic"}
                api={api}
                id={id}
                schema={active.definition}
                can={can}
              />
            )}
          </div>
        )}
      </main>
    </div>
  );
}
