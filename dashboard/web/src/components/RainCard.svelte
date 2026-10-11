<script lang="ts">
  /** Rain: whether it is raining now, and the console's running totals. */
  import CloudRainIcon from "@lucide/svelte/icons/cloud-rain";
  import type { Notice, Rain, Units } from "../lib/api";
  import { quantity } from "../lib/format";

  type Props = {
    notice?: Notice;
    rain: Rain;
    units: Units;
    symbols: Record<string, string>;
    onselect: (view: string) => void;
  };
  let { rain, units, symbols, onselect, notice }: Props = $props();

  const rate = $derived(units.rain === "in" ? "in_h" : "mm_h");
</script>

<button class="card {notice?.level ?? ''}" onclick={() => onselect("rain")}>
  <h2><CloudRainIcon size={16} aria-hidden="true" /> Rain</h2>
  {#if notice?.text}<p class="notice">{notice.text}</p>{/if}
  {#if rain.raining}
    <div class="big">{quantity(rain.rate, rate, symbols)}</div>
    <div class="muted">Raining now</div>
  {:else}
    <div class="big">{quantity(rain.daily, units.rain, symbols)}</div>
    <div class="muted">today, not raining now</div>
  {/if}
  <dl>
    {#if rain.raining}<div><dt>Today</dt><dd>{quantity(rain.daily, units.rain, symbols)}</dd></div>{/if}
    <div><dt>Last 24 hours</dt><dd>{quantity(rain.last_24h, units.rain, symbols)}</dd></div>
    <div><dt>This month</dt><dd>{quantity(rain.monthly, units.rain, symbols)}</dd></div>
    <div><dt>This year</dt><dd>{quantity(rain.yearly, units.rain, symbols)}</dd></div>
  </dl>
</button>
