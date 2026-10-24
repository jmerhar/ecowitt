/**
 * The charts: which metrics each tab shows, and how the API's bucketed series become the
 * aligned columns uPlot draws. Kept apart from the component so it can be tested without a
 * canvas.
 */

import type { Series, SeriesOut } from "./api";
import type { WindHeight } from "./prefs";
import { m } from "../paraglide/messages.js";

/** How one metric is drawn. */
export type Style = "line" | "band" | "points" | "bars" | "thin";

/** A chart tab: its metrics, how each is drawn, on which axis, and a label of its own if the
 * metric's would mislead in this view. Labels are message functions, read when drawn in the
 * page's language. */
export type View = {
  id: string;
  label: () => string;
  metrics: { id: string; style: Style; axis: "left" | "right"; label?: () => string }[];
};

export const VIEWS: View[] = [
  {
    id: "temperature",
    label: m.view_temperature,
    metrics: [
      { id: "outdoor.temperature", style: "band", axis: "left" },
      { id: "outdoor.dew_point", style: "line", axis: "left" },
    ],
  },
  {
    id: "humidity",
    label: m.view_humidity,
    metrics: [{ id: "outdoor.humidity", style: "band", axis: "left" }],
  },
  {
    id: "wind",
    label: m.view_wind,
    // Speed and gust at 10 m; what the sensor measured, faint behind them.
    metrics: [
      { id: "wind.speed", style: "line", axis: "left" },
      { id: "wind.gust", style: "line", axis: "left" },
      { id: "wind.direction", style: "points", axis: "right" },
      { id: "wind.measured_speed", style: "thin", axis: "left" },
    ],
  },
  {
    id: "rain",
    label: m.view_rain,
    metrics: [
      { id: "rain.amount", style: "bars", axis: "left" },
      { id: "rain.rate", style: "line", axis: "right" },
    ],
  },
  {
    id: "pressure",
    label: m.view_pressure,
    metrics: [{ id: "pressure.sea_level", style: "band", axis: "left" }],
  },
  {
    id: "sun",
    label: m.view_sun,
    metrics: [
      { id: "solar.radiation", style: "line", axis: "left" },
      { id: "solar.uv_index", style: "line", axis: "right" },
    ],
  },
  {
    id: "rooms-temperature",
    label: m.view_rooms_temperature,
    metrics: [{ id: "rooms.temperature", style: "line", axis: "left" }],
  },
  {
    id: "rooms-humidity",
    label: m.view_rooms_humidity,
    metrics: [{ id: "rooms.humidity", style: "line", axis: "left" }],
  },
];

/** The wind tab for a visitor who leads with the measured wind: the estimate at 10 m faint
 * behind it, in the places the measured lines take in the 10 m view, so the colours swap too. */
export const MEASURED_WIND: View = {
  id: "wind",
  label: m.view_wind,
  metrics: [
    { id: "wind.measured_speed", style: "line", axis: "left" },
    { id: "wind.measured_gust", style: "line", axis: "left" },
    { id: "wind.direction", style: "points", axis: "right" },
    { id: "wind.speed", style: "thin", axis: "left", label: m.chart_wind_speed_10m },
  ],
};

/** The tab a section of the page drills down to when clicked, with the wind the visitor leads
 * with. */
export function viewFor(id: string, wind: WindHeight = "10m"): View {
  if (id === "wind" && wind === "sensor") return MEASURED_WIND;
  return VIEWS.find((v) => v.id === id) ?? VIEWS[0];
}

/** One drawn line or band edge, aligned to the chart's shared time column. */
export type Line = {
  metric: string;
  label: string;
  unit: string;
  style: Style;
  axis: "left" | "right";
  /** Which line it is within its metric, for picking a colour. */
  index: number;
  /** The weather model's line for the metric, drawn dashed in the metric's colour. */
  model?: boolean;
  values: (number | null)[];
  /** The band's edges, for a band. */
  low?: (number | null)[];
  high?: (number | null)[];
};

export type ChartData = { times: number[]; lines: Line[] };

/** The main aggregate of a series: the mean when there is one, else its only one. */
function main(series: Series): string {
  for (const name of ["mean", "max", "circular", "min"]) {
    if (name in series.values) return name;
  }
  return Object.keys(series.values)[0];
}

/**
 * Align a view's series on one time column. Buckets a series lacks become gaps (null), so a
 * sensor that stopped reporting shows as a break rather than a line drawn across the silence.
 * The weather model's series, when the answer has them, become lines of their own after the
 * station's, plain lines however the metric is drawn.
 */
export function align(view: View, answer: SeriesOut, labels: Record<string, string>): ChartData {
  const wanted = new Map(view.metrics.map((metric) => [metric.id, metric]));
  const chosen = answer.series.filter((s) => wanted.has(s.metric));
  const times = [...new Set(chosen.flatMap((s) => s.t))].sort((a, b) => a - b);
  const position = new Map(times.map((t, i) => [t, i]));
  const column = (series: Series, aggregate: string): (number | null)[] => {
    const out: (number | null)[] = new Array(times.length).fill(null);
    const values = series.values[aggregate] ?? [];
    series.t.forEach((t, i) => {
      out[position.get(t) as number] = values[i] ?? null;
    });
    return out;
  };
  const counts = new Map<string, number>();
  const measured = chosen.filter((s) => s.source !== "model");
  const several = new Set(
    measured.map((s) => s.metric).filter((metric, i, all) => all.indexOf(metric) !== i),
  );
  const lines = measured.map((series) => {
    const how = wanted.get(series.metric)!;
    const index = counts.get(series.metric) ?? 0;
    counts.set(series.metric, index + 1);
    const metricLabel = how.label?.() ?? labels[series.metric] ?? series.metric;
    const line: Line = {
      metric: series.metric,
      // A per-room chart names each line by its room; a station-wide one by its metric.
      label: series.metric.startsWith("rooms.")
        ? (series.name ?? metricLabel)
        : several.has(series.metric)
          ? `${metricLabel} (${series.sensor})`
          : metricLabel,
      unit: series.unit,
      style: how.style,
      axis: how.axis,
      index,
      values: column(series, main(series)),
    };
    if (how.style === "band" && "min" in series.values && "max" in series.values) {
      line.low = column(series, "min");
      line.high = column(series, "max");
    }
    return line;
  });
  for (const series of chosen.filter((s) => s.source === "model")) {
    const how = wanted.get(series.metric)!;
    lines.push({
      metric: series.metric,
      label: m.chart_model_line({ label: how.label?.() ?? labels[series.metric] ?? series.metric }),
      unit: series.unit,
      style: how.style === "points" ? "points" : "line",
      axis: how.axis,
      index: 0,
      model: true,
      values: column(series, main(series)),
    });
  }
  return { times, lines };
}

/** Line colours, readable on both the light and the dark background. */
export const PALETTE = [
  "#3a9b84", "#e08a3c", "#4a7fd1", "#9b6bd1", "#d1544a",
  "#c9a227", "#d16ba0", "#5fa84f", "#a0704a", "#7f8c8d",
];

/** The colour of a line: its metric's place in the view, then the line's within the metric. */
export function colour(view: View, line: Line): string {
  const metricIndex = Math.max(0, view.metrics.findIndex((metric) => metric.id === line.metric));
  return PALETTE[(metricIndex + line.index) % PALETTE.length];
}

/** What uPlot needs, minus the functions only a browser can run (paths, tzDate). */
export type PlotSpec = {
  data: (number | null)[][];
  series: {
    label: string;
    scale: "left" | "right";
    stroke: string;
    width: number;
    style: Style;
    unit: string;
    fill?: string;
    /** A band's edge, drawn only as the band's fill. */
    edge?: boolean;
    /** The weather model's line: dashed, or hollow points, and drawn across its gaps. */
    model?: boolean;
    dash?: number[];
  }[];
  bands: { series: [number, number]; fill: string }[];
  axes: { scale: "left" | "right"; unit: string }[];
};

/** The columns, series and bands for a view's aligned data. */
export function spec(view: View, chart: ChartData): PlotSpec {
  const data: (number | null)[][] = [chart.times];
  const series: PlotSpec["series"] = [];
  const bands: PlotSpec["bands"] = [];
  const axes = new Map<string, { scale: "left" | "right"; unit: string }>();
  for (const line of chart.lines) {
    const stroke = colour(view, line);
    if (!axes.has(line.axis)) axes.set(line.axis, { scale: line.axis, unit: line.unit });
    if (line.low && line.high) {
      const base = {
        scale: line.axis,
        stroke,
        width: 0,
        style: "line" as Style,
        unit: line.unit,
        edge: true,
      };
      data.push(line.high);
      series.push({ ...base, label: `${line.label} high` });
      data.push(line.low);
      series.push({ ...base, label: `${line.label} low` });
      bands.push({ series: [series.length - 1, series.length], fill: `${stroke}33` });
    }
    data.push(line.values);
    if (line.model) {
      series.push({
        label: line.label,
        scale: line.axis,
        stroke,
        width: line.style === "points" ? 0 : 1.5,
        style: line.style,
        unit: line.unit,
        model: true,
        dash: line.style === "points" ? undefined : [6, 4],
      });
      continue;
    }
    series.push({
      label: line.label,
      scale: line.axis,
      // A thin line is drawn faint, behind the lines a chart is about.
      stroke: line.style === "thin" ? `${stroke}88` : stroke,
      width: line.style === "points" ? 0 : line.style === "thin" ? 1 : 2,
      style: line.style,
      unit: line.unit,
      fill: line.style === "bars" ? `${stroke}99` : undefined,
    });
  }
  return { data, series, bands, axes: [...axes.values()] };
}

/** The steps an aligned axis takes between ticks: 1, 2, 2.5 and 5 times a power of ten. */
const NICE_STEPS = [1, 2, 2.5, 5];

/** A direction axis spans the compass in quarters, so the other axis is divided to match. */
const DIRECTION_DIVISIONS = 4;

/**
 * How many divisions both axes of a two-axis chart share: one per 40 px or so of plot, or the
 * direction axis's quarters. Only the left axis draws grid lines, so the right one's ticks must
 * fall on them, which they do only when both scales are cut into the same number of parts.
 */
export function axisDivisions(axes: PlotSpec["axes"], height: number): number {
  if (axes.some((a) => a.unit === "deg")) return DIRECTION_DIVISIONS;
  return Math.min(8, Math.max(3, Math.round((height - 80) / 40)));
}

/** Round off the binary noise that adding steps leaves (0.30000000000000004). */
function tidy(value: number): number {
  return Number(value.toPrecision(12));
}

/**
 * A scale's range on a two-axis chart: exactly `divisions` steps of a round size, covering the
 * data, with any spare steps shared above and below it -- but never below zero for data that is
 * never negative, so rain and radiation stand on the axis. A direction axis is the compass.
 */
export function axisRange(
  unit: string,
  min: number | null,
  max: number | null,
  divisions: number,
): [number, number] {
  if (unit === "deg") return [0, 360];
  if (min === null || max === null || !Number.isFinite(min) || !Number.isFinite(max)) return [0, divisions];
  if (max - min < 1e-9) max = min + (Math.abs(min) || 1) / 10;
  const slack = 1e-9;
  let power = 10 ** Math.floor(Math.log10((max - min) / divisions));
  for (;;) {
    for (const nice of NICE_STEPS) {
      const step = nice * power;
      const low = Math.floor(min / step + slack);
      const high = Math.ceil(max / step - slack);
      const spare = divisions - (high - low);
      if (spare < 0) continue;
      const below = min >= 0 ? Math.min(Math.floor(spare / 2), low) : Math.floor(spare / 2);
      const start = (low - below) * step;
      return [tidy(start), tidy(start + divisions * step)];
    }
    power *= 10;
  }
}

/** The ticks of an aligned axis: its range cut into `divisions` equal steps. */
export function axisTicks(low: number, high: number, divisions: number): number[] {
  const step = (high - low) / divisions;
  return Array.from({ length: divisions + 1 }, (_, i) => tidy(low + i * step));
}
