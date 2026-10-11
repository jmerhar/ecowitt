<script lang="ts">
  /** Today's daylight at the station, and the light and UV now. */
  import type { Sun } from "../lib/api";
  import { clock, duration, quantity, uvRisk } from "../lib/format";

  type Props = {
    sun: Sun;
    symbols: Record<string, string>;
    timezone: string;
    onselect: (view: string) => void;
  };
  let { sun, symbols, timezone, onselect }: Props = $props();
</script>

<button class="card" onclick={() => onselect("sun")}>
  <h2>Sun</h2>
  {#if sun.polar === "day"}
    <div class="big">Up all day</div>
  {:else if sun.polar === "night"}
    <div class="big">Down all day</div>
  {:else if sun.sunrise}
    <div class="big">↑ {clock(sun.sunrise, timezone)} ↓ {clock(sun.sunset, timezone)}</div>
    <div class="muted">{duration(sun.daylight_s)} of daylight</div>
  {/if}
  <dl>
    <div><dt>Radiation</dt><dd>{quantity(sun.radiation, "wm2", symbols)}</dd></div>
    {#if sun.uv_index !== null}
      <div><dt>UV index</dt><dd>{quantity(sun.uv_index, "", symbols)} {uvRisk(sun.uv_index)}</dd></div>
    {/if}
  </dl>
</button>
