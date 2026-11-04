// @vitest-environment jsdom
import React from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { Client } from "../lib/api";
import { DatasetPanel } from "../features/datasets";
afterEach(cleanup);
it("shows immutable schema, ordered null/nested preview and validation failures to viewers", async () => {
  const api = vi.fn(async (path: string) =>
    path.includes("preview")
      ? {
          columns: [
            { name: "id", logical_type: "Int64", nullable: false },
            { name: "extra", logical_type: "List", nullable: true },
          ],
          rows: [
            [1, null],
            [2, { nested: [true] }],
          ],
          row_count: 2,
        }
      : [
          {
            id: "v",
            sequence: 1,
            state: "COMMITTED",
            artifact_state: "COMMITTED",
            result: {},
          },
          {
            id: "bad",
            sequence: 2,
            state: "FAILED",
            artifact_state: "COMMITTED",
            result: { message: "Invalid content" },
          },
        ],
  );
  render(<DatasetPanel api={api as Client} dataset="d" writable={false} />);
  fireEvent.click(screen.getByRole("button", { name: "Load versions" }));
  fireEvent.click(
    await screen.findByRole("button", {
      name: "Inspect schema and preview version 1",
    }),
  );
  await screen.findByRole("cell", { name: "null" });
  expect(screen.getByText('{"nested":[true]}')).toBeTruthy();
  expect(screen.getByText("Invalid content")).toBeTruthy();
  expect(
    screen.queryByRole("button", { name: "Upload new version" }),
  ).toBeNull();
  api.mockRejectedValue(new Error("forbidden"));
  fireEvent.click(screen.getByRole("button", { name: "Load versions" }));
  await screen.findByText(/forbidden/);
  expect(screen.queryByRole("table")).toBeNull();
});
