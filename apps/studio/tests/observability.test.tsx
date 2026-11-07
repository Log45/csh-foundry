// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { Observability } from "@/features/observability";
import type { Client } from "@/lib/api";
vi.mock("@xyflow/react", () => ({
  ReactFlow: () => null,
  Background: () => null,
  Controls: () => null,
}));
test("initial Project load retains its authorized resources across selection effects", async () => {
  const api = vi.fn(async (path: string) => {
    if (path.startsWith("/api/v1/projects?"))
      return [{ id: "project", name: "Operations" }];
    if (path.includes("/projects/project/resources"))
      return [
        { id: "resource", name: "Source data", resource_type: "DATASET" },
      ];
    if (path.includes("/health"))
      return {
        resource_id: "resource",
        executions: [],
        consecutive_failures: 0,
        history_truncated: false,
        active_ids: [],
      };
    if (path.includes("/versions")) return [];
    if (path.includes("/freshness"))
      return {
        resource_id: "resource",
        state: "DISABLED",
        reason: "No policy",
        last_committed_at: null,
      };
    await new Promise((resolve) => setTimeout(resolve, 50));
    return {
      execution_counts: {},
      recent_failures: [],
      sampled_resources: 0,
      truncated: false,
    };
  }) as unknown as Client;
  render(<Observability api={api} />);
  await waitFor(() =>
    expect(
      screen.getByRole("option", { name: "Source data · DATASET" }),
    ).not.toBeNull(),
  );
  expect(screen.getByLabelText("Lineage resource")).not.toBeNull();
  await waitFor(() =>
    expect(
      screen.getByRole("heading", { name: "Dataset freshness: DISABLED" }),
    ).not.toBeNull(),
  );
});
