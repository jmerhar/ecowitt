<script lang="ts">
  /** The visitor's units, one choice per quantity; "station" leaves a quantity as stored. */
  import type { Meta, UnitChoice, Units } from "../lib/api";

  type Props = { meta: Meta; chosen: UnitChoice; onchange: (units: UnitChoice) => void };
  let { meta, chosen, onchange }: Props = $props();

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
  }
</style>
