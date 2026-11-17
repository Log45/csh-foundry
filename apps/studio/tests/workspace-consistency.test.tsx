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
it("asks for a name and opens the workspace after creation", async () => {
  mocks.session
    .mockResolvedValueOnce({
      csrf: "test",
      nameRequired: true,
      tenants: [],
      me: null,
    })
    .mockResolvedValueOnce({ status: "selected" })
    .mockResolvedValueOnce({
      csrf: "test",
      tenant: "personal",
      tenants: [{ id: "personal", name: "My Workspace" }],
      me: { principal: { principal_id: "principal" }, permissions: [] },
    });
  mocks.api.mockResolvedValue([]);
  render(<Workspace />);
  const name = await screen.findByLabelText("Workspace name");
  const create = screen.getByRole("button", { name: "Create workspace" });
  expect(create).toHaveProperty("disabled", true);
  fireEvent.change(name, { target: { value: " My Workspace " } });
  fireEvent.click(create);
  expect(
    await screen.findByRole("option", { name: "My Workspace" }),
  ).toBeTruthy();
  expect(mocks.session).toHaveBeenCalledWith(
    "/auth/personal-tenant",
    expect.objectContaining({ body: JSON.stringify({ name: "My Workspace" }) }),
  );
  expect(screen.queryByLabelText("Workspace name")).toBeNull();
});

it("keeps the newest ontology read when an older request completes after activation", async () => {
  mocks.session.mockResolvedValue({
    csrf: "test",
    tenant: "tenant",
    tenants: [{ id: "tenant", name: "Tenant" }],
    me: {
      principal: { principal_id: "principal" },
      permissions: ["schema:read"],
    },
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

it("carries a private claim through reload and workspace naming", async () => {
  const key = "51630840-7207-4bdc-a318-6e602b82d8a9";
  const secret = "A".repeat(43);
  window.history.replaceState(null, "", "/#share=" + key + "." + secret);
  mocks.session.mockRejectedValueOnce(new Error("session_expired"));
  const signedOut = render(<Workspace />);
  await screen.findByRole("button", { name: "Sign in with OpenID Connect" });
  expect(window.location.hash).toBe("");
  signedOut.unmount();

  mocks.session
    .mockResolvedValueOnce({
      csrf: "test",
      nameRequired: true,
      tenants: [],
      me: null,
    })
    .mockResolvedValueOnce({ status: "selected" })
    .mockResolvedValueOnce({
      csrf: "test",
      tenant: "personal",
      tenants: [{ id: "personal", name: "My Workspace" }],
      me: {
        principal: { principal_id: "principal" },
        permissions: ["tenant:read"],
      },
    });
  mocks.api.mockImplementation((path: string) =>
    path.endsWith("/claim")
      ? Promise.resolve({ state: "accepted" })
      : Promise.resolve([]),
  );
  render(<Workspace />);
  fireEvent.change(await screen.findByLabelText("Workspace name"), {
    target: { value: "My Workspace" },
  });
  expect(
    screen.queryByRole("button", { name: "Accept invitation" }),
  ).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Create workspace" }));
  fireEvent.click(
    await screen.findByRole("button", { name: "Accept invitation" }),
  );
  expect(mocks.api).toHaveBeenCalledWith(
    "/api/v1/shares/" + key + "/claim",
    "POST",
    { secret },
  );
  await screen.findByRole("button", { name: "Shared with me" });
  expect(Object.values(sessionStorage)).not.toContain(key + "." + secret);
});
