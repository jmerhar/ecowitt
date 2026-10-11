import { describe, expect, it } from "vitest";
import { align, colour, PALETTE, spec, viewFor, VIEWS } from "./chart";
import { series } from "../testing";

const LABELS = { "outdoor.temperature": "Temperature", "outdoor.dew_point": "Dew point" };

describe("align", () => {
  it("puts every series on one time column, with gaps where a bucket is missing", () => {
    const chart = align(viewFor("temperature"), series(), LABELS);
    expect(chart.times).toEqual([100, 400, 700]);
    const [temperature, dew] = chart.lines;
    expect(temperature).toMatchObject({ label: "Temperature", values: [10, 11, 12], low: [9, 10, 11], high: [11, 12, 13] });
    expect(dew).toMatchObject({ label: "Dew point", values: [5, null, 6], style: "line" });
    expect(dew.low).toBeUndefined();
  });

  it("ignores series the view does not show", () => {
    const chart = align(viewFor("wind"), series(), LABELS);
    expect(chart).toEqual({ times: [], lines: [] });
  });

  it("names room lines by room, and tells apart several gauges", () => {
    const rooms = series({
      series: [
        { metric: "rooms.temperature", sensor: "ch1", name: "Bathroom", unit: "c", t: [1], values: { mean: [20] } },
        { metric: "rooms.temperature", sensor: "ch2", name: null, unit: "c", t: [1], values: { mean: [19] } },
      ],
    });
    expect(align(viewFor("rooms-temperature"), rooms, {}).lines.map((l) => [l.label, l.index])).toEqual([
      ["Bathroom", 0],
      ["rooms.temperature", 1],
    ]);
    const gauges = series({
      series: [
        { metric: "rain.daily", sensor: "bucket", name: null, unit: "mm", t: [1], values: { max: [1] } },
        { metric: "rain.daily", sensor: "piezo", name: null, unit: "mm", t: [1], values: { max: [2] } },
        { metric: "rain.rate", sensor: "bucket", name: null, unit: "mm_h", t: [1], values: { max: [0] } },
      ],
    });
    expect(align(viewFor("rain"), gauges, { "rain.daily": "Rain today" }).lines.map((l) => l.label)).toEqual([
      "Rain today (bucket)",
      "Rain today (piezo)",
      "rain.rate",
    ]);
  });

  it("takes each series' main aggregate", () => {
    const direction = series({
      series: [{ metric: "wind.direction", sensor: null, name: null, unit: "deg", t: [1], values: { circular: [90] } }],
    });
    expect(align(viewFor("wind"), direction, {}).lines[0].values).toEqual([90]);
    const minOnly = series({
      series: [{ metric: "wind.speed", sensor: null, name: null, unit: "kmh", t: [1], values: { min: [3] } }],
    });
    expect(align(viewFor("wind"), minOnly, {}).lines[0].values).toEqual([3]);
    const odd = series({
      series: [{ metric: "wind.gust", sensor: null, name: null, unit: "kmh", t: [1], values: { p90: [7] } }],
    });
    expect(align(viewFor("wind"), odd, {}).lines[0].values).toEqual([7]);
  });
});

describe("spec", () => {
  it("draws a band's edges as a filled band behind its line", () => {
    const view = viewFor("temperature");
    const built = spec(view, align(view, series(), LABELS));
    expect(built.series.map((s) => s.label)).toEqual(["Temperature high", "Temperature low", "Temperature", "Dew point"]);
    expect(built.bands).toEqual([{ series: [1, 2], fill: `${PALETTE[0]}33` }]);
    expect(built.data).toHaveLength(5);
    expect(built.axes).toEqual([{ scale: "left", unit: "c" }]);
    expect(built.series[3].stroke).toBe(PALETTE[1]);
  });

  it("gives points no line and bars a fill, each on its own axis", () => {
    const view = viewFor("rain");
    const answer = series({
      series: [
        { metric: "rain.daily", sensor: "bucket", name: null, unit: "mm", t: [1], values: { max: [1] } },
        { metric: "rain.rate", sensor: "bucket", name: null, unit: "mm_h", t: [1], values: { max: [0] } },
      ],
    });
    const built = spec(view, align(view, answer, {}));
    expect(built.series[0]).toMatchObject({ style: "bars", fill: `${PALETTE[0]}99`, width: 2 });
    expect(built.axes.map((a) => a.scale)).toEqual(["left", "right"]);
    const wind = viewFor("wind");
    const points = spec(wind, align(wind, series({
      series: [{ metric: "wind.direction", sensor: null, name: null, unit: "deg", t: [1], values: { circular: [5] } }],
    }), {}));
    expect(points.series[0]).toMatchObject({ style: "points", width: 0, scale: "right" });
  });
});

describe("views", () => {
  it("fall back to the first for an unknown id", () => {
    expect(viewFor("nonsense")).toBe(VIEWS[0]);
  });

  it("colour a metric that is not in the view like the first", () => {
    const line = { metric: "x", label: "", unit: "", style: "line" as const, axis: "left" as const, index: 0, values: [] };
    expect(colour(VIEWS[0], line)).toBe(PALETTE[0]);
    expect(colour(VIEWS[0], { ...line, index: 12 })).toBe(PALETTE[2]);
  });
});
