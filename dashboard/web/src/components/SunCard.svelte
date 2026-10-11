<script lang="ts">
  /** Today's daylight at the station, and the light and UV now. */
  import SunIcon from "@lucide/svelte/icons/sun";
  import SunriseIcon from "@lucide/svelte/icons/sunrise";
  import SunsetIcon from "@lucide/svelte/icons/sunset";
  import type { Notice, Sun } from "../lib/api";
  import { clock, duration, quantity, uvRisk } from "../lib/format";

  type Props = {
    notice?: Notice;
    sun: Sun;
    symbols: Record<string, string>;
    timezone: string;
    onselect: (view: string) => void;
  };
  let { sun, symbols, timezone, onselect, notice }: Props = $props();
</script>

<button class="card {notice?.level ?? ''}" onclick={() => onselect("sun")}>
  <h2><SunIcon size={16} aria-hidden="true" /> Sun</h2>
  {#if notice?.text}<p class="notice">{notice.text}</p>{/if}
  {#if sun.polar === "day"}
    <div class="big">Up all day</div>
  {:else if sun.polar === "night"}
    <div class="big">Down all day</div>
  {:else if sun.sunrise}
    <div class="big times">
      <span title="Sunrise"><SunriseIcon size={22} aria-label="Sunrise" /> {clock(sun.sunrise, timezone)}</span>
      <span title="Sunset"><SunsetIcon size={22} aria-label="Sunset" /> {clock(sun.sunset, timezone)}</span>
    </div>
    <div class="muted">{duration(sun.daylight_s)} of daylight</div>
  {/if}
  <dl>
    <div><dt>Radiation</dt><dd>{quantity(sun.radiation, "wm2", symbols)}</dd></div>
    {#if sun.uv_index !== null}
      <div><dt>UV index</dt><dd>{quantity(sun.uv_index, "", symbols)} {uvRisk(sun.uv_index)}</dd></div>
    {/if}
  </dl>
</button>

<style>
  .times {
    display: flex;
    flex-wrap: wrap;
    gap: 0.2rem 1rem;
  }
  .times span {
    display: inline-flex;
    gap: 0.35rem;
    align-items: center;
  }
</style>
