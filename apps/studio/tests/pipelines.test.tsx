// @vitest-environment jsdom
import React from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { Client } from "../lib/api";
import { PipelineBuilder } from "../features/pipeline-builder";
import { CreatePipelinePanel, PipelinePanel } from "../features/pipelines";
import { fileChecksum } from "../lib/file-checksum";

class TestResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver = TestResizeObserver;
afterEach(cleanup);
it("creates a pipeline in the selected Project folder", async () => {
  const api = vi.fn(async () => ({}));
  const reload = vi.fn();
  render(
    <CreatePipelinePanel
      api={api as Client}
      project="p"
      folder="f"
      reload={reload}
    />,
  );
  fireEvent.change(screen.getByLabelText("New pipeline name"), {
    target: { value: "Cleaning" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Create pipeline" }));
  await vi.waitFor(() => expect(reload).toHaveBeenCalled());
  expect(api).toHaveBeenCalledWith("/api/v1/projects/p/pipelines", "POST", {
    name: "Cleaning",
    folder_id: "f",
  });
});
it("shows immutable definitions and cancels a running job", async () => {
  const api = vi.fn(async (path: string) => {
    if (path.includes("graph/draft")) return null;
    if (path.includes("/resources")) return [];
    if (path.includes("definitions")) return [{ id: "def", sequence: 1 }];
    if (path.includes("cancel")) return {};
    return [{ id: "run", state: "RUNNING", attempts: 1, metrics: {} }];
  });
  render(
    <PipelinePanel
      api={api as Client}
      project="project"
      pipeline="p"
      writable={true}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Refresh pipeline" }));
  fireEvent.click(await screen.findByRole("button", { name: "Cancel run" }));
  await vi.waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      "/api/v1/execution/jobs/run/cancel",
      "POST",
      {},
    ),
  );
});
it("adds a visual node by keyboard and saves an incomplete private draft", async () => {
  const api = vi.fn(async (path: string, method = "GET") => {
    if (path.includes("graph/draft") && method === "GET") return null;
    if (path.includes("graph/draft") && method === "PUT")
      return {
        revision: 1,
        graph: { format_version: 1, nodes: [], edges: [] },
      };
    if (path.includes("/resources")) return [];
    return [];
  });
  render(
    <PipelineBuilder
      api={api as Client}
      project="project"
      pipeline="pipeline"
      writable={true}
      onPublished={vi.fn()}
    />,
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "Dataset source" }),
  );
  expect(screen.getByRole("status").textContent).toContain("Unsaved changes");
  fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
  await vi.waitFor(() =>
    expect(api).toHaveBeenCalledWith(
      "/api/v1/pipelines/pipeline/graph/draft",
      "PUT",
      expect.objectContaining({
        expected_revision: 0,
        graph: expect.objectContaining({
          nodes: [expect.objectContaining({ kind: "dataset_source" })],
        }),
      }),
    ),
  );
});
it("hashes file slices without reading the whole source", async () => {
  const original = await import("node:buffer");
  const source = new original.Blob(["abc"]);
  const all = vi.spyOn(source, "arrayBuffer");
  expect(await fileChecksum(source as unknown as Blob, () => {})).toBe(
    "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
  );
  expect(all).not.toHaveBeenCalled();
});
