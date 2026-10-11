import { describe, expect, it } from "vitest";
import { DEFAULTS, load, save } from "./prefs";

function memory(initial: Record<string, string> = {}): Storage {
  const data = new Map(Object.entries(initial));
  return {
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, v),
    removeItem: (k: string) => void data.delete(k),
    clear: () => data.clear(),
    key: () => null,
    get length() {
      return data.size;
    },
  };
}

describe("prefs", () => {
  it("round-trip through storage", () => {
    const storage = memory();
    const prefs = { ...DEFAULTS, station: "Home", units: { wind: "mph" }, range: "7d" };
    save(prefs, storage);
    expect(load(storage)).toEqual(prefs);
  });

  it("fall back to the defaults when nothing or nonsense is saved", () => {
    expect(load(memory())).toEqual(DEFAULTS);
    expect(load(memory({ "ecowitt-dashboard": "not json" }))).toEqual(DEFAULTS);
    expect(load(memory({ "ecowitt-dashboard": "null" }))).toEqual(DEFAULTS);
    expect(load(memory({ "ecowitt-dashboard": JSON.stringify({ station: 3, units: "x", view: 1 }) })))
      .toEqual(DEFAULTS);
    expect(load(undefined)).toEqual(DEFAULTS);
  });

  it("survive storage that refuses", () => {
    const refusing = { ...memory(), setItem: () => { throw new Error("quota"); }, getItem: () => { throw new Error("blocked"); } };
    expect(() => save(DEFAULTS, refusing as Storage)).not.toThrow();
    expect(load(refusing as Storage)).toEqual(DEFAULTS);
  });
});
