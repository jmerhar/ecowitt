<script lang="ts">
  /**
   * The visitor's units, one choice per quantity; "station" leaves a quantity as stored. And, for
   * a station whose wind is estimated at 10 m, whether the page leads with that or the measurement.
   */
  import type { Meta, UnitChoice, Units } from "../lib/api";
  import type { WindHeight } from "../lib/prefs";

  type Props = {
    meta: Meta;
    chosen: UnitChoice;
    onchange: (units: UnitChoice) => void;
    /** Which wind the page leads with; null hides the choice, for a station without an estimate. */
    wind?: WindHeight | null;
    onwind?: (wind: WindHeight) => void;
  };
  let { meta, chosen, onchange, wind = null, onwind = () => {} }: Props = $props();

  const LABELS: Record<string, string> = {
    temperature: "Temperature",
    pressure: "Pressure",
    wind: "Wind",
    rain: "Rain",
  };

  function choose(quantity: string, code: string): void {
    const next: UnitChoice = { ...chosen };
    if (code) next[quantity as keyof Units] = code;
    else delete next[quantity as keyof Units];
    onchange(next);
  }
</script>

<details class="menu">
  <summary>Units</summary>
  <div class="panel">
    {#each Object.keys(LABELS) as quantity (quantity)}
      <label>
        {LABELS[quantity]}
        <select
          value={chosen[quantity as keyof Units] ?? ""}
          onchange={(e) => choose(quantity, e.currentTarget.value)}>
          <option value="">As stored</option>
          {#each meta.units[quantity] ?? [] as unit (unit.code)}
            <option value={unit.code}>{unit.symbol}</option>
          {/each}
        </select>
      </label>
    {/each}
    {#if wind}
      <label>
        Wind at
        <select value={wind} onchange={(e) => onwind(e.currentTarget.value as WindHeight)}>
          <option value="10m">10 m, estimated</option>
          <option value="sensor">The sensor</option>
        </select>
      </label>
    {/if}
  </div>
</details>

<style>
  .menu {
    position: relative;
  }
  summary {
    cursor: pointer;
    border: 1px solid var(--line);
    border-radius: 0.3rem;
    padding: 0.2rem 0.6rem;
    list-style: none;
  }
  .panel {
    position: absolute;
    right: 0;
    top: 2.2rem;
    z-index: 2;
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 0.4rem;
    padding: 0.75rem;
    display: grid;
    gap: 0.5rem;
    min-width: 13rem;
  }
  label {
    display: flex;
    justify-content: space-between;
    gap: 0.75rem;
    align-items: center;
    color: var(--fg);
    white-space: nowrap;
  }
</style>
