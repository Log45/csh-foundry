"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { Background, Controls, ReactFlow } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { components } from "@/lib/api-schema";
import type { Client } from "@/lib/api";
import { Field, Notice, Result, useTask } from "@/components/ui";

type Resource = components["schemas"]["ResourceView"];
type Project = components["schemas"]["ProjectView"];
type Graph = components["schemas"]["LineageGraph"];
type Node = components["schemas"]["LineageNode"];
type Health = components["schemas"]["HealthSummary"];
type Freshness = components["schemas"]["FreshnessStatus"];
type DependencyFreshness = components["schemas"]["FreshnessDependencies"];
type Dashboard = components["schemas"]["Dashboard"];
type Impact = components["schemas"]["ImpactResult"];
type Execution = components["schemas"]["ExecutionObservation"];
type Columns = components["schemas"]["ColumnLineage"];
type Event = components["schemas"]["EventView"];

export function Observability({ api }: { api: Client }) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [project, setProject] = useState("");
  const [resources, setResources] = useState<Resource[]>([]);
  const [resource, setResource] = useState("");
  const [versions, setVersions] = useState<{ id: string; kind: string }[]>([]);
  const [root, setRoot] = useState<Node>();
  const [direction, setDirection] = useState<"upstream" | "downstream">(
    "upstream",
  );
  const [graph, setGraph] = useState<Graph>();
  const [impact, setImpact] = useState<Impact>();
  const [health, setHealth] = useState<Health>();
  const [freshness, setFreshness] = useState<Freshness>();
  const [dependencyFreshness, setDependencyFreshness] =
    useState<DependencyFreshness>();
  const [dashboard, setDashboard] = useState<Dashboard>();
  const [execution, setExecution] = useState<Execution>();
  const [columns, setColumns] = useState<Columns>();
  const [events, setEvents] = useState<Event[]>([]);
  const [offset, setOffset] = useState(0);
  const [age, setAge] = useState("86400");
  const task = useTask();
  const [loading, setLoading] = useState(0);
  const [loadError, setLoadError] = useState("");
  const busy = task.busy || loading > 0;
  async function load(action: () => Promise<void>) {
    setLoading((count) => count + 1);
    setLoadError("");
    try {
      await action();
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "Load failed");
    } finally {
      setLoading((count) => count - 1);
    }
  }
  const generation = useRef(0);
  const projectGeneration = useRef(0);
  const selected = resources.find((r) => r.id === resource);
  const makeNode = (id: string, kind = "RESOURCE", version?: string): Node => ({
    key: `${kind}:${id}:${version ?? ""}:`,
    kind,
    resource_id: id,
    version_id: version ?? null,
    local_id: null,
  });
  useEffect(() => {
    void load(async () => {
      const list = await api<Project[]>("/api/v1/projects?limit=100&offset=0");
      setProjects(list);
      setProject(list[0]?.id ?? "");
      setDashboard(
        await api<Dashboard>("/api/v1/observability/dashboard?days=7"),
      );
    });
  }, [api]);
  useEffect(() => {
    const current = ++projectGeneration.current;
    setResources([]);
    setResource("");
    setRoot(undefined);
    setGraph(undefined);
    if (project)
      void load(async () => {
        const list = await api<Resource[]>(
          `/api/v1/projects/${project}/resources?limit=100&offset=0`,
        );
        if (projectGeneration.current === current) {
          setResources(list);
          setResource(list[0]?.id ?? "");
        }
      });
  }, [project]);
  useEffect(() => {
    const current = ++generation.current;
    setGraph(undefined);
    setImpact(undefined);
    setVersions([]);
    setHealth(undefined);
    setFreshness(undefined);
    setDependencyFreshness(undefined);
    setExecution(undefined);
    setColumns(undefined);
    setEvents([]);
    setOffset(0);
    setRoot(resource ? makeNode(resource) : undefined);
    if (resource)
      void load(async () => {
        const health = await api<Health>(
          `/api/v1/resources/${resource}/health?limit=50&offset=0`,
        );
        if (current !== generation.current) return;
        setHealth(health);
        const family =
          selected?.resource_type === "DATASET"
            ? "datasets"
            : selected?.resource_type === "PIPELINE"
              ? "pipelines"
              : selected?.resource_type === "APPLICATION"
                ? "applications"
                : selected?.resource_type === "MAPPING"
                  ? "mappings"
                  : undefined;
        if (family) {
          const suffix = ["datasets", "applications"].includes(family)
            ? "versions"
            : "definitions";
          const list = await api<{ id: string }[]>(
            `/api/v1/${family}/${resource}/${suffix}?limit=50&offset=0`,
          );
          if (current !== generation.current) return;
          const kind = (
            {
              datasets: "DATASET_VERSION",
              pipelines: "PIPELINE_DEFINITION",
              applications: "APPLICATION_VERSION",
              mappings: "MAPPING_DEFINITION",
            } as Record<string, string>
          )[family];
          setVersions(list.map((v) => ({ id: v.id, kind })));
          if (list[0]) setRoot(makeNode(resource, kind, list[0].id));
        }
        if (family === "datasets") {
          const fresh = await api<Freshness>(
            `/api/v1/datasets/${resource}/freshness`,
          );
          if (current === generation.current) setFreshness(fresh);
        }
      });
  }, [resource]);
  async function explore(analyze = false) {
    if (!root) return;
    const current = generation.current;
    const body = { root, direction, depth: 6, max_nodes: 100, max_edges: 200 };
    if (analyze) {
      const result = await api<Impact>("/api/v1/lineage/impact", "POST", body);
      if (current === generation.current) {
        setImpact(result);
        setGraph(result.graph);
      }
    } else {
      const result = await api<Graph>("/api/v1/lineage/traverse", "POST", body);
      if (current === generation.current) {
        setGraph(result);
        setImpact(undefined);
      }
    }
  }
  const nodes = useMemo(
    () =>
      (graph?.nodes ?? []).map((n, index) => ({
        id: n.key,
        position: { x: (index % 4) * 250, y: Math.floor(index / 4) * 110 },
        data: {
          label: `${n.kind}\n${n.local_id ?? n.version_id ?? n.resource_id}`,
        },
        ariaLabel: `${n.kind} ${n.version_id ?? n.resource_id}. Select to explore.`,
      })),
    [graph],
  );
  const edges = useMemo(
    () =>
      (graph?.edges ?? []).map((e) => ({
        id: e.id,
        source: e.source.key,
        target: e.target.key,
        label: `${e.relation} · ${e.certainty}`,
        animated: false,
      })),
    [graph],
  );
  return (
    <section aria-label="Lineage and observability">
      <h2>Lineage & observability</h2>
      {(task.error || loadError) && (
        <Notice>
          {task.error || loadError}. Your selection is retained; refresh to
          retry.
        </Notice>
      )}
      <p>
        Explore published dependencies and observed execution provenance. Access
        is checked at every boundary.
      </p>
      <button
        disabled={busy}
        onClick={() =>
          void task.run(async () =>
            setDashboard(
              await api<Dashboard>("/api/v1/observability/dashboard?days=7"),
            ),
          )
        }
      >
        Refresh observability dashboard
      </button>
      {dashboard && (
        <div className="metrics" aria-label="Execution summary">
          {Object.entries(dashboard.execution_counts).map(([state, count]) => (
            <div key={state}>
              <strong>{count}</strong>
              <span>{state}</span>
            </div>
          ))}
          <p>
            Last 7 days; at most 500 authorized executions.
            {dashboard.truncated && " Summary is truncated."}
          </p>
        </div>
      )}
      <div className="row">
        <Field label="Lineage Project">
          <select value={project} onChange={(e) => setProject(e.target.value)}>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Lineage resource">
          <select
            value={resource}
            onChange={(e) => setResource(e.target.value)}
          >
            {resources.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name} · {r.resource_type}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Immutable lineage version">
          <select
            value={root?.version_id ?? ""}
            onChange={(e) => {
              const v = versions.find((v) => v.id === e.target.value);
              setRoot(makeNode(resource, v?.kind ?? "RESOURCE", v?.id));
            }}
          >
            <option value="">Resource dependencies</option>
            {versions.map((v) => (
              <option key={v.id} value={v.id}>
                {v.id}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Traversal direction">
          <select
            value={direction}
            onChange={(e) => setDirection(e.target.value as typeof direction)}
          >
            <option value="upstream">Upstream</option>
            <option value="downstream">Downstream</option>
          </select>
        </Field>
      </div>
      {!resources.length && <p>No authorized resources in this Project.</p>}
      <div className="row">
        <button
          disabled={!project || busy}
          onClick={() => {
            setRoot(makeNode(project, "PROJECT"));
            setDirection("downstream");
          }}
        >
          Select Project lineage
        </button>
        <button
          disabled={!root || busy}
          onClick={() => void task.run(() => explore())}
        >
          Explore lineage
        </button>
        <button
          disabled={!root || busy}
          onClick={() => void task.run(() => explore(true))}
        >
          Analyze downstream impact
        </button>
        <button
          disabled={!resource || busy}
          onClick={() =>
            void task.run(async () => {
              await api(
                `/api/v1/resources/${resource}/lineage/reconcile?batch=50`,
                "POST",
              );
              await explore();
            })
          }
        >
          Reconcile history batch
        </button>
        <button
          disabled={
            selected?.resource_type !== "PIPELINE" || !root?.version_id || busy
          }
          onClick={() =>
            void task.run(async () =>
              setColumns(
                await api<Columns>(
                  `/api/v1/pipelines/${resource}/definitions/${root?.version_id}/columns`,
                ),
              ),
            )
          }
        >
          Inspect column lineage
        </button>
      </div>
      {graph && (
        <>
          <p role="status">
            {graph.indexing.complete
              ? "Indexed history is current for visited resources."
              : "Indexing is incomplete. Missing edges may still be pending."}{" "}
            {graph.truncated && "Graph response limit reached."}
          </p>
          {!graph.edges.length && (
            <p>
              No indexed dependencies found for this selection. Choose a
              published version or reconcile pending history.
            </p>
          )}
          <div style={{ height: 420 }} aria-label="Interactive lineage graph">
            <ReactFlow
              nodes={nodes}
              edges={edges}
              fitView
              nodesDraggable={false}
              onNodeClick={(_, n) =>
                setRoot(graph.nodes.find((v) => v.key === n.id))
              }
            >
              <Background />
              <Controls />
            </ReactFlow>
          </div>
          <div className="table-wrap">
            <table>
              <caption>Accessible lineage node list</caption>
              <thead>
                <tr>
                  <th>Type</th>
                  <th>Identity</th>
                  <th>Navigation</th>
                </tr>
              </thead>
              <tbody>
                {graph.nodes.map((n) => (
                  <tr key={n.key}>
                    <td>{n.kind}</td>
                    <td>{n.local_id ?? n.version_id ?? n.resource_id}</td>
                    <td>
                      <button onClick={() => setRoot(n)}>
                        Select lineage node
                      </button>
                      <button onClick={() => setResource(n.resource_id)}>
                        Open resource observations
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <table>
            <caption>Dependency evidence</caption>
            <thead>
              <tr>
                <th>Relationship</th>
                <th>Mode</th>
                <th>Certainty</th>
                <th>Source evidence</th>
              </tr>
            </thead>
            <tbody>
              {graph.edges.map((e) => (
                <tr key={e.id}>
                  <td>{e.relation}</td>
                  <td>{e.mode}</td>
                  <td>{e.certainty}</td>
                  <td>{e.provenance}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      {impact && (
        <table>
          <caption>Downstream impact paths</caption>
          <thead>
            <tr>
              <th>Target</th>
              <th>Certainty</th>
              <th>Reason</th>
              <th>Path length</th>
            </tr>
          </thead>
          <tbody>
            {impact.paths.map((p) => (
              <tr key={p.target.key}>
                <td>
                  {p.target.kind} {p.target.version_id ?? p.target.resource_id}
                </td>
                <td>{p.certainty}</td>
                <td>{p.reason}</td>
                <td>{p.edges.length}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {columns && (
        <>
          <p>
            {columns.status}: {columns.reason}
          </p>
          <table>
            <caption>Column lineage</caption>
            <thead>
              <tr>
                <th>Output</th>
                <th>Input</th>
                <th>Column</th>
                <th>Dependency</th>
              </tr>
            </thead>
            <tbody>
              {columns.records.map((c, i) => (
                <tr key={i}>
                  <td>{c.output}</td>
                  <td>{c.input_name}</td>
                  <td>{c.input_column}</td>
                  <td>{c.kind}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      {freshness && (
        <section aria-label="Dataset freshness">
          <h3>Dataset freshness: {freshness.state}</h3>
          <p>{freshness.reason}</p>
          <p>
            Last committed version:{" "}
            {freshness.last_committed_at ?? "Unavailable"}
          </p>
          <p>
            Last successful producer:{" "}
            {freshness.last_successful_run_id ??
              "Unavailable or not authorized"}
          </p>
          <p>
            Last failed producer:{" "}
            {freshness.last_failed_run_id ?? "Unavailable or not authorized"}
          </p>
          <button
            disabled={busy}
            onClick={() =>
              void task.run(async () =>
                setDependencyFreshness(
                  await api<DependencyFreshness>(
                    `/api/v1/datasets/${resource}/freshness/dependencies`,
                  ),
                ),
              )
            }
          >
            Inspect upstream freshness
          </button>
          {dependencyFreshness && (
            <>
              <p>
                {dependencyFreshness.indexing_complete
                  ? "Upstream index is current"
                  : "Upstream indexing is incomplete"}
              </p>
              <table>
                <caption>Upstream dataset freshness</caption>
                <thead>
                  <tr>
                    <th>Dataset</th>
                    <th>State</th>
                    <th>Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {dependencyFreshness.statuses.map((s) => (
                    <tr key={s.resource_id}>
                      <td>{s.resource_id}</td>
                      <td>{s.state}</td>
                      <td>{s.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
          <Field label="Maximum version age in seconds">
            <input
              type="number"
              min="60"
              max="31536000"
              value={age}
              onChange={(e) => setAge(e.target.value)}
            />
          </Field>
          <button
            disabled={busy}
            onClick={() =>
              void task.run(async () =>
                setFreshness(
                  await api<Freshness>(
                    `/api/v1/datasets/${resource}/freshness`,
                    "PUT",
                    { enabled: true, max_age_seconds: Number(age) },
                  ),
                ),
              )
            }
          >
            Save freshness policy
          </button>
        </section>
      )}
      {health && (
        <section aria-label="Resource execution history">
          <h3>Execution history</h3>
          <p>
            Consecutive failures on this page: {health.consecutive_failures}
          </p>
          <table>
            <caption>Persisted executions</caption>
            <thead>
              <tr>
                <th>Execution</th>
                <th>State</th>
                <th>Attempts</th>
                <th>Duration</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {health.executions.map((e) => (
                <tr key={e.execution.id}>
                  <td>{e.execution.id}</td>
                  <td>{e.execution.state}</td>
                  <td>{e.execution.attempts}</td>
                  <td>{e.duration_seconds ?? "Unavailable"}</td>
                  <td>
                    <button
                      onClick={() =>
                        void task.run(async () =>
                          setExecution(
                            await api<Execution>(
                              `/api/v1/observability/executions/${e.execution.id}`,
                            ),
                          ),
                        )
                      }
                    >
                      Inspect execution
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <button
            disabled={busy || offset === 0}
            onClick={() =>
              void task.run(async () => {
                const next = Math.max(0, offset - 50);
                setHealth(
                  await api<Health>(
                    `/api/v1/resources/${resource}/health?limit=50&offset=${next}`,
                  ),
                );
                setOffset(next);
              })
            }
          >
            Previous executions
          </button>
          <button
            disabled={busy || !health.history_truncated || offset >= 9950}
            onClick={() =>
              void task.run(async () => {
                const next = offset + 50;
                setHealth(
                  await api<Health>(
                    `/api/v1/resources/${resource}/health?limit=50&offset=${next}`,
                  ),
                );
                setOffset(next);
              })
            }
          >
            More executions
          </button>
        </section>
      )}
      {execution && (
        <section aria-label="Execution detail">
          <h3>Execution detail</h3>
          <p>
            {execution.execution.state} · publication{" "}
            {execution.execution.publication_state ?? "Not applicable"} ·{" "}
            {execution.error_category ?? "No failure"}
          </p>
          <Result value={execution} />
        </section>
      )}
      <button
        disabled={!resource || busy}
        onClick={() =>
          void task.run(async () =>
            setEvents(
              await api<Event[]>(
                `/api/v1/resources/${resource}/events?limit=50&offset=0`,
              ),
            ),
          )
        }
      >
        Load operational events
      </button>
      <table>
        <caption>Recent operational events</caption>
        <thead>
          <tr>
            <th>Time</th>
            <th>State</th>
            <th>Attempt</th>
            <th>Severity</th>
          </tr>
        </thead>
        <tbody>
          {events.map((e) => (
            <tr key={e.id}>
              <td>{e.created_at}</td>
              <td>{e.state}</td>
              <td>{e.attempt}</td>
              <td>{e.severity}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
