"use client";
import { useEffect, useState } from "react";
import type { components } from "@/lib/api-schema";
import { ontologyPath, segment, type Client } from "@/lib/api";
import { Notice, Result, useTask } from "@/components/ui";
type Run = components["schemas"]["RunView"] | components["schemas"]["JobView"];
export function JobDashboard({
  api,
  id,
  kind,
  can,
}: {
  api: Client;
  id: string;
  kind: "ingestion" | "semantic";
  can: (p: string) => boolean;
}) {
  const [runs, setRuns] = useState<Run[]>([]),
    [offset, setOffset] = useState(0),
    [result, setResult] = useState<unknown>();
  const task = useTask(),
    base = ontologyPath(id),
    path = kind === "ingestion" ? "/ingestion/runs" : "/semantic/jobs";
  async function load(page = offset) {
    setRuns(await api<Run[]>(`${base}${path}?limit=50&offset=${page}`));
  }
  useEffect(() => {
    void task.run(() => load());
  }, [id, kind, offset]);
  return (
    <section aria-label={`${kind} job dashboard`}>
      <div className="metrics">
        {["PENDING", "RUNNING", "COMPLETED", "FAILED"].map((status) => (
          <div key={status}>
            <strong>{runs.filter((r) => r.status === status).length}</strong>
            <span>{status.toLowerCase()} on this page</span>
          </div>
        ))}
      </div>
      <div className="row">
        <button
          disabled={task.busy}
          onClick={() => void task.run(() => load())}
        >
          Refresh dashboard
        </button>
        <button
          disabled={task.busy || !offset}
          onClick={() => setOffset(Math.max(0, offset - 50))}
        >
          Previous jobs
        </button>
        <button
          disabled={task.busy || runs.length < 50 || offset >= 9950}
          onClick={() => setOffset(offset + 50)}
        >
          More jobs
        </button>
      </div>
      <div className="table-wrap">
        <table>
          <caption>Current authorized {kind} jobs</caption>
          <thead>
            <tr>
              <th>Job</th>
              <th>Status</th>
              <th>Progress / operation</th>
              <th>Outputs</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => (
              <tr key={run.id}>
                <td>
                  <button onClick={() => setResult(run)}>
                    {run.id.slice(0, 8)}
                  </button>
                </td>
                <td>
                  <span className="badge">{run.status}</span>
                  {run.last_error && <p>{run.last_error}</p>}
                </td>
                <td>
                  {"processed" in run
                    ? `${run.processed} processed · ${run.created} created · ${run.rejected} rejected`
                    : run.request.operation}
                </td>
                <td>
                  {"outputs" in run &&
                    run.outputs.map((output) => (
                      <button
                        key={output}
                        disabled={!can("semantic:read") || task.busy}
                        onClick={() =>
                          void task.run(async () =>
                            setResult(
                              await api(
                                `${base}/semantic/artifacts/${segment(output)}`,
                              ),
                            ),
                          )
                        }
                      >
                        Inspect {output.slice(0, 8)}
                      </button>
                    ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!runs.length && (
        <p>No jobs on this page. Submit a run with the forms below.</p>
      )}
      {task.busy && <p role="status">Loading job dashboard…</p>}
      {task.error && <Notice>{task.error}</Notice>}
      <Result value={result} />
    </section>
  );
}
