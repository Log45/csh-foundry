import type { AppDocument, AppWidget, AppValue } from "./application-runtime";
import type { components } from "@foundry/sdk";
export function manufacturingApplication(
  resource: components["schemas"]["ResourceView"],
  schema: components["schemas"]["OntologyDefinition"],
): AppDocument {
  const machine = schema.object_types?.find((t) => t.id === "Machine");
  const action = schema.action_types?.find(
    (a) => a.id === "UpdateMachineStatus",
  );
  if (
    !machine ||
    !action ||
    ![
      "machineId",
      "machineName",
      "operationalStatus",
      "temperatureCelsius",
    ].every((p) => machine.properties?.some((v) => v.id === p))
  )
    throw new Error(
      "Select the manufacturing fixture schema with published UpdateMachineStatus.",
    );
  const value = (
    kind: AppValue["kind"],
    state: string,
    property: string | null = null,
  ): AppValue => ({ kind, state, property, value: null });
  const widget = (
    id: string,
    kind: AppWidget["kind"],
    config: Partial<AppWidget>,
  ): AppWidget => ({
    id,
    kind,
    label: id,
    text: "",
    parent: null,
    layout: "column",
    spacing: "normal",
    align: "stretch",
    source: null,
    state: null,
    property: null,
    columns: [],
    options: [],
    page: null,
    action: null,
    visible: null,
    ...config,
  });
  const query = {
    object_type: "Machine",
    limit: 25,
    order_by: [],
    traverse: [],
    pagination: "cursor" as const,
    offset: 0,
  };
  const sources: AppDocument["sources"] = [
    {
      id: "machines",
      dependency: "schema",
      kind: "query",
      query,
      aggregate: null,
      filters: { operationalStatus: value("state", "status_filter") },
    },
    {
      id: "summary",
      dependency: "schema",
      kind: "aggregate",
      query,
      filters: {},
      aggregate: {
        object_type: "Machine",
        metrics: [{ name: "machines", operator: "count" }],
        traverse: [],
        max_groups: 100,
      },
    },
  ];
  if (schema.link_types?.some((l) => l.id === "locatedInFactory"))
    sources.push({
      id: "factory",
      dependency: "schema",
      kind: "query",
      query: {
        ...query,
        traverse: [{ link: "locatedInFactory", direction: "forward" }],
      },
      aggregate: null,
      filters: { machineId: value("selected", "selection", "$id") },
    });
  return {
    format_version: 1,
    title: "Manufacturing Operations Dashboard",
    description: "Live authorized machines and governed status updates.",
    home: "operations",
    states: [
      { id: "status_filter", data_type: "string", initial: "" },
      { id: "selection", data_type: "selection", initial: null },
      { id: "new_status", data_type: "string", initial: "STOPPED" },
    ],
    dependencies: [
      {
        id: "schema",
        resource_id: resource.id,
        ontology_id: resource.ontology_id!,
        schema_version: resource.schema_version!,
        policy: "exact_active",
      },
    ],
    sources,
    actions: [
      {
        id: "update_status",
        dependency: "schema",
        action_id: action.id,
        parameters: {
          machineId: value("selected", "selection", "$id"),
          newStatus: value("state", "new_status"),
          expectedRevision: value("selected", "selection", "$version"),
        },
        parameter_types: Object.fromEntries(
          action.parameters?.map((p) => [p.id, p.data_type]) ?? [],
        ),
        confirm: true,
        refresh: sources.map((s) => s.id),
      },
    ],
    interactions: [],
    pages: [
      {
        id: "operations",
        title: "Operations",
        description: "Choose a machine to inspect and update.",
        parameters: [],
        widgets: [
          widget("status_control", "select", {
            label: "Operational status filter",
            state: "status_filter",
            options: ["RUNNING", "STOPPED", "MAINTENANCE", "CRITICAL"],
          }),
          widget("machine_table", "table", {
            label: "Machines",
            source: "machines",
            state: "selection",
            columns: [
              "machineId",
              "machineName",
              "operationalStatus",
              "temperatureCelsius",
            ],
          }),
          widget("machine_details", "detail", {
            label: "Selected machine",
            state: "selection",
          }),
          ...(sources.some((s) => s.id === "factory")
            ? [
                widget("factory_list", "list", {
                  label: "Factory relationship",
                  source: "factory",
                }),
              ]
            : []),
          widget("machine_count", "metric", {
            label: "Authorized machine count",
            source: "summary",
          }),
          widget("status_input", "select", {
            label: "New operational status",
            state: "new_status",
            options: ["RUNNING", "STOPPED", "MAINTENANCE", "CRITICAL"],
          }),
          widget("submit_status", "action", {
            label: "Update machine status",
            action: "update_status",
          }),
          widget("about_link", "navigation", {
            label: "About this application",
            page: "about",
          }),
        ],
      },
      {
        id: "about",
        title: "About",
        description: "Immutable configuration; live operational values.",
        parameters: [],
        widgets: [
          widget("about_text", "text", {
            text: "Application access and ontology permissions are cumulative. Actions are previewed and audited by the canonical service.",
          }),
        ],
      },
    ],
  };
}
