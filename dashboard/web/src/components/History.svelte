<script lang="ts">
  /** The charts: a tab per subject, a range from a day to a year, fetched as either changes. */
  import type { Api, Meta, SeriesOut, UnitChoice } from "../lib/api";
  import { ApiError } from "../lib/api";
  import { align, VIEWS, viewFor } from "../lib/chart";
  import Chart from "./Chart.svelte";

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
  }: Props = $props();

  const RANGES: Record<string, string> = { "24h": "Day", "7d": "Week", "30d": "Month", "1y": "Year" };

  let answer = $state<SeriesOut | null>(null);
  /** The view the answer was fetched for: another view's answer holds none of this one's. */
  let answered = $state("");
  let error = $state("");
  let loading = $state(false);

  const current = $derived(viewFor(view));
  const labels = $derived(Object.fromEntries(meta.metrics.map((m) => [m.id, m.label])));
  const data = $derived(answer && answered === current.id ? align(current, answer, labels) : null);

  $effect(() => {
    const wanted = { tick, station, view: current, range, units: $state.snapshot(units) };
    loading = true;
    let stale = false;
    api
      .series(wanted.station, wanted.view.metrics.map((m) => m.id), wanted.range, wanted.units)
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
        <button role="tab" aria-selected={v.id === current.id} onclick={() => (view = v.id)}>{v.label}</button>
      {/each}
    </div>
    <div class="tabs" role="tablist" aria-label="Range">
      {#each meta.ranges as r (r)}
        <button role="tab" aria-selected={r === range} onclick={() => (range = r)}>{RANGES[r] ?? r}</button>
      {/each}
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
</style>
