/**
 * The charts: which metrics each tab shows, and how the API's bucketed series become the
 * aligned columns uPlot draws. Kept apart from the component so it can be tested without a
 * canvas.
 */

import type { Series, SeriesOut } from "./api";

/** How one metric is drawn. */
export type Style = "line" | "band" | "points" | "bars" | "thin";

/** A chart tab: its metrics, how each is drawn, and on which axis. */
export type View = {
  id: string;
  label: string;
  metrics: { id: string; style: Style; axis: "left" | "right" }[];
};

export const VIEWS: View[] = [
  {
    id: "temperature",
    label: "Temperature",
    metrics: [
      { id: "outdoor.temperature", style: "band", axis: "left" },
      { id: "outdoor.dew_point", style: "line", axis: "left" },
    ],
  },
  {
    id: "humidity",
    label: "Humidity",
    metrics: [{ id: "outdoor.humidity", style: "band", axis: "left" }],
  },
  {
    id: "wind",
    label: "Wind",
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
    label: "Rain",
    metrics: [
      { id: "rain.daily", style: "bars", axis: "left" },
      { id: "rain.rate", style: "line", axis: "right" },
    ],
  },
  {
    id: "pressure",
    label: "Pressure",
    metrics: [{ id: "pressure.sea_level", style: "band", axis: "left" }],
  },
  {
    id: "sun",
    label: "Sun",
    metrics: [
      { id: "solar.radiation", style: "line", axis: "left" },
      { id: "solar.uv_index", style: "line", axis: "right" },
    ],
  },
  {
    id: "rooms-temperature",
    label: "Rooms °",
    metrics: [{ id: "rooms.temperature", style: "line", axis: "left" }],
  },
  {
    id: "rooms-humidity",
    label: "Rooms %",
    metrics: [{ id: "rooms.humidity", style: "line", axis: "left" }],
  },
];

/** The tab a section of the page drills down to when clicked. */
export function viewFor(id: string): View {
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
  const wanted = new Map(view.metrics.map((m) => [m.id, m]));
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
    measured.map((s) => s.metric).filter((m, i, all) => all.indexOf(m) !== i),
  );
  const lines = measured.map((series) => {
    const how = wanted.get(series.metric)!;
    const index = counts.get(series.metric) ?? 0;
    counts.set(series.metric, index + 1);
    const metricLabel = labels[series.metric] ?? series.metric;
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
      label: `${labels[series.metric] ?? series.metric} (model)`,
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
  const metricIndex = Math.max(0, view.metrics.findIndex((m) => m.id === line.metric));
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
