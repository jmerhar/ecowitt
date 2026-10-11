import { render } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Chart from "./Chart.svelte";
import { align, viewFor } from "../lib/chart";
import { series, SYMBOLS } from "../testing";

const made: { options: any; data: any; destroyed: boolean; sizes: unknown[] }[] = [];

vi.mock("uplot", () => {
  class FakePlot {
    record: (typeof made)[number];
    constructor(options: unknown, data: unknown) {
      this.record = { options, data, destroyed: false, sizes: [] };
      made.push(this.record);
    }
    destroy() {
      this.record.destroyed = true;
    }
    setSize(size: unknown) {
      this.record.sizes.push(size);
    }
    static tzDate = (d: Date, tz: string) => ({ d, tz });
    static paths = { bars: () => "bars" };
  }
  return { default: FakePlot };
});
vi.mock("uplot/dist/uPlot.min.css", () => ({}));

let resize: () => void = () => {};
beforeEach(() => {
  made.length = 0;
  globalThis.ResizeObserver = class {
    constructor(callback: () => void) {
      resize = callback;
    }
    observe() {}
    disconnect() {}
  } as never;
});

describe("Chart", () => {
  it("hands uPlot the aligned columns, bands and labelled axes", () => {
    const view = viewFor("temperature");
    const data = align(view, series(), { "outdoor.temperature": "Temperature" });
    render(Chart, { view, data, symbols: SYMBOLS, timezone: "Europe/Lisbon" });
    expect(made).toHaveLength(1);
    const { options, data: columns } = made[0];
    expect(columns[0]).toEqual([100, 400, 700]);
    expect(options.bands).toEqual([{ series: [1, 2], fill: expect.stringMatching(/33$/) }]);
    expect(options.series.map((s: { label?: string }) => s.label)).toEqual([
      undefined, "Temperature high", "Temperature low", "Temperature", "outdoor.dew_point",
    ]);
    expect(options.series[1].stroke).toBe("transparent");
    expect(options.axes[1].values(null, [10, 20])).toEqual(["10 °C", "20 °C"]);
    expect(options.series[3].value(null, 12.5)).toBe("12.5 °C");
    expect(options.series[3].value(null, null)).toBe("–");
    expect(options.tzDate(60)).toEqual({ d: new Date(60_000), tz: "Europe/Lisbon" });
    resize();
    expect(made[0].sizes).toHaveLength(1);
  });

  it("draws points without a line and bars with uPlot's bar paths", () => {
    const wind = viewFor("wind");
    const points = align(wind, series({
      series: [{ metric: "wind.direction", sensor: null, name: null, unit: "deg", t: [1], values: { circular: [5] } }],
    }), {});
    render(Chart, { view: wind, data: points, symbols: SYMBOLS, timezone: "UTC" });
    const dot = made[0].options.series[1];
    expect(dot.paths()).toBeNull();
    expect(dot.points.show).toBe(true);
    expect(made[0].options.axes[1].side).toBe(1);

    const rain = viewFor("rain");
    const bars = align(rain, series({
      series: [{ metric: "rain.daily", sensor: "bucket", name: null, unit: "", t: [1], values: { max: [1] } }],
    }), {});
    render(Chart, { view: rain, data: bars, symbols: {}, timezone: "UTC" });
    expect(made[1].options.series[1].paths).toBe("bars");
    expect(made[1].options.axes[1].values(null, [1])).toEqual(["1"]);
    expect(made[1].options.series[1].value(null, 2)).toBe("2");
  });

  it("redraws when its data changes, and cleans up when it goes", async () => {
    const view = viewFor("temperature");
    const first = align(view, series(), {});
    const chart = render(Chart, { view, data: first, symbols: SYMBOLS, timezone: "UTC" });
    await chart.rerender({ view, data: { ...first }, symbols: SYMBOLS, timezone: "UTC" });
    expect(made).toHaveLength(2);
    expect(made[0].destroyed).toBe(true);
    chart.unmount();
    expect(made[1].destroyed).toBe(true);
  });
});
