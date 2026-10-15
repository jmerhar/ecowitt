import { describe, expect, it } from "vitest";
import { failures } from "./failures.mjs";

/** A page that drew everything it should. */
const WORKING = { legacy: true, text: "Weather\nOutdoors\n18.0 °C\nForecast", error: null, canvases: 1, bar: 8, cardGap: 16, iconGap: 6.4 };

describe("failures", () => {
  it("finds none in a page that drew everything and reported nothing", () => {
    expect(failures(WORKING, [])).toEqual([]);
  });

  it("passes on what the page reported", () => {
    expect(failures(WORKING, ["uncaught: ReferenceError: ResizeObserver is not defined"])).toEqual([
      "uncaught: ReferenceError: ResizeObserver is not defined",
    ]);
  });

  it.each([
    [{ legacy: false }, "did not mark itself"],
    [{ error: "SyntaxError: Unexpected token" }, "could not start: SyntaxError"],
    [{ text: "Forecast" }, "cards were not drawn"],
    [{ text: "Outdoors" }, "forecast was not drawn"],
    [{ canvases: 0 }, "no chart"],
    [{ bar: 0 }, ":where() fallbacks"],
    [{ cardGap: 0 }, "grid-gap fallback"],
    [{ iconGap: 1 }, "icon touches its text"],
  ])("names what is wrong in %o", (change, words) => {
    const found = failures({ ...WORKING, ...change }, []);
    expect(found).toHaveLength(1);
    expect(found[0]).toContain(words);
  });
});
