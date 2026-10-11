<script lang="ts">
  /** One chart, drawn by uPlot from a view's aligned series; redrawn when they change. */
  import { onDestroy } from "svelte";
  import uPlot from "uplot";
  import "uplot/dist/uPlot.min.css";
  import type { ChartData, View } from "../lib/chart";
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
          spanGaps: false,
          paths:
            s.style === "bars"
              ? uPlot.paths.bars!({ size: [0.6, 64] })
              : s.style === "points"
                ? () => null
                : undefined,
          points: { show: s.style === "points", size: 4, fill: s.stroke },
          value: (_: uPlot, v: number | null) =>
            v === null ? "–" : `${v.toLocaleString(LOCALE)}${symbols[s.unit] ? ` ${symbols[s.unit]}` : ""}`,
        })),
      ],
      bands: built.bands,
      legend: { live: true },
      cursor: { drag: { x: false, y: false } },
    };
    plot = new uPlot(options, built.data as uPlot.AlignedData, element);
    // A band's edges are drawn only as its fill; their legend rows would read "high: –".
    const rows = element.querySelectorAll<HTMLElement>(".u-legend .u-series");
    built.series.forEach((s, i) => {
      if (s.edge && rows[i + 1]) rows[i + 1].style.display = "none";
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
