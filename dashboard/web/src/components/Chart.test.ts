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
      // The time row is named by the page, not left to uPlot's English default.
      "Time", "Temperature high", "Temperature low", "Temperature", "outdoor.dew_point",
    ]);
    expect(options.series[1].stroke).toBe("transparent");
    expect(options.axes[1].values(null, [10, 20])).toEqual(["10 °C", "20 °C"]);
    expect(options.series[3].value(null, 12.5)).toBe("12.5 °C");
    expect(options.series[3].value(null, null)).toBe("–");
    expect(options.tzDate(60)).toEqual({ d: new Date(60_000), tz: "Europe/Lisbon" });
    expect(options.series[0].value(null, 1791633600)).toBe("10 Oct, 13:00");
    expect(options.series[0].value(null, null)).toBe("–");
    expect(options.axes[0].values(null, [1791633600], 0, 0, 3600)).toEqual(["13:00\n10 Oct"]);
    resize();
    expect(made[0].sizes).toHaveLength(1);
  });

  it("draws again in the new colours when the theme changes", async () => {
    const view = viewFor("temperature");
    const data = align(view, series(), {});
    const shown = render(Chart, { view, data, symbols: SYMBOLS, timezone: "UTC" });
    expect(made).toHaveLength(1);
    document.documentElement.dataset.theme = "dark";
    await vi.waitFor(() => expect(made).toHaveLength(2));
    expect(made[0].destroyed).toBe(true);
    shown.unmount();
    delete document.documentElement.dataset.theme;
    await new Promise((resolve) => setTimeout(resolve));
    expect(made).toHaveLength(2);
  });

  it("draws again when the system switches between light and dark", () => {
    const listeners: (() => void)[] = [];
    const removed: unknown[] = [];
    globalThis.matchMedia = (() => ({
      addEventListener: (_: string, fn: () => void) => listeners.push(fn),
      removeEventListener: (_: string, fn: unknown) => removed.push(fn),
    })) as never;
    try {
      const view = viewFor("temperature");
      const shown = render(Chart, { view, data: align(view, series(), {}), symbols: SYMBOLS, timezone: "UTC" });
      expect(listeners).toHaveLength(1);
      listeners[0]();
      expect(made).toHaveLength(2);
      shown.unmount();
      expect(removed).toEqual(listeners);
    } finally {
      delete (globalThis as { matchMedia?: unknown }).matchMedia;
    }
  });

  it("follows the window's size where there is no ResizeObserver", () => {
    delete (globalThis as { ResizeObserver?: unknown }).ResizeObserver;
    const view = viewFor("temperature");
    const shown = render(Chart, { view, data: align(view, series(), {}), symbols: SYMBOLS, timezone: "UTC" });
    window.dispatchEvent(new Event("resize"));
    expect(made[0].sizes).toHaveLength(1);
    shown.unmount();
    window.dispatchEvent(new Event("resize"));
    expect(made[0].sizes).toHaveLength(1);
  });

  it("draws points without a line and bars with uPlot's bar paths", () => {
    const wind = viewFor("wind");
    const points = align(wind, series({
      series: [{ metric: "wind.direction", sensor: null, name: null, unit: "deg", source: "station", t: [1], values: { circular: [5] } }],
    }), {});
    render(Chart, { view: wind, data: points, symbols: SYMBOLS, timezone: "UTC" });
    const dot = made[0].options.series[1];
    expect(dot.paths()).toBeNull();
    expect(dot.points.show).toBe(true);
    expect(made[0].options.axes[1].side).toBe(1);

    const rain = viewFor("rain");
    const bars = align(rain, series({
      series: [{ metric: "rain.daily", sensor: "bucket", name: null, unit: "", source: "station", t: [1], values: { max: [1] } }],
    }), {});
    render(Chart, { view: rain, data: bars, symbols: {}, timezone: "UTC" });
    expect(made[1].options.series[1].paths).toBe("bars");
    expect(made[1].options.axes[1].values(null, [1])).toEqual(["1"]);
    expect(made[1].options.series[1].value(null, 2)).toBe("2");
  });

  it("draws the model dashed across its gaps, and its points hollow", () => {
    const wind = viewFor("wind");
    const data = align(wind, series({
      series: [
        { metric: "wind.speed", sensor: null, name: null, unit: "kmh", source: "station", t: [1, 2], values: { mean: [5, 6] } },
        { metric: "wind.speed", sensor: null, name: null, unit: "kmh", source: "model", t: [1], values: { mean: [9] } },
        { metric: "wind.direction", sensor: null, name: null, unit: "deg", source: "model", t: [1], values: { circular: [350] } },
      ],
    }), {});
    render(Chart, { view: wind, data, symbols: SYMBOLS, timezone: "UTC" });
    const [, station, speed, direction] = made[0].options.series;
    expect(station).toMatchObject({ spanGaps: false, dash: undefined });
    expect(speed).toMatchObject({ spanGaps: true, dash: [6, 4], width: 1.5 });
    expect(direction.points).toMatchObject({ show: true, size: 6, width: 1.5 });
    expect(direction.points.fill).not.toBe(direction.points.stroke);
  });

  it("picks out a line on a legend click, keeping its band with it", () => {
    const view = viewFor("temperature");
    render(Chart, { view, data: align(view, series(), {}), symbols: SYMBOLS, timezone: "UTC" });
    const { options } = made[0];
    expect(options.legend.isolate).toBe(true);
    // Series 1 and 2 are the temperature band's edges, 3 its line, 4 the dew point.
    const shown = [true, false, false, true, false];
    const plot = {
      series: shown.map((show) => ({ show })),
      setSeries: vi.fn((i: number, { show }: { show: boolean }) => (plot.series[i].show = show)),
    };
    options.hooks.setSeries[0](plot);
    expect(plot.series.map((s) => s.show)).toEqual([true, true, true, true, false]);
    expect(plot.setSeries).toHaveBeenCalledWith(1, { show: true }, false);
    plot.series[3].show = false;
    plot.setSeries.mockClear();
    options.hooks.setSeries[0](plot);
    expect(plot.series.slice(1, 3).map((s) => s.show)).toEqual([false, false]);
    options.hooks.setSeries[0](plot);
    expect(plot.setSeries).toHaveBeenCalledTimes(2);
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
