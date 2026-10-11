<script lang="ts">
  /**
   * The lowest and highest of each metric today, this month or this year: a tile per outdoor
   * metric, and the rooms folded beneath, a tile each.
   */
  import type { Api, Extreme, ExtremesOut, Meta, UnitChoice } from "../lib/api";
  import { ApiError } from "../lib/api";
  import { clock, moment, quantity } from "../lib/format";
  import { metricIcon } from "../lib/icons";
  import ArrowUpDownIcon from "@lucide/svelte/icons/arrow-up-down";
  import HouseIcon from "@lucide/svelte/icons/house";

  type Props = {
    api: Api;
    meta: Meta;
    station: string;
    units: UnitChoice;
    timezone: string;
    /** Changes whenever the page refreshes, which fetches the answer again. */
    tick?: number;
    period: string;
  };
  let { api, meta, station, units, timezone, tick = 0, period = $bindable() }: Props = $props();

  const PERIODS: Record<string, string> = { today: "Today", month: "This month", year: "This year" };

  let answer = $state<ExtremesOut | null>(null);
  let error = $state("");

  const labels = $derived(Object.fromEntries(meta.metrics.map((m) => [m.id, m.label])));
  /**
   * The outdoor and station-wide records. A record that is only a highest and is zero -- no
   * rain, no sun at night -- says nothing.
   */
  const outdoor = $derived(
    (answer?.extremes ?? []).filter(
      (e) => !e.metric.startsWith("rooms.") && !(e.min === null && (e.max?.value ?? 0) === 0),
    ),
  );
  /** One row per room: its temperature and humidity ranges. */
  const rooms = $derived.by(() => {
    const byRoom = new Map<string, { name: string; temperature?: Extreme; humidity?: Extreme }>();
    for (const e of answer?.extremes ?? []) {
      const kind = e.metric === "rooms.temperature" ? "temperature" : e.metric === "rooms.humidity" ? "humidity" : null;
      if (!kind || !e.sensor) continue;
      const row = byRoom.get(e.sensor) ?? { name: e.name ?? e.sensor };
      row[kind] = e;
      byRoom.set(e.sensor, row);
    }
    return [...byRoom.values()];
  });

  $effect(() => {
    const wanted = { tick, station, period, units: $state.snapshot(units) };
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

  /** When a record was set: the time of day for today's, the date and time otherwise. */
  function when(iso: string): string {
    return period === "today" ? clock(iso, timezone) : moment(iso, timezone);
  }
</script>

{#snippet sides(record: Extreme)}
  {@const Icon = metricIcon(record.metric)}
  {#if record.min}
    <dt><Icon size={13} aria-hidden="true" /> Low</dt>
    <dd class="value">{quantity(record.min.value, record.unit, meta.symbols)}</dd>
    <dd class="when">{when(record.min.time)}</dd>
  {/if}
  {#if record.max}
    <dt><Icon size={13} aria-hidden="true" /> High</dt>
    <dd class="value">{quantity(record.max.value, record.unit, meta.symbols)}</dd>
    <dd class="when">{when(record.max.time)}</dd>
  {/if}
{/snippet}

<section class="card wide">
  <div class="toolbar">
    <h2><ArrowUpDownIcon size={16} aria-hidden="true" /> Highs and lows</h2>
    <div class="tabs" role="tablist" aria-label="Period">
      {#each meta.periods as p (p)}
        <button role="tab" aria-selected={p === period} onclick={() => (period = p)}>{PERIODS[p] ?? p}</button>
      {/each}
    </div>
  </div>
  {#if error}
    <p class="bad">{error}</p>
  {:else if answer}
    <div class="tiles">
      {#each outdoor as record (`${record.metric}/${record.sensor}`)}
        {@const Icon = metricIcon(record.metric)}
        <div class="tile">
          <div class="label"><Icon size={14} aria-hidden="true" /> {labels[record.metric] ?? record.metric}</div>
          <dl>
            {#if record.min}
              <dt>Low</dt>
              <dd class="value">{quantity(record.min.value, record.unit, meta.symbols)}</dd>
              <dd class="when">{when(record.min.time)}</dd>
            {/if}
            {#if record.max}
              <dt>High</dt>
              <dd class="value">{quantity(record.max.value, record.unit, meta.symbols)}</dd>
              <dd class="when">{when(record.max.time)}</dd>
            {/if}
          </dl>
        </div>
      {/each}
    </div>
    {#if rooms.length}
      <details class="rooms">
        <summary><HouseIcon size={14} aria-hidden="true" /> Rooms</summary>
        <div class="tiles">
          {#each rooms as room (room.name)}
            <div class="tile">
              <div class="label">{room.name}</div>
              <dl>
                {#if room.temperature}{@render sides(room.temperature)}{/if}
                {#if room.humidity}{@render sides(room.humidity)}{/if}
              </dl>
            </div>
          {/each}
        </div>
      </details>
    {/if}
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
    margin-bottom: 0.5rem;
  }
  .tiles {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(16rem, 1fr));
    gap: 0.75rem;
  }
  .tile {
    border: 1px solid var(--line);
    border-radius: 0.4rem;
    padding: 0.6rem 0.8rem;
    font-variant-numeric: tabular-nums;
  }
  .label {
    display: flex;
    gap: 0.35rem;
    align-items: center;
    color: var(--muted);
    font-size: 0.85rem;
    margin-bottom: 0.2rem;
  }
  /* Label, value and when on one line each, in columns that line up down the tile. */
  dl {
    display: grid;
    grid-template-columns: auto auto 1fr;
    gap: 0.15rem 0.6rem;
    margin: 0;
    align-items: baseline;
  }
  dt {
    display: flex;
    gap: 0.25rem;
    align-items: center;
    color: var(--muted);
  }
  .value {
    font-weight: 600;
    text-align: left;
    white-space: nowrap;
  }
  .when {
    color: var(--muted);
    font-size: 0.85rem;
    white-space: nowrap;
  }
  .rooms {
    margin-top: 1rem;
  }
  /* Still a list item, so it keeps its disclosure triangle; the icon sits on the text line. */
  .rooms summary :global(svg) {
    vertical-align: -2px;
  }
  .rooms summary {
    cursor: pointer;
    color: var(--muted);
    margin-bottom: 0.75rem;
  }
</style>
