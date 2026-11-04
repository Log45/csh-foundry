// @vitest-environment jsdom
import React from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { Client } from "../lib/api";
import { CreateMappingPanel, MappingPanel } from "../features/mappings";
afterEach(cleanup);
it("creates mapping in current folder", async () => {
  const api = vi.fn(async () => ({}));
  const reload = vi.fn();
  render(
    <CreateMappingPanel
      api={api as Client}
      project="p"
      folder="f"
      reload={reload}
    />,
  );
  fireEvent.change(screen.getByLabelText("New mapping name"), {
    target: { value: "Machines" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Create mapping" }));
  await vi.waitFor(() => expect(reload).toHaveBeenCalled());
  expect(api).toHaveBeenCalledWith("/api/v1/projects/p/mappings", "POST", {
    name: "Machines",
    folder_id: "f",
  });
});
it("shows durable partial state, cancellation and provenance", async () => {
  const api = vi.fn(async (path: string) =>
    path.includes("definitions")
      ? []
      : path.includes("cancel")
        ? {}
        : [
            {
              id: "run",
              state: "RUNNING",
              attempts: 1,
              metrics: { created: 100 },
            },
          ],
  );
  render(<MappingPanel api={api as Client} mapping="m" writable={true} />);
  fireEvent.click(screen.getByRole("button", { name: "Refresh mapping" }));
  fireEvent.click(
    await screen.findByRole("button", { name: "Cancel materialization" }),
  );
  await vi.waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      "/api/v1/execution/jobs/run/cancel",
      "POST",
      {},
    ),
  );
  expect(screen.getByText(/failed or cancelled runs can retain/)).toBeTruthy();
});
it("read-only shares cannot publish or materialize", () => {
  render(<MappingPanel api={vi.fn() as Client} mapping="m" writable={false} />);
  expect(
    screen.queryByRole("button", { name: "Materialize dataset" }),
  ).toBeNull();
  expect(
    screen.queryByRole("button", { name: "Publish mapping definition" }),
  ).toBeNull();
});
