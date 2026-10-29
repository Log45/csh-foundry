// @vitest-environment jsdom
import React from "react";
import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { SchemaGraph } from "../components/schema-graph";
import { Actions } from "../features/explorer";
import type { Schema, Client } from "../lib/api";
afterEach(cleanup);
const schema: Schema = {
  tenant_id: "00000000-0000-0000-0000-000000000001",
  id: "m",
  name: "M",
  namespace: "https://example.org/",
  version: "1.0.0",
  object_types: [
    {
      id: "Machine",
      name: "Machine",
      primary_key: "machineId",
      properties: [
        {
          id: "machineId",
          name: "Machine ID",
          data_type: "string",
          required: true,
        },
      ],
    },
  ],
  link_types: [],
  action_types: [
    {
      id: "Update",
      name: "Update",
      parameters: [
        { id: "status", name: "Status", data_type: "string", required: true },
      ],
      operations: [],
    },
  ],
};
it("offers keyboard-accessible graph selection", () => {
  const select = vi.fn();
  render(<SchemaGraph schema={schema} select={select} />);
  fireEvent.click(screen.getByRole("button", { name: "Machine" }));
  expect(select).toHaveBeenCalledWith("Machine");
  expect(
    screen.getByRole("img", { name: "Ontology schema relationships" }),
  ).toBeTruthy();
});
it("invalidates action approval when parameters change and retains replay key", async () => {
  const fn = vi.fn().mockResolvedValue({ changes: [] });
  render(
    <Actions api={fn as Client} id="m" schema={schema} can={() => true} />,
  );
  fireEvent.change(screen.getByLabelText("Status (string, required)"), {
    target: { value: "RUNNING" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Preview action" }));
  await waitFor(() =>
    expect(
      screen.getByText("I reviewed the preview and approve execution."),
    ).toBeTruthy(),
  );
  fireEvent.click(screen.getByRole("checkbox"));
  const key = (screen.getByLabelText("Idempotency key") as HTMLInputElement)
    .value;
  fireEvent.click(screen.getByRole("button", { name: "Execute action" }));
  await waitFor(() => expect(fn).toHaveBeenCalledTimes(2));
  expect(fn.mock.calls[1][2].idempotency_key).toBe(key);
  fireEvent.change(screen.getByLabelText("Status (string, required)"), {
    target: { value: "STOPPED" },
  });
  expect(screen.queryByRole("button", { name: "Execute action" })).toBeNull();
});
