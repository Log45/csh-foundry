// @vitest-environment jsdom
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { Sharing } from "../features/sharing";
import { RecipientPicker, type Recipient } from "../features/recipient-picker";
import type { Client } from "../lib/api";
import { APIError, type BrowserSession } from "../lib/api";

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

it("invites the selected user to the selected shareable resource", async () => {
  const session = {
    tenant: "acting",
    csrf: "csrf",
    me: {
      principal: { principal_id: "owner" },
      permissions: ["project:read", "project:manage"],
    },
  } as BrowserSession;
  const api = vi.fn(async (path: string) => {
    if (path === "/api/v1/shares/targets/project?search=Plant")
      return [{ id: "project-id", label: "Plant Operations" }];
    if (path === "/api/v1/shares/recipient-directory?search=ali")
      return {
        results: [
          {
            id: "foundry-user-id",
            source: "keycloak",
            username: "alice",
            display_name: "Alice Example",
          },
        ],
        unavailable_sources: [],
      };
    return [];
  });
  render(
    <Sharing
      api={api as unknown as Parameters<typeof Sharing>[0]["api"]}
      session={session}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Shared by me" }));
  fireEvent.change(screen.getByLabelText("Search project"), {
    target: { value: "Plant" },
  });
  fireEvent.change(screen.getByRole("combobox", { name: "Recipient" }), {
    target: { value: "ali" },
  });
  await screen.findByRole("option", { name: "Plant Operations" });
  await screen.findByRole("option", { name: "Alice Example (alice) Keycloak" });
  fireEvent.change(screen.getByLabelText("Project to share", { exact: true }), {
    target: { value: "project-id" },
  });
  const input = screen.getByRole("combobox", {
    name: "Recipient",
  });
  fireEvent.keyDown(input, { key: "ArrowDown" });
  expect(input.getAttribute("aria-activedescendant")).toBeTruthy();
  fireEvent.keyDown(input, { key: "Enter" });
  expect(input).toHaveProperty("value", "Alice Example (alice)");
  fireEvent.click(screen.getByRole("button", { name: "Send invitation" }));
  expect(api).toHaveBeenCalledWith("/api/v1/shares", "POST", {
    access: "viewer",
    project_id: "project-id",
    recipient_principal_id: "foundry-user-id",
  });
});

it("switches to inviting by principal ID when the directory is unconfigured", async () => {
  const session = {
    tenant: "acting",
    csrf: "csrf",
    me: {
      principal: { principal_id: "owner" },
      permissions: ["project:read", "project:manage"],
    },
  } as BrowserSession;
  const api = vi.fn(async (path: string) => {
    if (path.startsWith("/api/v1/shares/targets/project"))
      return [{ id: "project-id", label: "Plant Operations" }];
    if (path.startsWith("/api/v1/shares/recipient-directory"))
      throw new APIError(503, "directory_unconfigured");
    return [];
  });
  render(
    <Sharing
      api={api as unknown as Parameters<typeof Sharing>[0]["api"]}
      session={session}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Shared by me" }));
  fireEvent.focus(screen.getByRole("combobox", { name: "Recipient" }));
  const principal = await screen.findByLabelText("Recipient principal ID");
  await screen.findByRole("option", { name: "Plant Operations" });
  fireEvent.change(screen.getByLabelText("Project to share"), {
    target: { value: "project-id" },
  });
  fireEvent.change(principal, { target: { value: "foundry-user-id" } });
  fireEvent.click(screen.getByRole("button", { name: "Send invitation" }));
  expect(api).toHaveBeenCalledWith("/api/v1/shares", "POST", {
    access: "viewer",
    project_id: "project-id",
    recipient_principal_id: "foundry-user-id",
  });
  expect(screen.queryByRole("option", { name: "Directory user" })).toBeNull();
});

const directory = "/api/v1/shares/recipient-directory";
const alicia: Recipient = {
  id: "directory-alicia",
  source: "ldap",
  username: "alicia",
  display_name: "Alicia Example (alicia)",
};
const maria: Recipient = {
  id: "directory-maria",
  source: "ldap",
  username: "maria",
  display_name: "Maria Example",
};

it("browses on focus, loads more, selects by mouse and clears selection when edited", async () => {
  const onSelect = vi.fn();
  const api = vi.fn(async (path: string, method?: string) => {
    if (method === "DELETE") return {};
    return path.includes("cursor=")
      ? {
          results: [maria],
          next_cursor: "second-page",
          unavailable_sources: [],
        }
      : {
          results: [alicia],
          next_cursor: "first-page",
          unavailable_sources: [],
        };
  });
  const props = {
    api: api as unknown as Client,
    onSelect,
    onDirectoryUnconfigured: vi.fn(),
  };
  const view = render(<RecipientPicker {...props} />);
  const input = screen.getByRole("combobox");
  fireEvent.focus(input);
  await screen.findByRole("option", { name: "Alicia Example (alicia) LDAP" });
  expect(api).toHaveBeenCalledWith(directory + "?search=");
  fireEvent.click(screen.getByRole("button", { name: "Load more" }));
  const choice = await screen.findByRole("option", {
    name: "Maria Example (maria) LDAP",
  });
  expect(api).toHaveBeenCalledWith(directory + "?search=&cursor=first-page");
  fireEvent.mouseDown(choice);
  fireEvent.click(choice);
  expect(onSelect).toHaveBeenLastCalledWith(maria);
  view.rerender(<RecipientPicker {...props} selected={maria} />);
  expect(input).toHaveProperty("value", "Maria Example (maria)");
  expect(input.getAttribute("aria-expanded")).toBe("false");
  expect(api).toHaveBeenCalledWith(directory + "?cursor=second-page", "DELETE");
  fireEvent.change(input, { target: { value: "Mar" } });
  expect(onSelect).toHaveBeenLastCalledWith(undefined);
  view.rerender(<RecipientPicker {...props} />);
  expect(input.getAttribute("aria-expanded")).toBe("true");
  fireEvent.keyDown(input, { key: "Escape" });
  expect(input.getAttribute("aria-expanded")).toBe("false");
});

it("ignores stale pages and releases their cursors while keeping healthy results", async () => {
  let resolveStale!: (value: unknown) => void;
  const api = vi.fn((path: string, method?: string) => {
    if (method === "DELETE") return Promise.resolve({});
    if (path.endsWith("=al"))
      return new Promise((resolve) => {
        resolveStale = resolve;
      });
    return Promise.resolve({
      results: path.endsWith("=ma") ? [maria] : [],
      unavailable_sources: ["keycloak"],
    });
  });
  render(
    <RecipientPicker
      api={api as unknown as Client}
      onSelect={vi.fn()}
      onDirectoryUnconfigured={vi.fn()}
    />,
  );
  const input = screen.getByRole("combobox");
  fireEvent.change(input, { target: { value: "al" } });
  await waitFor(() =>
    expect(api).toHaveBeenCalledWith(directory + "?search=al"),
  );
  fireEvent.change(input, { target: { value: "ma" } });
  await screen.findByRole("option", { name: "Maria Example (maria) LDAP" });
  expect(screen.getByRole("status").textContent).toContain(
    "Keycloak unavailable.",
  );
  await act(async () =>
    resolveStale({
      results: [alicia],
      next_cursor: "stale",
      unavailable_sources: [],
    }),
  );
  expect(screen.queryByRole("option", { name: /Alicia/ })).toBeNull();
  expect(api).toHaveBeenCalledWith(directory + "?cursor=stale", "DELETE");
});

it("routes LDAP selection to a private claim link and refuses unselected query text", async () => {
  const secret = "A".repeat(43);
  const key = "51630840-7207-4bdc-a318-6e602b82d8a9";
  const session = {
    tenant: "acting",
    csrf: "csrf",
    me: {
      principal: { principal_id: "owner" },
      permissions: ["project:read", "project:manage"],
    },
  } as BrowserSession;
  const api = vi.fn(async (path: string) => {
    if (path.startsWith("/api/v1/shares/targets/project"))
      return [{ id: "project-id", label: "Plant Operations" }];
    if (path.startsWith(directory))
      return { results: [maria], unavailable_sources: [] };
    if (path.endsWith("/directory-invitations"))
      return { share: { id: key }, claim_secret: secret };
    return [];
  });
  render(<Sharing api={api as unknown as Client} session={session} />);
  fireEvent.click(screen.getByRole("button", { name: "Shared by me" }));
  await screen.findByRole("option", { name: "Plant Operations" });
  fireEvent.change(screen.getByLabelText("Project to share"), {
    target: { value: "project-id" },
  });
  const input = screen.getByRole("combobox", {
    name: "Recipient",
  });
  fireEvent.focus(input);
  fireEvent.click(
    await screen.findByRole("option", { name: "Maria Example (maria) LDAP" }),
  );
  const submit = screen.getByRole("button", { name: "Send invitation" });
  fireEvent.change(input, { target: { value: "mar" } });
  expect(submit).toHaveProperty("disabled", true);
  fireEvent.click(
    await screen.findByRole("option", { name: "Maria Example (maria) LDAP" }),
  );
  fireEvent.click(submit);
  expect(api).toHaveBeenCalledWith(
    "/api/v1/shares/directory-invitations",
    "POST",
    {
      access: "viewer",
      project_id: "project-id",
      selection: "directory-maria",
    },
  );
  const link = new URL(
    ((await screen.findByLabelText("Invitation link")) as HTMLInputElement)
      .value,
  );
  expect(link.search).toBe("");
  expect(link.hash).toBe("#share=" + key + "." + secret);
});

it("restarts expired continuations at the first page", async () => {
  const api = vi.fn(async (path: string) => {
    if (path.includes("cursor=")) throw new APIError(409, "directory_restart");
    return {
      results: [alicia],
      next_cursor: "cursor",
      unavailable_sources: [],
    };
  });
  render(
    <RecipientPicker
      api={api as unknown as Client}
      onSelect={vi.fn()}
      onDirectoryUnconfigured={vi.fn()}
    />,
  );
  fireEvent.focus(screen.getByRole("combobox"));
  fireEvent.click(await screen.findByRole("button", { name: "Load more" }));
  const restart = await screen.findByRole("button", { name: "Restart search" });
  expect(screen.getByRole("status").textContent).toMatch(/page expired/);
  expect(
    screen.getByRole("option", { name: "Alicia Example (alicia) LDAP" }),
  ).toBeTruthy();
  fireEvent.click(restart);
  await screen.findByRole("button", { name: "Load more" });
  expect(
    api.mock.calls.filter(([path]) => path === directory + "?search="),
  ).toHaveLength(2);
});
