<script lang="ts">
  /** One chart, drawn by uPlot from a view's aligned series; redrawn when they change. */
  import { onDestroy } from "svelte";
  import uPlot from "uplot";
  import "uplot/dist/uPlot.min.css";
  import type { ChartData, PlotSpec, View } from "../lib/chart";
  import { spec } from "../lib/chart";
  import { axisLabels, LOCALE, moment } from "../lib/format";

  type Props = {
    view: View;
    data: ChartData;
    symbols: Record<string, string>;
    timezone: string;
    height?: number;
  };
  let { view, data, symbols, timezone, height = 280 }: Props = $props();

  let element: HTMLDivElement;
  let plot: uPlot | undefined;
  let observer: ResizeObserver | undefined;

  function css(name: string): string {
    return getComputedStyle(element).getPropertyValue(name).trim() || "#888";
  }

  function draw(): void {
    plot?.destroy();
    const built = spec(view, data);
    const ink = css("--muted");
    const grid = css("--line");
    const axis = (scale: string, unit: string, side: number): uPlot.Axis => ({
      scale,
      side,
      stroke: ink,
      grid: { stroke: grid, show: side === 3 },
      ticks: { stroke: grid },
      values: (_: uPlot, ticks: number[]) =>
        ticks.map((v) => `${v.toLocaleString(LOCALE)}${symbols[unit] ? ` ${symbols[unit]}` : ""}`),
      size: 70,
    });
    const options: uPlot.Options = {
      width: element.clientWidth || 600,
      height,
      tzDate: (ts) => uPlot.tzDate(new Date(ts * 1000), timezone),
      scales: { x: { time: true } },
      axes: [
        {
          stroke: ink,
          grid: { stroke: grid },
          ticks: { stroke: grid },
          values: (_: uPlot, ticks: number[], _axis: number, _space: number, step: number) =>
            axisLabels(ticks, step, timezone),
        },
        ...built.axes.map((a) => axis(a.scale, a.unit, a.scale === "left" ? 3 : 1)),
      ],
      series: [
        // The legend's time row, day first with a 24-hour clock like the axis.
        { value: (_: uPlot, ts: number | null) => (ts === null ? "–" : moment(new Date(ts * 1000).toISOString(), timezone)) },
        ...built.series.map((s) => ({
          label: s.label,
          scale: s.scale,
          stroke: s.width ? s.stroke : s.style === "points" ? s.stroke : "transparent",
          width: s.width,
          fill: s.fill,
          dash: s.dash,
          // The model has a value every 15 minutes, so shorter buckets leave gaps between that
          // are not silences.
          spanGaps: Boolean(s.model),
          paths:
            s.style === "bars"
              ? uPlot.paths.bars!({ size: [0.6, 64] })
              : s.style === "points"
                ? () => null
                : undefined,
          // The model's points are hollow, so they stay apart from the station's in one colour.
          points: s.model
            ? { show: s.style === "points", size: 6, width: 1.5, stroke: s.stroke, fill: css("--card") }
            : { show: s.style === "points", size: 4, fill: s.stroke },
          value: (_: uPlot, v: number | null) =>
            v === null ? "–" : `${v.toLocaleString(LOCALE)}${symbols[s.unit] ? ` ${symbols[s.unit]}` : ""}`,
        })),
      ],
      bands: built.bands,
      // A click on a legend entry shows that line alone (again: all of them), and Cmd or Ctrl
      // with it hides or shows just that one: a tablet has no modifier key, and picking out one
      // room is the common case.
      legend: { live: true, isolate: true },
      hooks: { setSeries: [(u: uPlot) => followLines(u, built.series)] },
      cursor: { drag: { x: false, y: false } },
    };
    plot = new uPlot(options, built.data as uPlot.AlignedData, element);
    // A band's edges are drawn only as its fill; their legend rows would read "high: –".
    const rows = element.querySelectorAll<HTMLElement>(".u-legend .u-series");
    built.series.forEach((s, i) => {
      if (s.edge && rows[i + 1]) rows[i + 1].style.display = "none";
    });
  }

  /**
   * Show a band's edges exactly when its line is shown. They are series of their own, so a
   * legend click that picks out the line would otherwise hide its band.
   */
  function followLines(u: uPlot, series: PlotSpec["series"]): void {
    series.forEach((s, i) => {
      if (!s.edge) return;
      const line = series.findIndex((t, j) => j > i && !t.edge);
      const show = u.series[line + 1].show;
      if (u.series[i + 1].show !== show) u.setSeries(i + 1, { show }, false);
    });
  }

  $effect(() => {
    // Read every input so the chart redraws when any of them changes.
    void [view, data, symbols, timezone, height];
    draw();
  });

  $effect(() => {
    observer = new ResizeObserver(() => plot?.setSize({ width: element.clientWidth, height }));
    observer.observe(element);
    return () => observer?.disconnect();
  });

  onDestroy(() => plot?.destroy());
</script>

<div class="chart" bind:this={element}></div>

<style>
  .chart {
    width: 100%;
    min-height: 2rem;
  }
  .chart :global(.u-legend) {
    font-size: 0.85rem;
    color: var(--fg);
  }
</style>
