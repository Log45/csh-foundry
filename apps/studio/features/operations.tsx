"use client";
import { useState } from "react";
import { ontologyPath, segment, type Client, type Schema } from "@/lib/api";
import {
  Field,
  JsonEditor,
  Notice,
  Result,
  Task,
  json,
  useTask,
} from "@/components/ui";
import { JobDashboard } from "./job-dashboard";
interface Operation {
  name: string;
  method?: string;
  path: string;
  permission: string;
  body?: unknown;
  confirm?: boolean;
  requires?: string[];
}
function OperationForm({
  api,
  base,
  operation,
}: {
  api: Client;
  base: string;
  operation: Operation;
}) {
  const [text, setText] = useState(json(operation.body)),
    [key, setKey] = useState(""),
    [offset, setOffset] = useState(0),
    [result, setResult] = useState<unknown>();
  const task = useTask();
  async function run(page = offset) {
    if (operation.path.includes("{id}") && !key)
      throw Error("Enter an identifier");
    const path = base + operation.path.replace("{id}", segment(key));
    setResult(
      await api(
        path +
          (operation.method === undefined ? `?limit=50&offset=${page}` : ""),
        operation.method ?? "GET",
        operation.body === undefined ? undefined : JSON.parse(text),
      ),
    );
  }
  return (
    <details className="operation">
      <summary>{operation.name}</summary>
      {operation.path.includes("{id}") && (
        <Field label={`${operation.name} identifier`}>
          <input value={key} onChange={(e) => setKey(e.target.value)} />
        </Field>
      )}
      {operation.body !== undefined && (
        <JsonEditor
          label={`${operation.name} request`}
          value={text}
          onChange={setText}
        />
      )}
      <div className="row">
        <button
          disabled={task.busy}
          onClick={() => {
            if (
              !operation.confirm ||
              window.confirm(
                `${operation.name}? This applies through the governed backend.`,
              )
            )
              void task.run(() => run());
          }}
        >
          {task.busy ? "Working…" : operation.name}
        </button>
        {operation.method === undefined && (
          <>
            <button
              disabled={task.busy || offset === 0}
              onClick={() =>
                void task.run(async () => {
                  const next = Math.max(0, offset - 50);
                  setOffset(next);
                  await run(next);
                })
              }
            >
              Previous results
            </button>
            <button
              disabled={task.busy || offset >= 9950}
              onClick={() =>
                void task.run(async () => {
                  const next = offset + 50;
                  setOffset(next);
                  await run(next);
                })
              }
            >
              Next results
            </button>
          </>
        )}
      </div>
      {task.error && <Notice>{task.error}</Notice>}
      <Result value={result} />
    </details>
  );
}
export function Operations({
  kind,
  api,
  id,
  schema,
  can,
}: {
  kind: "ingestion" | "semantic" | "objects";
  api: Client;
  id: string;
  schema: Schema;
  can: (p: string) => boolean;
}) {
  const [selectedType, setSelectedType] = useState(
    schema.object_types?.[0]?.id ?? "",
  );
  const version = schema.version,
    first = schema.object_types?.find((t) => t.id === selectedType),
    firstId = first?.id ?? "Factory";
  const groups: Record<
    typeof kind,
    { title: string; description: string; operations: Operation[] }
  > = {
    ingestion: {
      title: "Ingestion sources & runs",
      description:
        "Sources and mappings publish as immutable versions. Bindings refer to server registrations; browser requests never supply paths, SQL or credentials. Runs execute asynchronously in a separately configured worker. Refresh to inspect progress.",
      operations: [
        { name: "List sources", path: "/sources", permission: "source:read" },
        {
          name: "Publish source",
          path: "/sources",
          method: "POST",
          permission: "source:create",
          requires: ["source:publish"],
          body: {
            id: firstId,
            name: firstId,
            binding: firstId,
            identity_namespace: firstId,
            version: 1,
          },
          confirm: true,
        },
        {
          name: "Publish mapping",
          path: "/mappings",
          method: "POST",
          permission: "mapping:create",
          requires: ["mapping:publish"],
          body: {
            id: firstId,
            version: 1,
            source_id: firstId,
            source_version: 1,
            schema_version: version,
            object_type: firstId,
            identity_column: first?.primary_key ?? "factoryId",
            properties: first?.properties.map((p) => ({
              property: p.id,
              column: p.id,
              conversion: p.data_type === "decimal" ? "decimal" : "identity",
            })),
            relationships: [],
          },
          confirm: true,
        },
        {
          name: "Submit ingestion run",
          path: "/ingestion/runs",
          method: "POST",
          permission: "ingestion:execute",
          body: {
            mappings: [{ id: firstId, version: 1 }],
            idempotency_key: "replace-with-unique-run-key",
            validation_policy: "reject_run",
            batch_size: 25,
          },
          confirm: true,
        },
        {
          name: "Refresh ingestion runs",
          path: "/ingestion/runs",
          permission: "ingestion:history",
        },
        {
          name: "Inspect ingestion run",
          path: "/ingestion/runs/{id}",
          permission: "ingestion:history",
        },
        {
          name: "Read ingestion diagnostics",
          path: "/ingestion/runs/{id}/diagnostics",
          permission: "ingestion:diagnostics",
        },
        {
          name: "Cancel ingestion run",
          path: "/ingestion/runs/{id}/cancel",
          method: "POST",
          permission: "ingestion:cancel",
          confirm: true,
        },
      ],
    },
    semantic: {
      title: "Semantic validation & reasoning",
      description:
        "Compile published metadata, export an authorized selection, then submit a durable job. A separately configured semantic worker processes it. Inspect report, derived and proof artifact IDs from job outputs; freshness and approvals remain backend governed. Derived facts do not mutate operational objects.",
      operations: [
        {
          name: "Compile ontology and shapes",
          path: "/semantic/compile",
          method: "POST",
          permission: "semantic:compile",
          body: { schema_version: version },
        },
        {
          name: "Export operational RDF",
          path: "/semantic/exports",
          method: "POST",
          permission: "semantic:export",
          body: {
            schema_version: version,
            selections: [{ object_type: firstId, limit: 200 }],
            links: [],
          },
        },
        {
          name: "Publish native semantic artifact",
          path: "/semantic/native-artifacts",
          method: "POST",
          permission: "semantic:publish",
          body: { schema_version: version, kind: "ontology", content: "" },
        },
        {
          name: "Submit semantic job",
          path: "/semantic/jobs",
          method: "POST",
          permission: "semantic:execute",
          body: {
            operation: "validation",
            primary_artifact: "",
            secondary_artifact: "",
            profile: "owl-rl-ext",
          },
        },
        {
          name: "Refresh semantic jobs",
          path: "/semantic/jobs",
          permission: "semantic:history",
        },
        {
          name: "Inspect semantic job",
          path: "/semantic/jobs/{id}",
          permission: "semantic:history",
        },
        {
          name: "Cancel semantic job",
          path: "/semantic/jobs/{id}/cancel",
          method: "POST",
          permission: "semantic:cancel",
          confirm: true,
        },
        {
          name: "Inspect artifact and provenance",
          path: "/semantic/artifacts/{id}",
          permission: "semantic:read",
        },
        {
          name: "Inspect inferred facts",
          path: "/semantic/artifacts/{id}/facts",
          permission: "semantic:read",
        },
        {
          name: "Read approval history",
          path: "/semantic/artifacts/{id}/approval",
          permission: "semantic:history",
        },
        {
          name: "Approve or reject derived facts",
          path: "/semantic/artifacts/{id}/approval",
          method: "POST",
          permission: "semantic:approve",
          body: { state: "APPROVED" },
          confirm: true,
        },
      ],
    },
    objects: {
      title: "Object details, relationships & aggregates",
      description:
        "Object writes require current revisions and canonical values. Relationship changes check both endpoints. Backend property and row policies apply to all results.",
      operations: [
        {
          name: "Aggregate Object Set",
          path: "/aggregate",
          method: "POST",
          permission: "object:aggregate",
          body: {
            object_type: firstId,
            metrics: [{ name: "count", operator: "count" }],
          },
        },
        {
          name: "Get object",
          path: `/objects/${segment(firstId)}/{id}`,
          permission: "object:read",
        },
        {
          name: "Create object",
          path: `/objects/${segment(firstId)}`,
          method: "POST",
          permission: "object:create",
          body: { object_id: "", properties: {} },
          confirm: true,
        },
        {
          name: "Update object",
          path: `/objects/${segment(firstId)}/{id}`,
          method: "PATCH",
          permission: "object:update",
          body: { expected_version: 1, properties: {} },
          confirm: true,
        },
        {
          name: "Create relationship",
          path: "/links",
          method: "POST",
          permission: "link:create",
          body: {
            link_type_id: schema.link_types?.[0]?.id ?? "",
            source_object_type_id: firstId,
            source_object_id: "",
            target_object_type_id: schema.link_types?.[0]?.target_type ?? "",
            target_object_id: "",
          },
          confirm: true,
        },
        {
          name: "Remove relationship",
          path: "/links",
          method: "DELETE",
          permission: "link:delete",
          body: {
            link_type_id: schema.link_types?.[0]?.id ?? "",
            source_object_type_id: firstId,
            source_object_id: "",
            target_object_type_id: schema.link_types?.[0]?.target_type ?? "",
            target_object_id: "",
          },
          confirm: true,
        },
        {
          name: "Inspect execution",
          path: "/actions/executions/{id}",
          permission: "action:history",
        },
        {
          name: "Inspect execution audit",
          path: "/actions/executions/{id}/audit",
          permission: "action:audit",
        },
      ],
    },
  };
  const group = groups[kind];
  return (
    <Task title={group.title}>
      <p>{group.description}</p>
      {kind !== "objects" && can(`${kind}:history`) && (
        <JobDashboard api={api} id={id} kind={kind} can={can} />
      )}
      {kind === "objects" && (
        <Field label="Detail object type">
          <select
            value={selectedType}
            onChange={(e) => setSelectedType(e.target.value)}
          >
            {schema.object_types?.map((t) => (
              <option key={t.id}>{t.id}</option>
            ))}
          </select>
        </Field>
      )}
      {group.operations
        .filter((o) => can(o.permission) && (o.requires ?? []).every(can))
        .map((o) => (
          <OperationForm
            key={`${o.name}-${selectedType}`}
            api={api}
            base={ontologyPath(id)}
            operation={o}
          />
        ))}
      {!group.operations.some((o) => can(o.permission)) && (
        <p>No operations are available for your current permissions.</p>
      )}
    </Task>
  );
}
