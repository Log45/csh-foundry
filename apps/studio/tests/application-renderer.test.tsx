// @vitest-environment jsdom
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { FoundryClient } from "@foundry/sdk";
import {
  ApplicationRuntime,
  type AppDocument,
  type AppWidget,
} from "@/features/application-runtime";
afterEach(cleanup);
function widget(id: string, source: string | null = null): AppWidget {
  return {
    id,
    kind: source ? "table" : "text",
    label: id,
    text: "<script>private()</script>",
    parent: null,
    layout: "column",
    spacing: "normal",
    align: "stretch",
    source,
    state: null,
    property: null,
    columns: [],
    options: [],
    page: null,
    action: null,
    visible: null,
  };
}
function document(count = 0): AppDocument {
  return {
    format_version: 1,
    title: "Example",
    description: "",
    home: "home",
    states: [],
    actions: [],
    interactions: [],
    dependencies: [
      {
        id: "schema",
        resource_id: "resource",
        ontology_id: "manufacturing",
        schema_version: "1.0.0",
        policy: "exact_active",
      },
    ],
    sources: Array.from({ length: count }, (_, i) => ({
      id: `source${i}`,
      kind: "query",
      dependency: "schema",
      query: { object_type: "Machine", limit: 1 },
      aggregate: null,
      filters: {},
    })),
    pages: [
      {
        id: "home",
        title: "Home",
        description: "",
        parameters: [],
        widgets: count
          ? Array.from({ length: count }, (_, i) =>
              widget(`widget${i}`, `source${i}`),
            )
          : [widget("copy")],
      },
      {
        id: "about",
        title: "About",
        description: "",
        parameters: [],
        widgets: [],
      },
    ],
  };
}
describe("bounded application renderer", () => {
  it("renders untrusted text literally without an HTML interpreter", () => {
    render(
      <ApplicationRuntime client={{} as FoundryClient} document={document()} />,
    );
    expect(screen.getByText("<script>private()</script>")).toBeTruthy();
    expect(globalThis.document.querySelector("script")).toBeNull();
  });
  it("loads at most four sources concurrently and discards inactive-page results", async () => {
    let active = 0,
      maximum = 0;
    const signals: AbortSignal[] = [];
    const query = vi.fn(
      async (_: unknown, options: { signal: AbortSignal }) => {
        signals.push(options.signal);
        active++;
        maximum = Math.max(maximum, active);
        await new Promise((resolve) => setTimeout(resolve, 30));
        active--;
        return {
          items: [],
          next_cursor: null,
          has_more: false,
          object_type: "Machine",
          schema_version: "1.0.0",
        };
      },
    );
    const client = { applications: { query } } as unknown as FoundryClient;
    render(
      <ApplicationRuntime
        client={client}
        document={document(6)}
        application="app"
        version="version"
      />,
    );
    await waitFor(() => expect(query).toHaveBeenCalledTimes(6));
    expect(maximum).toBeLessThanOrEqual(4);
    fireEvent.click(screen.getByRole("button", { name: "About" }));
    expect(signals.every((s) => s.aborted)).toBe(true);
    expect(screen.queryAllByText("No matching objects.")).toHaveLength(0);
  });
});
