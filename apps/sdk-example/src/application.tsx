"use client";
import { useEffect, useState, useMemo, type ReactNode } from "react";
import {
  createFoundryClient,
  createSessionClient,
  FoundryError,
  type BrowserSession,
} from "@foundry/sdk";
import {
  FoundryProvider,
  useObjectsQuery,
  useDatasetsSchema,
  useDatasetsPreview,
  useExecution,
  ExecutionStatus,
  useMappingsGet,
} from "@foundry/react";
function Result({
  query,
}: {
  query: { isPending: boolean; error: Error | null; data: unknown };
}) {
  return query.error ? (
    <p role="alert">
      {query.error instanceof FoundryError
        ? `${query.error.category}: ${query.error.code}`
        : query.error.message}
    </p>
  ) : query.isPending ? (
    <p role="status">Loading…</p>
  ) : (
    <pre style={{ overflow: "auto", maxHeight: 350 }}>
      {JSON.stringify(query.data, null, 2)}
    </pre>
  );
}
function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section style={{ borderTop: "1px solid #ddd", paddingBlock: 16 }}>
      <h2>{title}</h2>
      {children}
    </section>
  );
}
function Objects() {
  const [ontology, setOntology] = useState("manufacturing"),
    [type, setType] = useState("Machine");
  const [cursor, setCursor] = useState<string | undefined>();
  const query = useObjectsQuery(
    {
      path: { ontology_id: ontology, type_id: type },
      body: { object_type: type, limit: 10, cursor },
    },
    { enabled: !!ontology && !!type },
  );
  return (
    <Panel title="Ontology objects">
      <label>
        Ontology{" "}
        <input
          value={ontology}
          onChange={(e) => {
            setOntology(e.target.value);
            setCursor(undefined);
          }}
        />
      </label>
      <label>
        Object type{" "}
        <input
          value={type}
          onChange={(e) => {
            setType(e.target.value);
            setCursor(undefined);
          }}
        />
      </label>
      <button onClick={() => void query.refetch()}>Refresh objects</button>
      <Result query={query} />
      <button disabled={!cursor} onClick={() => setCursor(undefined)}>
        First page
      </button>
      <button
        disabled={!query.data?.next_cursor}
        onClick={() => setCursor(query.data?.next_cursor ?? undefined)}
      >
        Next page
      </button>
    </Panel>
  );
}
function Dataset() {
  const [dataset, setDataset] = useState(""),
    [version, setVersion] = useState("");
  const input = { path: { dataset_id: dataset, version_id: version } };
  const options = { enabled: !!dataset && !!version };
  const schema = useDatasetsSchema(input, options),
    preview = useDatasetsPreview({ ...input, query: { limit: 10 } }, options);
  return (
    <Panel title="Dataset schema and preview">
      <label>
        Dataset UUID{" "}
        <input value={dataset} onChange={(e) => setDataset(e.target.value)} />
      </label>
      <label>
        Version UUID{" "}
        <input value={version} onChange={(e) => setVersion(e.target.value)} />
      </label>
      {options.enabled && (
        <>
          <h3>Schema</h3>
          <Result query={schema} />
          <h3>Preview</h3>
          <Result query={preview} />
        </>
      )}
    </Panel>
  );
}
function Monitor({ title }: { title: string }) {
  const [id, setId] = useState(""),
    [enabled, setEnabled] = useState(true);
  const query = useExecution(id, { enabled: enabled && !!id, maxPolls: 120 });
  return (
    <Panel title={title}>
      <label>
        {title} UUID{" "}
        <input value={id} onChange={(e) => setId(e.target.value)} />
      </label>
      <label>
        <input
          type="checkbox"
          checked={enabled}
          onChange={(e) => setEnabled(e.target.checked)}
        />
        Monitor
      </label>
      <button disabled={!id} onClick={() => void query.refetch()}>
        Refresh status
      </button>
      {id && (
        <>
          <Result query={query} />
          {query.data && <ExecutionStatus job={query.data} />}
        </>
      )}
    </Panel>
  );
}
function Mapping() {
  const [id, setId] = useState("");
  const query = useMappingsGet({ path: { mapping_id: id } }, { enabled: !!id });
  return (
    <Panel title="Mapping metadata">
      <label>
        Mapping UUID{" "}
        <input value={id} onChange={(e) => setId(e.target.value)} />
      </label>
      {id && <Result query={query} />}
    </Panel>
  );
}
export default function Application() {
  const auth = useMemo(() => createSessionClient(), []);
  const [session, setSession] = useState<BrowserSession | null>(null),
    [generation, setGeneration] = useState(0),
    [error, setError] = useState<string | null>(null),
    [offset, setOffset] = useState(0);
  const expire = () => {
    setSession(null);
    setError("Session expired. Sign in again.");
    setGeneration((v) => v + 1);
  };
  const client = useMemo(() => {
    const principal = session?.me?.principal;
    const id =
      principal && typeof principal === "object" && "principal_id" in principal
        ? principal.principal_id
        : undefined;
    if (!session?.tenant || typeof id !== "string") return null;
    return createFoundryClient({
      baseUrl: process.env.NEXT_PUBLIC_FOUNDRY_API_BASE ?? "/api/v1",
      tenantId: session.tenant,
      principalId: id,
      sessionKey: String(generation),
      auth: { csrf: session.csrf },
      onSessionExpired: expire,
    });
  }, [session, generation]);
  useEffect(() => {
    const controller = new AbortController();
    void auth
      .session(0, controller.signal)
      .then(setSession)
      .catch((e) => {
        if (
          !controller.signal.aborted &&
          e instanceof FoundryError &&
          e.status !== 401
        )
          setError(e.code);
      });
    return () => controller.abort();
  }, [auth]);
  useEffect(() => {
    if (!session) return;
    const timer = setTimeout(
      () => {
        client?.invalidate();
        expire();
      },
      Math.max(0, session.expires - Date.now()),
    );
    return () => clearTimeout(timer);
  }, [session, client]);
  async function run(action: () => Promise<void>) {
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(
        e instanceof FoundryError
          ? `${e.category}: ${e.code}`
          : "Request failed",
      );
    }
  }
  return (
    <main>
      <h1>Foundry SDK example</h1>
      <p>
        Governed APIs through the existing session BFF. Previews and pages are
        bounded. Production remains blocked.
      </p>
      {error && <p role="alert">{error}</p>}
      {!session ? (
        <button
          onClick={() =>
            void run(async () => {
              const result = await auth.login();
              window.location.assign(result.authorization);
            })
          }
        >
          Sign in with OpenID Connect
        </button>
      ) : (
        <>
          <label htmlFor="tenant">Tenant</label>
          <select
            id="tenant"
            value={session.tenant ?? ""}
            onChange={(e) =>
              void run(async () => {
                client?.invalidate();
                setSession(null);
                await auth.selectTenant(e.target.value, session.csrf);
                setGeneration((v) => v + 1);
                setSession(await auth.session());
              })
            }
          >
            <option value="">Select tenant</option>
            {session.tenants.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
          <button
            disabled={offset === 0}
            onClick={() =>
              void run(async () => {
                const next = offset - 100;
                setSession(await auth.session(next));
                setOffset(next);
              })
            }
          >
            Previous tenants
          </button>
          <button
            disabled={session.tenants.length < 100}
            onClick={() =>
              void run(async () => {
                const next = offset + 100;
                setSession(await auth.session(next));
                setOffset(next);
              })
            }
          >
            More tenants
          </button>
          <button
            onClick={() =>
              void run(async () => {
                client?.invalidate();
                setSession(null);
                await auth.logout(session.csrf);
              })
            }
          >
            Sign out
          </button>
        </>
      )}
      {client && (
        <FoundryProvider client={client}>
          <Objects />
          <Dataset />
          <Monitor title="Pipeline run" />
          <Mapping />
          <Monitor title="Materialization run" />
        </FoundryProvider>
      )}
    </main>
  );
}
