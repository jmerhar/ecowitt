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
        { metric: "rooms.temperature", sensor: "ch1", name: "Bathroom", unit: "c", source: "station", t: [1], values: { mean: [20] } },
        { metric: "rooms.temperature", sensor: "ch2", name: null, unit: "c", source: "station", t: [1], values: { mean: [19] } },
      ],
    });
    expect(align(viewFor("rooms-temperature"), rooms, {}).lines.map((l) => [l.label, l.index])).toEqual([
      ["Bathroom", 0],
      ["rooms.temperature", 1],
    ]);
    const gauges = series({
      series: [
        { metric: "rain.daily", sensor: "bucket", name: null, unit: "mm", source: "station", t: [1], values: { max: [1] } },
        { metric: "rain.daily", sensor: "piezo", name: null, unit: "mm", source: "station", t: [1], values: { max: [2] } },
        { metric: "rain.rate", sensor: "bucket", name: null, unit: "mm_h", source: "station", t: [1], values: { max: [0] } },
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
      series: [{ metric: "wind.direction", sensor: null, name: null, unit: "deg", source: "station", t: [1], values: { circular: [90] } }],
    });
    expect(align(viewFor("wind"), direction, {}).lines[0].values).toEqual([90]);
    const minOnly = series({
      series: [{ metric: "wind.speed", sensor: null, name: null, unit: "kmh", source: "station", t: [1], values: { min: [3] } }],
    });
    expect(align(viewFor("wind"), minOnly, {}).lines[0].values).toEqual([3]);
    const odd = series({
      series: [{ metric: "wind.gust", sensor: null, name: null, unit: "kmh", source: "station", t: [1], values: { p90: [7] } }],
    });
    expect(align(viewFor("wind"), odd, {}).lines[0].values).toEqual([7]);
  });
});

describe("the weather model's lines", () => {
  const answer = series({
    series: [
      ...series().series,
      { metric: "outdoor.temperature", sensor: null, name: null, unit: "c", source: "model", t: [100, 1000],
        values: { mean: [9, 13], min: [9, 13], max: [9, 13] } },
    ],
  });

  it("follow the station's, as plain lines named for the model, in the metric's colour", () => {
    const view = viewFor("temperature");
    const chart = align(view, answer, LABELS);
    expect(chart.times).toEqual([100, 400, 700, 1000]);
    expect(chart.lines.map((l) => [l.label, l.style, l.model ?? false])).toEqual([
      ["Temperature", "band", false],
      ["Dew point", "line", false],
      ["Temperature (model)", "line", true],
    ]);
    expect(chart.lines[2].values).toEqual([9, null, null, 13]);
    expect(chart.lines[2].low).toBeUndefined();
    expect(colour(view, chart.lines[2])).toBe(colour(view, chart.lines[0]));
  });

  it("are dashed, thinner, and no band", () => {
    const view = viewFor("temperature");
    const built = spec(view, align(view, answer, LABELS));
    expect(built.series.at(-1)).toMatchObject({
      label: "Temperature (model)", width: 1.5, dash: [6, 4], model: true, stroke: PALETTE[0],
    });
    expect(built.bands).toHaveLength(1);
  });

  it("stay points for a direction, without a dash", () => {
    const wind = viewFor("wind");
    const built = spec(wind, align(wind, series({
      series: [
        { metric: "wind.direction", sensor: null, name: null, unit: "deg", source: "station", t: [1], values: { circular: [170] } },
        { metric: "wind.direction", sensor: null, name: null, unit: "deg", source: "model", t: [1], values: { circular: [350] } },
      ],
    }), { "wind.direction": "Wind direction" }));
    expect(built.series.map((s) => s.label)).toEqual(["Wind direction", "Wind direction (model)"]);
    expect(built.series[1]).toMatchObject({ style: "points", width: 0, dash: undefined, model: true });
  });
});

describe("a thin line", () => {
  it("is drawn faint and narrow, behind the lines a chart is about", () => {
    const wind = viewFor("wind");
    const built = spec(wind, align(wind, series({
      series: [
        { metric: "wind.speed", sensor: null, name: null, unit: "kmh", source: "station", t: [1], values: { mean: [30] } },
        { metric: "wind.measured_speed", sensor: null, name: null, unit: "kmh", source: "station", t: [1], values: { mean: [15] } },
      ],
    }), {}));
    expect(built.series[1]).toMatchObject({ style: "thin", width: 1, stroke: `${PALETTE[3]}88` });
    expect(built.series[0]).toMatchObject({ width: 2, stroke: PALETTE[0] });
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
        { metric: "rain.daily", sensor: "bucket", name: null, unit: "mm", source: "station", t: [1], values: { max: [1] } },
        { metric: "rain.rate", sensor: "bucket", name: null, unit: "mm_h", source: "station", t: [1], values: { max: [0] } },
      ],
    });
    const built = spec(view, align(view, answer, {}));
    expect(built.series[0]).toMatchObject({ style: "bars", fill: `${PALETTE[0]}99`, width: 2 });
    expect(built.axes.map((a) => a.scale)).toEqual(["left", "right"]);
    const wind = viewFor("wind");
    const points = spec(wind, align(wind, series({
      series: [{ metric: "wind.direction", sensor: null, name: null, unit: "deg", source: "station", t: [1], values: { circular: [5] } }],
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
