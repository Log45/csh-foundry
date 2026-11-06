"use client";

import {
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  ReactFlowProvider,
  addEdge,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Connection,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type DragEvent,
} from "react";
import type { Client } from "@/lib/api";
import type { components } from "@/lib/api-schema";
import { Field, Notice, useTask } from "@/components/ui";

type Graph = components["schemas"]["Graph-Input"];
type GraphNode = Graph["nodes"][number];
type Compilation = components["schemas"]["Compilation"];
type Definition = components["schemas"]["DefinitionView"];
type Draft = components["schemas"]["DraftView"];
type Resource = components["schemas"]["ResourceView"];
type DatasetVersion = components["schemas"]["DatasetVersionView"];
type FunctionDefinition = components["schemas"]["FunctionDefinitionView"];

const operations = [
  "select",
  "rename",
  "drop",
  "filter",
  "sort",
  "cast",
  "derive",
  "fill_null",
  "deduplicate",
  "aggregate",
  "join",
  "union",
] as const;
type Operation = (typeof operations)[number];

type CanvasData = {
  title: string;
  kind: GraphNode["kind"];
  operation?: string;
};
type CanvasNode = Node<CanvasData>;

function PipelineNode({ data, selected }: NodeProps<CanvasNode>) {
  const multi = data.operation === "join" || data.operation === "union";
  return (
    <div
      className={`pipeline-node pipeline-node-${data.kind}${selected ? " selected" : ""}`}
      aria-label={`${data.title} pipeline node`}
    >
      {data.kind !== "dataset_source" && data.kind !== "function_reference" && (
        <Handle type="target" position={Position.Left} id="input" />
      )}
      {multi && (
        <Handle
          type="target"
          position={Position.Top}
          id="right"
          aria-label="Right dataset input"
        />
      )}
      <strong>{data.title}</strong>
      <small>{data.kind.replaceAll("_", " ")}</small>
      {data.kind !== "dataset_output" && data.kind !== "function_reference" && (
        <Handle type="source" position={Position.Right} id="output" />
      )}
    </div>
  );
}

const nodeTypes = { pipeline: PipelineNode };

function defaultStep(op: Operation): Record<string, unknown> {
  if (["select", "drop", "sort"].includes(op))
    return { op, columns: ["column"] };
  if (op === "rename") return { op, mapping: { column: "renamed" } };
  if (op === "cast") return { op, mapping: { column: "String" } };
  if (op === "filter")
    return {
      op,
      expression: {
        op: "eq",
        args: [
          { op: "column", column: "column" },
          { op: "literal", value: "value" },
        ],
      },
    };
  if (op === "derive")
    return {
      op,
      name: "derived",
      expression: {
        op: "add",
        args: [
          { op: "column", column: "column" },
          { op: "literal", value: 1 },
        ],
      },
    };
  if (op === "fill_null") return { op, name: "column", value: "value" };
  if (op === "deduplicate") return { op, columns: [] };
  if (op === "aggregate")
    return {
      op,
      columns: [],
      aggregates: [{ column: "column", function: "count", alias: "count" }],
    };
  if (op === "join")
    return { op, input: "right", columns: ["id"], how: "inner" };
  return { op, input: "right" };
}

const emptyGraph: Graph = { format_version: 2, nodes: [], edges: [] };

function label(node: GraphNode) {
  if (node.kind === "transform") return node.config.op;
  if (node.kind === "dataset_source")
    return node.config.name || "Dataset source";
  if (node.kind === "dataset_output") return "Dataset output";
  return "Function reference (unsupported)";
}

function toCanvas(graph: Graph): { nodes: CanvasNode[]; edges: Edge[] } {
  return {
    nodes: graph.nodes.map((node) => ({
      id: node.id,
      type: "pipeline",
      position: { x: node.position?.x ?? 0, y: node.position?.y ?? 0 },
      data: {
        title: label(node),
        kind: node.kind,
        operation: node.kind === "transform" ? node.config.op : undefined,
      },
    })),
    edges: graph.edges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      sourceHandle: edge.source_port,
      target: edge.target,
      targetHandle: edge.target_port,
    })),
  };
}

function parseScalar(value: string): string | number | boolean | null {
  if (value === "null") return null;
  if (value === "true") return true;
  if (value === "false") return false;
  const numeric = Number(value);
  return value.trim() !== "" && Number.isFinite(numeric) ? numeric : value;
}

function csv(value: string) {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function mapping(value: string) {
  return Object.fromEntries(
    value
      .split("\n")
      .map((line) => line.split(":", 2).map((part) => part.trim()))
      .filter((parts) => parts.length === 2 && parts.every(Boolean)),
  );
}

function Canvas({
  graph,
  setGraph,
  selected,
  setSelected,
}: {
  graph: Graph;
  setGraph: (graph: Graph) => void;
  selected: string;
  setSelected: (id: string) => void;
}) {
  const initial = useMemo(() => toCanvas(graph), []); // graph changes use the effect below.
  const [nodes, setNodes, onNodesChange] = useNodesState<CanvasNode>(
    initial.nodes,
  );
  const [edges, setEdges, onEdgesChange] = useEdgesState(initial.edges);
  const flow = useReactFlow<CanvasNode>();

  useEffect(() => {
    const value = toCanvas(graph);
    setNodes(value.nodes);
    setEdges(value.edges);
  }, [graph, setEdges, setNodes]);

  const syncEdges = useCallback(
    (next: Edge[]) => {
      setEdges(next);
      setGraph({
        ...graph,
        edges: next.map((edge) => ({
          id: edge.id,
          source: edge.source,
          source_port: "output",
          target: edge.target,
          target_port: edge.targetHandle === "right" ? "right" : "input",
        })),
      });
    },
    [graph, setEdges, setGraph],
  );

  const connect = useCallback(
    (connection: Connection) => {
      if (!connection.source || !connection.target) return;
      syncEdges(
        addEdge(
          {
            ...connection,
            id: `edge-${crypto.randomUUID()}`,
            sourceHandle: "output",
            targetHandle: connection.targetHandle ?? "input",
          },
          edges,
        ),
      );
    },
    [edges, syncEdges],
  );

  const drop = (event: DragEvent) => {
    event.preventDefault();
    const kind = event.dataTransfer.getData("application/foundry-node");
    if (!kind) return;
    const position = flow.screenToFlowPosition({
      x: event.clientX,
      y: event.clientY,
    });
    addNode(kind, position);
  };

  function addNode(
    kind: string,
    position = { x: 80 + graph.nodes.length * 30, y: 80 },
  ) {
    const id = `node-${crypto.randomUUID()}`;
    let node: GraphNode;
    if (kind === "dataset_source") {
      node = {
        id,
        kind,
        position,
        config: {
          name: `source${graph.nodes.length + 1}`,
          dataset_id: null,
          version_id: null,
          columns: {},
        },
      };
    } else if (kind === "dataset_output") {
      node = { id, kind, position, config: { dataset_id: null, columns: {} } };
    } else if (kind === "function_reference") {
      node = {
        id,
        kind,
        position,
        config: { function_id: null, definition_id: null },
      };
    } else {
      node = {
        id,
        kind: "transform",
        position,
        config: defaultStep(kind as Operation),
      } as GraphNode;
    }
    setGraph({ ...graph, nodes: [...graph.nodes, node] });
    setSelected(id);
  }

  return (
    <div className="pipeline-canvas-shell">
      <div className="pipeline-palette" aria-label="Pipeline node palette">
        <h4>Sources and outputs</h4>
        {[
          ["dataset_source", "Dataset source"],
          ["dataset_output", "Dataset output"],
          ["function_reference", "Function reference"],
        ].map(([kind, title]) => (
          <button
            key={kind}
            type="button"
            draggable
            onDragStart={(event) =>
              event.dataTransfer.setData("application/foundry-node", kind)
            }
            onClick={() => addNode(kind)}
          >
            {title}
          </button>
        ))}
        <h4>Transformations</h4>
        {operations.map((op) => (
          <button
            key={op}
            type="button"
            draggable
            onDragStart={(event) =>
              event.dataTransfer.setData("application/foundry-node", op)
            }
            onClick={() => addNode(op)}
          >
            {op.replaceAll("_", " ")}
          </button>
        ))}
      </div>
      <div
        className="pipeline-canvas"
        onDrop={drop}
        onDragOver={(event) => event.preventDefault()}
        aria-label="Visual pipeline canvas"
      >
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={connect}
          onNodeClick={(_, node) => setSelected(node.id)}
          onNodeDragStop={(_, moved) =>
            setGraph({
              ...graph,
              nodes: graph.nodes.map((node) =>
                node.id === moved.id
                  ? { ...node, position: moved.position }
                  : node,
              ),
            })
          }
          onNodesDelete={(removed) => {
            const ids = new Set(removed.map((node) => node.id));
            setGraph({
              ...graph,
              nodes: graph.nodes.filter((node) => !ids.has(node.id)),
              edges: graph.edges.filter(
                (edge) => !ids.has(edge.source) && !ids.has(edge.target),
              ),
            });
          }}
          onEdgesDelete={(removed) =>
            syncEdges(edges.filter((edge) => !removed.includes(edge)))
          }
          fitView
          deleteKeyCode={["Backspace", "Delete"]}
          nodesFocusable
          edgesFocusable
          aria-label="Pipeline graph editor"
        >
          <Background />
          <MiniMap pannable zoomable />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
    </div>
  );
}

function Inspector({
  graph,
  selected,
  datasets,
  functions,
  api,
  mutate,
}: {
  graph: Graph;
  selected: string;
  datasets: Resource[];
  functions: Resource[];
  api: Client;
  mutate: (update: (current: Graph) => Graph) => void;
}) {
  const node = graph.nodes.find((candidate) => candidate.id === selected);
  const [versions, setVersions] = useState<DatasetVersion[]>([]);
  const [functionDefinitions, setFunctionDefinitions] = useState<
    FunctionDefinition[]
  >([]);
  if (!node) return <p>Select a node to configure it.</p>;
  const active: GraphNode = node;
  const update = (config: Record<string, unknown>) =>
    mutate((current) => ({
      ...current,
      nodes: current.nodes.map((candidate) =>
        candidate.id === active.id
          ? ({ ...candidate, config } as GraphNode)
          : candidate,
      ),
    }));
  const remove = () =>
    mutate((current) => ({
      ...current,
      nodes: current.nodes.filter((candidate) => candidate.id !== active.id),
      edges: current.edges.filter(
        (edge) => edge.source !== active.id && edge.target !== active.id,
      ),
    }));

  async function chooseDataset(datasetId: string) {
    if (active.kind === "dataset_output") {
      update({
        ...active.config,
        dataset_id: datasetId || null,
        project_id: null,
        name: null,
      });
      return;
    }
    if (active.kind !== "dataset_source") return;
    update({
      ...active.config,
      dataset_id: datasetId || null,
      version_id: null,
      columns: {},
    });
    setVersions(
      datasetId
        ? await api<DatasetVersion[]>(
            `/api/v1/datasets/${datasetId}/versions?limit=50&offset=0`,
          )
        : [],
    );
  }

  async function chooseVersion(versionId: string) {
    if (active.kind !== "dataset_source") return;
    const columns = versionId
      ? await api<Array<{ name: string; logical_type: string }>>(
          `/api/v1/datasets/${active.config.dataset_id}/versions/${versionId}/schema`,
        )
      : [];
    update({
      ...active.config,
      version_id: versionId || null,
      columns: Object.fromEntries(
        columns.map((column) => [column.name, column.logical_type]),
      ),
    });
  }

  async function chooseFunction(functionId: string) {
    if (active.kind !== "function_reference") return;
    update({
      ...active.config,
      function_id: functionId || null,
      definition_id: null,
    });
    setFunctionDefinitions(
      functionId
        ? await api<FunctionDefinition[]>(
            `/api/v1/functions/${functionId}/definitions?limit=50&offset=0`,
          )
        : [],
    );
  }

  return (
    <section
      className="pipeline-inspector"
      aria-label="Node configuration inspector"
    >
      <h4>{label(active)}</h4>
      {active.kind === "dataset_source" && (
        <>
          <Field label="Source logical name">
            <input
              value={active.config.name}
              onChange={(event) =>
                update({ ...active.config, name: event.target.value })
              }
            />
          </Field>
          <Field label="Source dataset">
            <select
              value={active.config.dataset_id ?? ""}
              onChange={(event) => void chooseDataset(event.target.value)}
            >
              <option value="">Select an authorized dataset</option>
              {datasets.map((dataset) => (
                <option key={dataset.id} value={dataset.id}>
                  {dataset.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Immutable source version">
            <select
              value={active.config.version_id ?? ""}
              onChange={(event) => void chooseVersion(event.target.value)}
            >
              <option value="">Select a committed version</option>
              {versions.map((version) => (
                <option key={version.id} value={version.id}>
                  Version {version.sequence} · {version.id}
                </option>
              ))}
            </select>
          </Field>
          <p>
            {Object.entries(active.config.columns ?? {})
              .map(([name, type]) => `${name}: ${type}`)
              .join(" · ")}
          </p>
          {active.config.dataset_id && active.config.version_id && (
            <button
              type="button"
              onClick={() =>
                void api(
                  `/api/v1/datasets/${active.config.dataset_id}/versions/${active.config.version_id}/preview?limit=20`,
                )
              }
            >
              Load bounded preview
            </button>
          )}
        </>
      )}
      {active.kind === "dataset_output" && (
        <>
          <Field label="Output format">
            <select
              value={active.config.format ?? "parquet"}
              onChange={(event) =>
                update({ ...active.config, format: event.target.value })
              }
            >
              <option value="parquet">Parquet</option>
              <option value="csv">CSV</option>
              <option value="ndjson">NDJSON</option>
            </select>
          </Field>
          <Field label="New output Project ID">
            <input
              value={active.config.project_id ?? ""}
              onChange={(event) =>
                update({
                  ...active.config,
                  dataset_id: null,
                  project_id: event.target.value || null,
                })
              }
            />
          </Field>
          <Field label="New output dataset name">
            <input
              value={active.config.name ?? ""}
              onChange={(event) =>
                update({
                  ...active.config,
                  dataset_id: null,
                  name: event.target.value || null,
                })
              }
            />
          </Field>
          <Field label="Output dataset">
            <select
              value={active.config.dataset_id ?? ""}
              onChange={(event) => void chooseDataset(event.target.value)}
            >
              <option value="">Select an authorized dataset</option>
              {datasets.map((dataset) => (
                <option key={dataset.id} value={dataset.id}>
                  {dataset.name}
                </option>
              ))}
            </select>
          </Field>
        </>
      )}
      {active.kind === "function_reference" && (
        <>
          <Notice>
            Function definitions are scalar and cannot execute in dataset
            pipelines. This node always blocks publication.
          </Notice>
          <Field label="Governed Function">
            <select
              value={active.config.function_id ?? ""}
              onChange={(event) => void chooseFunction(event.target.value)}
            >
              <option value="">Select an authorized Function</option>
              {functions.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Immutable Function version">
            <select
              value={active.config.definition_id ?? ""}
              onChange={(event) =>
                update({
                  ...active.config,
                  definition_id: event.target.value || null,
                })
              }
            >
              <option value="">Select a published version</option>
              {functionDefinitions.map((definition) => (
                <option key={definition.id} value={definition.id}>
                  Version {definition.sequence} · {definition.id}
                </option>
              ))}
            </select>
          </Field>
          {functionDefinitions
            .filter(
              (definition) => definition.id === active.config.definition_id,
            )
            .map((definition) => (
              <p key={definition.id}>
                Inputs:{" "}
                {Object.entries(definition.specification.input_schema)
                  .map(([name, type]) => `${name}: ${type.type}`)
                  .join(" · ")}
                <br />
                Outputs:{" "}
                {Object.entries(definition.specification.output_schema)
                  .map(([name, type]) => `${name}: ${type.type}`)
                  .join(" · ")}
              </p>
            ))}
        </>
      )}
      {active.kind === "transform" && (
        <StepForm
          config={active.config as Record<string, unknown>}
          update={update}
        />
      )}
      <button type="button" onClick={remove}>
        Delete selected node
      </button>
    </section>
  );
}

function StepForm({
  config,
  update,
}: {
  config: Record<string, unknown>;
  update: (value: Record<string, unknown>) => void;
}) {
  const op = config.op as Operation;
  const columns = (config.columns as string[] | undefined) ?? [];
  if (["select", "drop", "sort", "deduplicate"].includes(op))
    return (
      <>
        <Field label="Columns (comma separated)">
          <input
            value={columns.join(", ")}
            onChange={(event) =>
              update({ ...config, columns: csv(event.target.value) })
            }
          />
        </Field>
        {op === "sort" && (
          <label>
            <input
              type="checkbox"
              checked={Boolean(config.descending)}
              onChange={(event) =>
                update({ ...config, descending: event.target.checked })
              }
            />{" "}
            Descending
          </label>
        )}
      </>
    );
  if (op === "rename" || op === "cast")
    return (
      <Field
        label={
          op === "rename"
            ? "Renames (old:new, one per line)"
            : "Casts (column:type, one per line)"
        }
      >
        <textarea
          rows={5}
          value={Object.entries(
            (config.mapping as Record<string, string>) ?? {},
          )
            .map(([a, b]) => `${a}:${b}`)
            .join("\n")}
          onChange={(event) =>
            update({ ...config, mapping: mapping(event.target.value) })
          }
        />
      </Field>
    );
  if (op === "fill_null")
    return (
      <>
        <Field label="Column">
          <input
            value={String(config.name ?? "")}
            onChange={(event) =>
              update({ ...config, name: event.target.value })
            }
          />
        </Field>
        <Field label="Replacement value">
          <input
            value={String(config.value ?? "")}
            onChange={(event) =>
              update({ ...config, value: parseScalar(event.target.value) })
            }
          />
        </Field>
      </>
    );
  if (op === "join" || op === "union")
    return (
      <>
        <Field label="Right source logical name">
          <input
            value={String(config.input ?? "")}
            onChange={(event) =>
              update({ ...config, input: event.target.value })
            }
          />
        </Field>
        {op === "join" && (
          <>
            <Field label="Join keys (comma separated)">
              <input
                value={columns.join(", ")}
                onChange={(event) =>
                  update({ ...config, columns: csv(event.target.value) })
                }
              />
            </Field>
            <Field label="Join type">
              <select
                value={String(config.how ?? "inner")}
                onChange={(event) =>
                  update({ ...config, how: event.target.value })
                }
              >
                {["inner", "left", "full", "semi", "anti"].map((how) => (
                  <option key={how}>{how}</option>
                ))}
              </select>
            </Field>
          </>
        )}
      </>
    );
  if (op === "aggregate") {
    const aggregates =
      (config.aggregates as Array<Record<string, string>>) ?? [];
    return (
      <>
        <Field label="Group columns (comma separated)">
          <input
            value={columns.join(", ")}
            onChange={(event) =>
              update({ ...config, columns: csv(event.target.value) })
            }
          />
        </Field>
        <Field label="Aggregates (column:function:alias, one per line)">
          <textarea
            rows={5}
            value={aggregates
              .map((item) => `${item.column}:${item.function}:${item.alias}`)
              .join("\n")}
            onChange={(event) =>
              update({
                ...config,
                aggregates: event.target.value
                  .split("\n")
                  .map((line) => line.split(":").map((part) => part.trim()))
                  .filter((parts) => parts.length === 3)
                  .map(([column, fn, alias]) => ({
                    column,
                    function: fn,
                    alias,
                  })),
              })
            }
          />
        </Field>
      </>
    );
  }
  const expression =
    (config.expression as {
      op?: string;
      args?: Array<Record<string, unknown>>;
    }) ?? {};
  const left = expression.args?.[0] ?? { op: "column", column: "column" };
  const right = expression.args?.[1] ?? { op: "literal", value: "value" };
  return (
    <>
      {op === "derive" && (
        <Field label="Output column">
          <input
            value={String(config.name ?? "")}
            onChange={(event) =>
              update({ ...config, name: event.target.value })
            }
          />
        </Field>
      )}
      <Field label="Input column">
        <input
          value={String(left.column ?? "")}
          onChange={(event) =>
            update({
              ...config,
              expression: {
                ...expression,
                args: [{ op: "column", column: event.target.value }, right],
              },
            })
          }
        />
      </Field>
      <Field label={op === "filter" ? "Comparison" : "Operation"}>
        <select
          value={expression.op ?? (op === "filter" ? "eq" : "add")}
          onChange={(event) =>
            update({
              ...config,
              expression: {
                ...expression,
                op: event.target.value,
                args: [left, right],
              },
            })
          }
        >
          {(op === "filter"
            ? ["eq", "ne", "lt", "le", "gt", "ge"]
            : ["add", "subtract", "multiply", "divide"]
          ).map((value) => (
            <option key={value}>{value}</option>
          ))}
        </select>
      </Field>
      <Field label="Literal value">
        <input
          value={String(right.value ?? "")}
          onChange={(event) =>
            update({
              ...config,
              expression: {
                ...expression,
                args: [
                  left,
                  { op: "literal", value: parseScalar(event.target.value) },
                ],
              },
            })
          }
        />
      </Field>
    </>
  );
}

export function PipelineBuilder({
  api,
  project,
  pipeline,
  writable,
  onPublished,
}: {
  api: Client;
  project: string;
  pipeline: string;
  writable: boolean;
  onPublished: (definition: Definition, compilation: Compilation) => void;
}) {
  const task = useTask();
  const path = `/api/v1/pipelines/${pipeline}`;
  const [graph, setGraph] = useState<Graph>(emptyGraph);
  const [revision, setRevision] = useState(0);
  const [selected, setSelected] = useState("");
  const [datasets, setDatasets] = useState<Resource[]>([]);
  const [functions, setFunctions] = useState<Resource[]>([]);
  const [compilation, setCompilation] = useState<Compilation | null>(null);
  const [saved, setSaved] = useState(true);
  const [source, setSource] = useState("");
  const [target, setTarget] = useState("");
  const [targetPort, setTargetPort] = useState("input");

  useEffect(() => {
    void task.run(async () => {
      const [draft, owned, shared] = await Promise.all([
        api<Draft | null>(`${path}/graph/draft`),
        api<Resource[]>(
          `/api/v1/projects/${project}/resources?limit=100&offset=0`,
        ),
        api<Resource[]>(
          `/api/v1/projects/${project}/resources?limit=100&offset=0&shared=true`,
        ),
      ]);
      const resources = [
        ...new Map(
          [...owned, ...shared].map((item) => [item.id, item]),
        ).values(),
      ];
      setDatasets(
        resources.filter(
          (resource) =>
            resource.resource_type === "DATASET" && resource.state === "ACTIVE",
        ),
      );
      setFunctions(
        resources.filter(
          (resource) =>
            resource.resource_type === "FUNCTION" &&
            resource.state === "ACTIVE",
        ),
      );
      if (draft) {
        setGraph(draft.graph);
        setRevision(draft.revision);
      }
    });
  }, []);

  function change(next: Graph) {
    setGraph(next);
    setCompilation(null);
    setSaved(false);
  }

  function mutate(update: (current: Graph) => Graph) {
    setGraph((current) => update(current));
    setCompilation(null);
    setSaved(false);
  }

  async function compile() {
    const value = await api<Compilation>(
      `${path}/graph/compile`,
      "POST",
      graph,
    );
    setCompilation(value);
    return value;
  }

  return (
    <details open className="pipeline-builder">
      <summary>Visual pipeline builder</summary>
      {task.error && <Notice>{task.error}</Notice>}
      <p role="status">
        {saved
          ? revision
            ? `Saved draft revision ${revision}`
            : "No saved draft"
          : "Unsaved changes"}
      </p>
      {graph.format_version === 1 && (
        <button
          type="button"
          disabled={!writable}
          onClick={() => change({ ...graph, format_version: 2 })}
        >
          Upgrade draft to DAG v2
        </button>
      )}
      <p>
        Graph format {graph.format_version}. Outputs publish together after
        every output is prepared and verified.
      </p>
      <ReactFlowProvider>
        <Canvas
          graph={graph}
          setGraph={change}
          selected={selected}
          setSelected={setSelected}
        />
      </ReactFlowProvider>
      <div className="pipeline-builder-lower">
        <Inspector
          graph={graph}
          selected={selected}
          datasets={datasets}
          functions={functions}
          api={api}
          mutate={mutate}
        />
        <section aria-label="Accessible connection editor">
          <h4>Connections</h4>
          <Field label="Connection source">
            <select
              value={source}
              onChange={(event) => setSource(event.target.value)}
            >
              <option value="">Select source node</option>
              {graph.nodes
                .filter(
                  (node) =>
                    !["dataset_output", "function_reference"].includes(
                      node.kind,
                    ),
                )
                .map((node) => (
                  <option key={node.id} value={node.id}>
                    {label(node)}
                  </option>
                ))}
            </select>
          </Field>
          <Field label="Connection target">
            <select
              value={target}
              onChange={(event) => setTarget(event.target.value)}
            >
              <option value="">Select target node</option>
              {graph.nodes
                .filter(
                  (node) =>
                    !["dataset_source", "function_reference"].includes(
                      node.kind,
                    ),
                )
                .map((node) => (
                  <option key={node.id} value={node.id}>
                    {label(node)}
                  </option>
                ))}
            </select>
          </Field>
          <Field label="Target port">
            <select
              value={targetPort}
              onChange={(event) => setTargetPort(event.target.value)}
            >
              <option value="input">Main input</option>
              <option value="right">Right input (join/union)</option>
            </select>
          </Field>
          <button
            type="button"
            disabled={!source || !target}
            onClick={() =>
              change({
                ...graph,
                edges: [
                  ...graph.edges,
                  {
                    id: `edge-${crypto.randomUUID()}`,
                    source,
                    source_port: "output",
                    target,
                    target_port: targetPort as "input" | "right",
                  },
                ],
              })
            }
          >
            Add connection
          </button>
          <ul>
            {graph.edges.map((edge) => (
              <li key={edge.id}>
                {edge.source} → {edge.target} ({edge.target_port}){" "}
                <button
                  type="button"
                  aria-label={`Remove connection ${edge.id}`}
                  onClick={() =>
                    change({
                      ...graph,
                      edges: graph.edges.filter((item) => item.id !== edge.id),
                    })
                  }
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        </section>
      </div>
      <div className="pipeline-builder-actions">
        <button
          type="button"
          disabled={task.busy || !writable}
          onClick={() =>
            void task.run(async () => {
              const draft = await api<Draft>(`${path}/graph/draft`, "PUT", {
                expected_revision: revision,
                graph,
              });
              setRevision(draft.revision);
              setSaved(true);
            })
          }
        >
          Save draft
        </button>
        <button
          type="button"
          disabled={task.busy}
          onClick={() =>
            void task.run(async () => {
              const value = await compile();
              if (value.valid) setSaved(saved);
            })
          }
        >
          Validate graph
        </button>
        <button
          type="button"
          disabled={task.busy || !writable || compilation?.valid !== true}
          onClick={() =>
            void task.run(async () => {
              const value = await compile();
              if (!value.valid) return;
              const definition = await api<Definition>(
                `${path}/graph/publish`,
                "POST",
                graph,
              );
              onPublished(definition, value);
              setSaved(true);
            })
          }
        >
          Publish immutable visual definition
        </button>
      </div>
      {compilation && (
        <section
          className={compilation.valid ? "pipeline-valid" : "pipeline-invalid"}
          aria-label="Graph validation diagnostics"
        >
          <h4>
            {compilation.valid ? "Graph is valid" : "Graph needs attention"}
          </h4>
          <ul>
            {(compilation.diagnostics ?? []).map((diagnostic, index) => (
              <li key={`${diagnostic.code}-${index}`}>
                <strong>{diagnostic.code}</strong>: {diagnostic.message}
                {diagnostic.node_id ? ` · node ${diagnostic.node_id}` : ""}
                {diagnostic.edge_id ? ` · edge ${diagnostic.edge_id}` : ""}
              </li>
            ))}
          </ul>
          {compilation.semantic_digest && (
            <p>
              Executable identity: <code>{compilation.semantic_digest}</code>
            </p>
          )}
          {Object.entries(compilation.schemas ?? {}).map(([node, schema]) => (
            <p key={node}>
              <strong>{node}</strong>:{" "}
              {Object.entries(schema)
                .map(([name, type]) => `${name}: ${type}`)
                .join(" · ")}
            </p>
          ))}
        </section>
      )}
    </details>
  );
}
