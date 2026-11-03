// @vitest-environment jsdom
import React from "react";
import { afterEach, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import type { Client } from "../lib/api";
import { Projects } from "../features/projects";
const project = {
  id: "p",
  name: "Project A",
  description: "",
  state: "ACTIVE",
  role: "viewer",
  revision: 1,
};
afterEach(cleanup);
it("clears private Project contents on revoked discovery and hides mutation controls for viewers", async () => {
  const api = vi.fn(async (path: string) =>
    path.includes("/folders")
      ? []
      : path.includes("/members")
        ? []
        : path.includes("/resources")
          ? [
              {
                id: "r",
                project_id: "p",
                name: "Private reference",
                resource_type: "ONTOLOGY_OBJECT_TYPE",
                ontology_id: "m",
                schema_version: "1",
                entity_id: "Machine",
              },
            ]
          : [project],
  );
  const open = vi.fn();
  render(
    <Projects
      api={api as Client}
      can={(p) => ["project:read", "project:create", "schema:read"].includes(p)}
      open={open}
    />,
  );
  await screen.findByText("Private reference");
  expect(screen.queryByRole("button", { name: "Create folder" })).toBeNull();
  expect(screen.queryByText("Manage Project")).toBeNull();
  expect(screen.queryByRole("button", { name: "Create Project" })).toBeNull();
  fireEvent.click(
    screen.getByRole("button", { name: "Open ontology in Manager" }),
  );
  expect(open).toHaveBeenCalledWith("m");
  api.mockRejectedValue(new Error("forbidden"));
  fireEvent.click(screen.getByRole("button", { name: "Refresh Projects" }));
  await screen.findByRole("alert");
  expect(screen.queryByText("Private reference")).toBeNull();
});
it("rejects stale Project list results after a newer refresh", async () => {
  let old!: (v: unknown) => void;
  const api = vi
    .fn()
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          old = resolve;
        }),
    )
    .mockResolvedValue([]);
  render(<Projects api={api as Client} can={() => true} open={() => {}} />);
  fireEvent.click(screen.getByRole("button", { name: "Refresh Projects" }));
  await screen.findByText(/No accessible Projects/);
  await act(async () => {
    old([project]);
  });
  expect(screen.queryByRole("option", { name: /Project A/ })).toBeNull();
});
