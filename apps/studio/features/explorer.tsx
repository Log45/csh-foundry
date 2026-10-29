"use client";
import { useState } from "react";
import {
  ontologyPath,
  type Client,
  type Schema,
  type Page,
  type Query,
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
export function Explorer({
  api,
  id,
  schema,
}: {
  api: Client;
  id: string;
  schema: Schema;
}) {
  const [type, setType] = useState(schema.object_types?.[0]?.id ?? ""),
    [property, setProperty] = useState(""),
    [operator, setOperator] = useState("eq"),
    [operand, setOperand] = useState(""),
    [projection, setProjection] = useState<string[]>([]),
    [sort, setSort] = useState(""),
    [direction, setDirection] = useState("asc"),
    [link, setLink] = useState(""),
    [inverse, setInverse] = useState(false),
    [page, setPage] = useState<Page>(),
    [detail, setDetail] = useState<unknown>(),
    [advanced, setAdvanced] = useState(""),
    [history, setHistory] = useState<string[]>([]),
    [saved, setSaved] = useState<{ name: string; query: string }[]>([]),
    [name, setName] = useState("");
  const task = useTask(),
    typed = schema.object_types?.find((t) => t.id === type),
    base = ontologyPath(id);
  function query(): Query {
    if (advanced) return JSON.parse(advanced);
    const field = typed?.properties.find((p) => p.id === property);
    const value = operator.startsWith("is_")
      ? null
      : field?.data_type === "integer" || field?.data_type === "float"
        ? JSON.parse(operand)
        : field?.data_type === "boolean"
          ? JSON.parse(operand)
          : operand;
    return {
      object_type: type,
      limit: 25,
      ...(property
        ? {
            filter: {
              property,
              operator: operator as "eq",
              ...(!operator.startsWith("is_") ? { value } : {}),
            },
          }
        : {}),
      ...(projection.length ? { select: projection } : {}),
      ...(sort
        ? { order_by: [{ property: sort, direction: direction as "asc" }] }
        : {}),
      ...(link
        ? { traverse: [{ link, direction: inverse ? "inverse" : "forward" }] }
        : {}),
    };
  }
  async function search(cursor?: string) {
    const q = query();
    const data = await api<Page>(base + "/object-sets/query", "POST", {
      ...q,
      ...(cursor ? { cursor } : {}),
    });
    setPage(data);
    setDetail(undefined);
    if (!cursor) setHistory([]);
  }
  return (
    <Task title="Object explorer & Object Sets">
      <p>
        Queries, projections and traversals use current backend row and property
        permissions. Saved Object Sets last for this workspace session.
      </p>
      <div className="grid">
        <Field label="Object type">
          <select
            value={type}
            onChange={(e) => {
              setType(e.target.value);
              setProperty("");
              setProjection([]);
              setSort("");
              setLink("");
              setPage(undefined);
            }}
          >
            {schema.object_types?.map((t) => (
              <option key={t.id}>{t.id}</option>
            ))}
          </select>
        </Field>
        <Field label="Filter property">
          <select
            value={property}
            onChange={(e) => setProperty(e.target.value)}
          >
            <option value="">All authorized rows</option>
            {typed?.properties.map((p) => (
              <option key={p.id}>{p.id}</option>
            ))}
          </select>
        </Field>
        <Field label="Operator">
          <select
            value={operator}
            onChange={(e) => setOperator(e.target.value)}
          >
            {[
              "eq",
              "ne",
              "gt",
              "gte",
              "lt",
              "lte",
              "contains",
              "starts_with",
              "ends_with",
              "is_null",
              "is_not_null",
            ].map((o) => (
              <option key={o}>{o}</option>
            ))}
          </select>
        </Field>
        <Field label="Filter value">
          <input
            value={operand}
            onChange={(e) => setOperand(e.target.value)}
            disabled={operator.startsWith("is_")}
          />
        </Field>
        <Field label="Sort property">
          <select value={sort} onChange={(e) => setSort(e.target.value)}>
            <option value="">Stable identity order</option>
            {typed?.properties.map((p) => (
              <option key={p.id}>{p.id}</option>
            ))}
          </select>
        </Field>
        <Field label="Sort direction">
          <select
            value={direction}
            onChange={(e) => setDirection(e.target.value)}
          >
            <option>asc</option>
            <option>desc</option>
          </select>
        </Field>
        <Field label="Traverse relationship">
          <select value={link} onChange={(e) => setLink(e.target.value)}>
            <option value="">No traversal</option>
            {schema.link_types
              ?.filter((l) =>
                inverse ? l.target_type === type : l.source_type === type,
              )
              .map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name}
                </option>
              ))}
          </select>
        </Field>
        <label>
          <input
            type="checkbox"
            checked={inverse}
            onChange={(e) => {
              setInverse(e.target.checked);
              setLink("");
            }}
          />
          Inverse direction
        </label>
      </div>
      <details>
        <summary>Projection</summary>
        <div className="row">
          {typed?.properties.map((p) => (
            <label key={p.id}>
              <input
                type="checkbox"
                checked={projection.includes(p.id)}
                onChange={(e) =>
                  setProjection(
                    e.target.checked
                      ? [...projection, p.id]
                      : projection.filter((x) => x !== p.id),
                  )
                }
              />
              {p.name}
            </label>
          ))}
        </div>
      </details>
      <details>
        <summary>Advanced query</summary>
        <JsonEditor
          label="Query AST override (empty uses builder)"
          value={advanced}
          onChange={setAdvanced}
        />
        <p>
          Supports nested filters, up to four traversal steps, result filters
          and typed projections.
        </p>
      </details>
      <div className="row">
        <button
          className="primary"
          disabled={task.busy || !type}
          onClick={() => void task.run(() => search())}
        >
          Run query
        </button>
        <Field label="Object Set name">
          <input value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <button
          disabled={!name}
          onClick={() =>
            void task.run(async () => {
              setSaved([...saved, { name, query: json(query()) }]);
              setName("");
            })
          }
        >
          Save Object Set
        </button>
      </div>
      <div className="row">
        {saved.map((s, i) => (
          <button
            key={i}
            onClick={() => {
              setAdvanced(s.query);
              setPage(undefined);
            }}
          >
            {s.name}
          </button>
        ))}
      </div>
      {task.busy && <p role="status">Querying…</p>}
      {task.error && <Notice>{task.error}</Notice>}
      {page && (
        <>
          <p role="status">
            {page.items.length} objects · schema {page.schema_version}
          </p>
          <div className="table-wrap">
            <table>
              <caption>Authorized {page.object_type} objects</caption>
              <thead>
                <tr>
                  <th>Identity</th>
                  <th>Revision</th>
                  {[
                    ...new Set(
                      page.items.flatMap((o) => Object.keys(o.properties)),
                    ),
                  ].map((k) => (
                    <th key={k}>{k}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {page.items.map((o) => (
                  <tr key={o.object_id}>
                    <td>
                      <button onClick={() => setDetail(o)}>
                        {o.object_id}
                      </button>
                    </td>
                    <td>{o.version}</td>
                    {[
                      ...new Set(
                        page.items.flatMap((o) => Object.keys(o.properties)),
                      ),
                    ].map((k) => (
                      <td key={k}>
                        {o.properties[k] === undefined
                          ? "—"
                          : typeof o.properties[k] === "string"
                            ? o.properties[k]
                            : JSON.stringify(o.properties[k])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!page.items.length && <p>No objects match this authorized query.</p>}
          <button
            disabled={task.busy || !page.next_cursor}
            onClick={() =>
              void task.run(async () => {
                if (page.next_cursor) {
                  setHistory([...history, page.next_cursor]);
                  await search(page.next_cursor);
                }
              })
            }
          >
            Next page
          </button>
          <button
            disabled={task.busy}
            onClick={() => void task.run(() => search())}
          >
            First page
          </button>
        </>
      )}
      <Result value={detail} />
    </Task>
  );
}
export function Actions({
  api,
  id,
  schema,
  can,
}: {
  api: Client;
  id: string;
  schema: Schema;
  can: (p: string) => boolean;
}) {
  const [selected, setSelected] = useState(schema.action_types?.[0]?.id ?? ""),
    [parameters, setParameters] = useState<Record<string, string>>({}),
    [preview, setPreview] = useState<unknown>(),
    [result, setResult] = useState<unknown>(),
    [key, setKey] = useState(() => crypto.randomUUID()),
    [approved, setApproved] = useState(false);
  const task = useTask(),
    action = schema.action_types?.find((a) => a.id === selected),
    base = ontologyPath(id);
  function body() {
    const values: Record<string, unknown> = {};
    for (const p of action?.parameters ?? []) {
      const raw = parameters[p.id];
      if (raw === undefined || raw === "") {
        if (p.required) throw Error(`${p.name} is required`);
        continue;
      }
      values[p.id] =
        ["integer", "float", "boolean", "json"].includes(p.data_type) || p.array
          ? JSON.parse(raw)
          : raw;
    }
    return { parameters: values };
  }
  function invalidate() {
    setPreview(undefined);
    setApproved(false);
    setKey(crypto.randomUUID());
  }
  return (
    <Task title="Governed actions">
      <Field label="Action">
        <select
          value={selected}
          onChange={(e) => {
            setSelected(e.target.value);
            setParameters({});
            invalidate();
          }}
        >
          {schema.action_types?.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
      </Field>
      <div className="grid">
        {action?.parameters?.map((p) => (
          <Field
            key={p.id}
            label={`${p.name} (${p.data_type}${p.required ? ", required" : ""})`}
          >
            {p.enum?.length ? (
              <select
                value={parameters[p.id] ?? ""}
                onChange={(e) => {
                  setParameters({ ...parameters, [p.id]: e.target.value });
                  invalidate();
                }}
              >
                <option value="">Select value</option>
                {p.enum.map((v, i) => (
                  <option key={i} value={String(v)}>
                    {String(v)}
                  </option>
                ))}
              </select>
            ) : (
              <input
                value={parameters[p.id] ?? ""}
                onChange={(e) => {
                  setParameters({ ...parameters, [p.id]: e.target.value });
                  invalidate();
                }}
              />
            )}
          </Field>
        ))}
      </div>
      <button
        disabled={task.busy || !selected || !can("action:invoke")}
        onClick={() =>
          void task.run(async () => {
            setPreview(
              await api(
                `${base}/actions/${encodeURIComponent(selected)}/preview`,
                "POST",
                body(),
              ),
            );
            setApproved(false);
          })
        }
      >
        Preview action
      </button>
      <Result value={preview} />
      {preview !== undefined && (
        <>
          <label>
            <input
              type="checkbox"
              checked={approved}
              onChange={(e) => setApproved(e.target.checked)}
            />
            I reviewed the preview and approve execution.
          </label>
          <Field label="Idempotency key">
            <input value={key} readOnly />
          </Field>
          <button
            className="primary"
            disabled={task.busy || !approved || !can("action:invoke")}
            onClick={() =>
              void task.run(async () => {
                setResult(
                  await api(
                    `${base}/actions/${encodeURIComponent(selected)}/execute`,
                    "POST",
                    { ...body(), idempotency_key: key },
                  ),
                );
                setApproved(false);
              })
            }
          >
            Execute action
          </button>
          <p>
            Retries use the same key. Execution rechecks current permissions,
            revisions and preconditions.
          </p>
        </>
      )}
      <button
        disabled={task.busy || !can("action:history")}
        onClick={() =>
          void task.run(async () =>
            setResult(await api(base + "/actions/executions")),
          )
        }
      >
        Refresh execution history
      </button>
      {task.error && <Notice>{task.error}</Notice>}
      <Result value={result} />
      {!action && <p>No action definitions in the active schema.</p>}
    </Task>
  );
}
