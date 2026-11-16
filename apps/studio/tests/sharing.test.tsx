// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { Sharing } from "../features/sharing";
import type { BrowserSession } from "../lib/api";

const mocks = vi.hoisted(() => ({ shared: vi.fn(), scoped: vi.fn() }));
vi.mock("../lib/api", async (original) => ({
  ...(await original<object>()),
  client: mocks.scoped,
}));
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

it("accepts an invitation and opens the resource using the selected acting tenant", async () => {
  const session = {
    tenant: "acting",
    csrf: "csrf",
    me: {
      principal: { principal_id: "recipient" },
      permissions: ["tenant:read"],
    },
  } as BrowserSession;
  const invitation = {
    id: "invitation",
    project_id: "project",
    owner_tenant_id: "owner",
    recipient_principal_id: "recipient",
    access: "viewer",
    state: "pending",
  };
  const lifecycle = vi
    .fn()
    .mockResolvedValueOnce([invitation])
    .mockResolvedValueOnce({ ...invitation, state: "accepted" })
    .mockResolvedValueOnce([{ ...invitation, state: "accepted" }])
    .mockResolvedValueOnce([]);
  mocks.shared.mockImplementation((path: string) =>
    path.endsWith("/folders") ? [] : { name: "Shared Project" },
  );
  mocks.scoped.mockReturnValue(mocks.shared);
  render(<Sharing api={lifecycle} session={session} />);
  fireEvent.click(
    await screen.findByRole("button", { name: "Accept invitation" }),
  );
  expect(lifecycle).toHaveBeenCalledWith(
    "/api/v1/shares/invitation/accept",
    "POST",
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "Open shared resource" }),
  );
  expect(
    await screen.findByRole("heading", { name: "Shared Project" }),
  ).toBeTruthy();
  expect(mocks.scoped).toHaveBeenCalledWith("csrf", "acting", "invitation");
  expect(screen.getAllByText("owner")).toHaveLength(2);
  expect(screen.queryByRole("button", { name: "Save Project" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Shared by me" }));
  expect(lifecycle).toHaveBeenLastCalledWith(
    "/api/v1/shares?direction=outgoing&limit=50&offset=0",
  );
});
