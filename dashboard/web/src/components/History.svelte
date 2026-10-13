<script lang="ts">
  /**
   * The charts: a tab per subject, a range from a day to a year, fetched as either changes; and,
   * for a station with a weather model, the model's lines beside its own on request.
   */
  import type { Api, Meta, SeriesOut, UnitChoice } from "../lib/api";
  import { ApiError } from "../lib/api";
  import { align, VIEWS, viewFor } from "../lib/chart";
  import Chart from "./Chart.svelte";
  import { viewIcon } from "../lib/icons";
  import type { WeatherModel } from "../lib/api";

  type Props = {
    api: Api;
    meta: Meta;
    station: string;
    units: UnitChoice;
    timezone: string;
    /** Changes whenever the page refreshes, which fetches the answer again. */
    tick?: number;
    view: string;
    range: string;
    /** The station's weather model, or null when it has none. */
    weatherModel?: WeatherModel | null;
    /** Whether the model's lines are shown, where the chart has any. */
    model?: boolean;
  };
  let {
    api,
    meta,
    station,
    units,
    timezone,
    tick = 0,
    view = $bindable(),
    range = $bindable(),
    weatherModel = null,
    model = $bindable(false),
  }: Props = $props();

  const RANGES: Record<string, string> = {
    "1h": "1 h", "3h": "3 h", "6h": "6 h", "12h": "12 h",
    "24h": "Day", "7d": "Week", "30d": "Month", "1y": "Year",
  };

  let answer = $state<SeriesOut | null>(null);
  /** The view the answer was fetched for: another view's answer holds none of this one's. */
  let answered = $state("");
  let error = $state("");
  let loading = $state(false);

  const current = $derived(viewFor(view));
  const labels = $derived(Object.fromEntries(meta.metrics.map((m) => [m.id, m.label])));
  const modelled = $derived(new Set(meta.metrics.filter((m) => m.model).map((m) => m.id)));
  /** Whether this chart can show the model: the station has one, and it has one of the metrics. */
  const offersModel = $derived(
    weatherModel !== null && current.metrics.some((m) => modelled.has(m.id)),
  );
  const data = $derived(answer && answered === current.id ? align(current, answer, labels) : null);

  $effect(() => {
    const wanted = {
      tick, station, view: current, range, units: $state.snapshot(units), model: model && offersModel,
    };
    loading = true;
    let stale = false;
    api
      .series(
        wanted.station, wanted.view.metrics.map((m) => m.id), wanted.range, wanted.units, wanted.model,
      )
      .then((found) => {
        if (stale) return;
        answer = found;
        answered = wanted.view.id;
        error = "";
      })
      .catch((exc: unknown) => {
        if (stale) return;
        error = exc instanceof ApiError ? exc.message : "The chart could not be loaded.";
      })
      .finally(() => {
        if (!stale) loading = false;
      });
    return () => {
      stale = true;
    };
  });
</script>

<section class="card wide" id="history">
  <div class="toolbar">
    <div class="tabs" role="tablist" aria-label="Chart">
      {#each VIEWS as v (v.id)}
        {@const Icon = viewIcon(v.id)}
        <button role="tab" aria-selected={v.id === current.id} onclick={() => (view = v.id)}>
          <Icon size={14} aria-hidden="true" /> {v.label}</button>
      {/each}
    </div>
    <div class="controls">
      <!-- Hidden rather than absent on a chart the model does not cover, so that the range stays
           where it is when the chart changes. -->
      {#if weatherModel}
        <button
          class="toggle"
          aria-pressed={model}
          aria-hidden={!offersModel}
          disabled={!offersModel}
          style:visibility={offersModel ? null : "hidden"}
          title="The weather model's values for this location, dashed: {weatherModel.label}, from Open-Meteo"
          onclick={() => (model = !model)}>Model</button>
      {/if}
      <label>
        <span class="visually-hidden">Range</span>
        <select value={range} onchange={(e) => (range = e.currentTarget.value)}>
          {#each meta.ranges as r (r)}<option value={r}>{RANGES[r] ?? r}</option>{/each}
        </select>
      </label>
    </div>
  </div>
  {#if error}
    <p class="bad">{error}</p>
  {:else if data && data.lines.length}
    <div class:loading><Chart view={current} {data} symbols={meta.symbols} {timezone} /></div>
  {:else if data}
    <p class="muted">Nothing recorded for this in the chosen range.</p>
  {:else}
    <p class="muted">Loading…</p>
  {/if}
</section>

<style>
  .toolbar {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem 1rem;
    justify-content: space-between;
    margin-bottom: 0.75rem;
  }
  .loading {
    opacity: 0.6;
  }
  /* At the right, on the chart tabs' row or beneath it. */
  .controls {
    margin-left: auto;
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    align-items: center;
  }
  /* Dashed, like the lines it adds. */
  .toggle {
    font: inherit;
    font-size: 0.9rem;
    color: var(--muted);
    background: transparent;
    border: 1px dashed var(--line);
    border-radius: 0.3rem;
    padding: 0.15rem 0.55rem;
    cursor: pointer;
  }
  .toggle[aria-pressed="true"] {
    color: var(--fg);
    border-color: var(--muted);
    background: var(--bg);
  }
</style>
