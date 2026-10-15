<script lang="ts">
  /** Sea-level pressure and where it has been heading for three hours. */
  import GaugeIcon from "@lucide/svelte/icons/gauge";
  import type { Notice, Pressure, Units } from "../lib/api";
  import { quantity } from "../lib/format";
  import { intlLocale } from "../lib/language";
  import { m } from "../paraglide/messages.js";

  type Props = {
    notice?: Notice;
    pressure: Pressure;
    units: Units;
    symbols: Record<string, string>;
    onselect: (view: string) => void;
  };
  let { pressure, units, symbols, onselect, notice }: Props = $props();

  const trend = $derived(pressure.trend);
  const arrow = $derived(
    !trend || trend.code === "steady" ? "→" : trend.change > 0 ? "↗" : "↘",
  );
</script>

<button class="card {notice?.level ?? ''}" onclick={() => onselect("pressure")}>
  <h2><GaugeIcon size={16} aria-hidden="true" /> {m.pressure_title()}</h2>
  {#if notice?.text}<p class="notice">{notice.text}</p>{/if}
  <div class="big">{quantity(pressure.sea_level ?? pressure.relative, units.pressure, symbols)}</div>
  {#if trend}
    <div class="muted">
      <span aria-hidden="true">{arrow}</span>
      <span class="tendency">{trend.tendency}</span>:
      {m.pressure_change({
        change: `${trend.change > 0 ? "+" : ""}${quantity(trend.change, units.pressure, symbols)}`,
        hours: trend.hours.toLocaleString(intlLocale()),
      })}
    </div>
  {/if}
  <dl>
    <div><dt>{m.at_the_station()}</dt><dd>{quantity(pressure.absolute, units.pressure, symbols)}</dd></div>
  </dl>
</button>

<style>
  /* The tendency starts the line: capitalised by the browser, by its language's rules. */
  .tendency {
    display: inline-block;
  }
  .tendency::first-letter {
    text-transform: uppercase;
  }
</style>
