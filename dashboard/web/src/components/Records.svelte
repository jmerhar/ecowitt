<script lang="ts">
  /** The lowest and highest of each metric today, this month or this year, with when. */
  import type { Api, ExtremesOut, Meta, UnitChoice } from "../lib/api";
  import { ApiError } from "../lib/api";
  import { moment, quantity } from "../lib/format";

  type Props = {
    api: Api;
    meta: Meta;
    station: string;
    units: UnitChoice;
    timezone: string;
    period: string;
  };
  let { api, meta, station, units, timezone, period = $bindable() }: Props = $props();

  const PERIODS: Record<string, string> = { today: "Today", month: "This month", year: "This year" };

  let answer = $state<ExtremesOut | null>(null);
  let error = $state("");

  const labels = $derived(Object.fromEntries(meta.metrics.map((m) => [m.id, m.label])));
  /** Rows worth showing: a rain record of nothing says nothing. */
  const rows = $derived(
    (answer?.extremes ?? []).filter(
      (e) => !(e.metric.startsWith("rain.") && (e.max?.value ?? 0) === 0),
    ),
  );

  $effect(() => {
    const wanted = { station, period, units: $state.snapshot(units) };
    let stale = false;
    api
      .extremes(wanted.station, wanted.period, wanted.units)
      .then((found) => {
        if (!stale) [answer, error] = [found, ""];
      })
      .catch((exc: unknown) => {
        if (!stale) error = exc instanceof ApiError ? exc.message : "The records could not be loaded.";
      });
    return () => {
      stale = true;
    };
  });

  function title(metric: string, name: string | null): string {
    const label = labels[metric] ?? metric;
    return metric.startsWith("rooms.") && name ? `${name} · ${label.toLowerCase()}` : label;
  }
</script>

<section class="card wide">
  <div class="toolbar">
    <h2>Records</h2>
    <div class="tabs" role="tablist" aria-label="Period">
      {#each meta.periods as p (p)}
        <button role="tab" aria-selected={p === period} onclick={() => (period = p)}>{PERIODS[p] ?? p}</button>
      {/each}
    </div>
  </div>
  {#if error}
    <p class="bad">{error}</p>
  {:else if answer}
    <div class="table-wrap">
      <table>
        <thead><tr><th></th><th class="num">Lowest</th><th class="num">Highest</th></tr></thead>
        <tbody>
          {#each rows as row (`${row.metric}/${row.sensor}`)}
            <tr>
              <td>{title(row.metric, row.name)}</td>
              <td class="num">
                {#if row.min}{quantity(row.min.value, row.unit, meta.symbols)}
                  <span class="when">{moment(row.min.time, timezone)}</span>{/if}
              </td>
              <td class="num">
                {#if row.max}{quantity(row.max.value, row.unit, meta.symbols)}
                  <span class="when">{moment(row.max.time, timezone)}</span>{/if}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
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
    align-items: baseline;
  }
  .when {
    display: block;
    color: var(--muted);
    font-size: 0.8rem;
  }
</style>
