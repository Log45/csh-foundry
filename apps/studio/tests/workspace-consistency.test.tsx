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
import { Workspace } from "../components/workspace";
const mocks = vi.hoisted(() => ({ api: vi.fn(), session: vi.fn() }));
vi.mock("../lib/api", async (original) => ({
  ...(await original<object>()),
  browserRequest: mocks.session,
  client: () => mocks.api,
}));
vi.mock("../features/manager", () => ({
  Manager: ({ refresh }: { refresh: () => void }) => (
    <button onClick={refresh}>Refresh ontology</button>
  ),
}));
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
it("keeps the newest ontology read when an older request completes after activation", async () => {
  mocks.session.mockResolvedValue({
    csrf: "test",
    tenant: "tenant",
    tenants: [{ id: "tenant", name: "Tenant" }],
    me: { permissions: ["schema:read"] },
  });
  const ontology = { id: "m", name: "M", active_version: null };
  mocks.api.mockResolvedValueOnce([ontology]);
  render(<Workspace />);
  await screen.findByRole("button", { name: "Refresh ontology" });
  let stale!: (value: unknown) => void;
  let fresh!: (value: unknown) => void;
  mocks.api.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        stale = resolve;
      }),
  );
  mocks.api.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        fresh = resolve;
      }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Refresh ontology" }));
  fireEvent.click(screen.getByRole("button", { name: "Refresh ontology" }));
  expect(mocks.api).toHaveBeenCalledTimes(3);
  mocks.api.mockResolvedValue({ definition: { version: "1.0.0" } });
  await act(async () => {
    fresh([{ ...ontology, active_version: "1.0.0" }]);
  });
  expect(await screen.findByText("Active 1.0.0")).toBeTruthy();
  await act(async () => {
    stale([ontology]);
  });
  expect(screen.getByText("Active 1.0.0")).toBeTruthy();
});
