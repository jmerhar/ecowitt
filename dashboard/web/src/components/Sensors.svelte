<script lang="ts">
  /** Whether each sensor is reporting and how its battery is; folded away unless something is wrong. */
  import type { SensorHealth } from "../lib/api";
  import { duration } from "../lib/format";

  let { sensors }: { sensors: SensorHealth[] } = $props();

  const problems = $derived(sensors.filter((s) => s.battery_low || !s.updating));
</script>

<details class="card wide" open={problems.length > 0}>
  <summary>
    <h2>Sensors</h2>
    <span class:bad={problems.length > 0} class="muted">
      {problems.length ? `${problems.length} need${problems.length === 1 ? "s" : ""} attention` : "All reporting"}
    </span>
  </summary>
  <ul>
    {#each sensors as sensor (sensor.sensor)}
      <li>
        <span>{sensor.name}</span>
        <span class="muted">
          {#if !sensor.updating}<span class="bad">Not updating for {duration(sensor.unchanged_s)}</span>
          {:else}Reporting{/if}
          {#if sensor.battery_low}· <span class="bad">Battery low</span>{/if}
        </span>
      </li>
    {/each}
  </ul>
</details>

<style>
  summary {
    display: flex;
    gap: 1rem;
    align-items: baseline;
    cursor: pointer;
    list-style: none;
  }
  summary h2 {
    margin: 0;
  }
  ul {
    list-style: none;
    padding: 0;
    margin: 0.75rem 0 0;
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(14rem, 1fr));
    gap: 0.35rem 1.5rem;
  }
  li {
    display: flex;
    justify-content: space-between;
    gap: 0.5rem;
  }
</style>
