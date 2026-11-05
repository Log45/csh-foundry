// @vitest-environment jsdom
import React from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { Client } from "../lib/api";
import {
  CreateGovernedPanel,
  GovernedPanel,
} from "../features/governed-processing";
afterEach(cleanup);
it("creates the selected governed family in the current folder", async () => {
  const api = vi.fn(async () => ({})),
    reload = vi.fn();
  render(
    <CreateGovernedPanel
      api={api as Client}
      project="project"
      folder="folder"
      reload={reload}
    />,
  );
  fireEvent.change(screen.getByLabelText("Processing resource type"), {
    target: { value: "functions" },
  });
  fireEvent.change(screen.getByLabelText("Processing resource name"), {
    target: { value: "Normalize" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Create processing resource" }),
  );
  await vi.waitFor(() => expect(reload).toHaveBeenCalled());
  expect(api).toHaveBeenCalledWith(
    "/api/v1/projects/project/functions",
    "POST",
    { name: "Normalize", folder_id: "folder" },
  );
});
it("removes private results and history when refreshed access is revoked", async () => {
  let revoked = false;
  const api = vi.fn(async (path: string) => {
    if (revoked) throw new Error("not_found");
    if (path.includes("definitions")) return [{ id: "version", sequence: 1 }];
    if (path.includes("result")) return { values: { text: "PRIVATE RESULT" } };
    return [{ id: "job", state: "SUCCEEDED", metrics: {}, attempts: 1 }];
  });
  render(
    <GovernedPanel
      api={api as Client}
      resource="fn"
      family="functions"
      writable
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Refresh functions" }));
  fireEvent.click(
    await screen.findByRole("button", { name: "Inspect function result" }),
  );
  await screen.findByText(/PRIVATE RESULT/);
  revoked = true;
  fireEvent.click(screen.getByRole("button", { name: "Refresh functions" }));
  await screen.findByText("not_found");
  expect(screen.queryByText(/PRIVATE RESULT/)).toBeNull();
  expect(
    screen.queryByRole("button", { name: "Inspect function result" }),
  ).toBeNull();
});
