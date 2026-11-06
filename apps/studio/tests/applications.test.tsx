import { describe, expect, it } from "vitest";
import {
  binding,
  renderers,
  objectProperty,
} from "@/features/application-runtime";
import { manufacturingApplication } from "@/features/application-example";
import type { AppValue } from "@/features/application-runtime";
describe("application runtime", () => {
  it("only reads own selected properties and explicit identity/revision bindings", () => {
    const state = {
      selection: {
        object_id: "M-1",
        version: 3,
        properties: { machineName: "Machine" },
      },
    };
    const value: AppValue = {
      kind: "selected",
      state: "selection",
      property: "machineName",
      value: null,
    };
    expect(binding(value, state)).toBe("Machine");
    expect(binding({ ...value, property: "$version" }, state)).toBe(3);
    expect(
      binding({ ...value, property: "constructor" }, state),
    ).toBeUndefined();
    expect(binding(value, {})).toBeUndefined();
    expect(
      objectProperty(state.selection as never, "constructor"),
    ).toBeUndefined();
    expect(
      objectProperty(
        { properties: { constructor: "owned data" } } as never,
        "constructor",
      ),
    ).toBe("owned data");
  });
  it("has a renderer for every initial widget kind", () => {
    expect(Object.keys(renderers)).toHaveLength(18);
  });
  it("rejects an example against an incompatible schema", () => {
    expect(() => manufacturingApplication({} as never, {} as never)).toThrow(
      "manufacturing fixture",
    );
  });
});
