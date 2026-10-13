<script lang="ts">
  /**
   * The wind: a compass showing where it comes from, its speed, gusts and the day's strongest --
   * at the standard 10 m where the station estimates it, with what its sensor measured below.
   */
  import WindIcon from "@lucide/svelte/icons/wind";
  import type { Notice, Units, Wind } from "../lib/api";
  import { clock, quantity } from "../lib/format";

  type Props = {
    notice?: Notice;
    wind: Wind;
    units: Units;
    symbols: Record<string, string>;
    timezone: string;
    onselect: (view: string) => void;
  };
  let { wind, units, symbols, timezone, onselect, notice }: Props = $props();

  /** Whether the figures shown are an estimate at 10 m rather than the measurement itself. */
  const estimated = $derived(wind.source === "model" || (wind.source !== null && wind.height_factor !== 1));
  const basis = $derived(
    wind.source === "model"
      ? "At 10 m, from the weather model: too light here for the sensor to turn"
      : `Estimated at 10 m: ×${wind.height_factor.toFixed(2)} the wind measured at the sensor`,
  );
</script>

<button class="card {notice?.level ?? ''}" onclick={() => onselect("wind")}>
  <h2><WindIcon size={16} aria-hidden="true" /> Wind</h2>
  {#if notice?.text}<p class="notice">{notice.text}</p>{/if}
  <div class="row">
    <svg viewBox="-50 -50 100 100" class="compass" role="img" aria-label={wind.compass ? `From the ${wind.compass}` : "Direction unknown"}>
      <circle r="44" class="ring" />
      {#each [["N", 0], ["E", 90], ["S", 180], ["W", 270]] as [label, angle] (label)}
        <text
          x={Math.sin((Number(angle) * Math.PI) / 180) * 34}
          y={-Math.cos((Number(angle) * Math.PI) / 180) * 34}
          dominant-baseline="central"
          text-anchor="middle">{label}</text>
      {/each}
      {#if wind.direction !== null}
        <!-- The arrow points the way the wind blows, from the side it comes from. -->
        <g transform="rotate({wind.direction})">
          <path d="M0 -26 L7 6 L0 0 L-7 6 Z" transform="rotate(180)" class="arrow" />
        </g>
      {/if}
    </svg>
    <div>
      <div class="big">{quantity(wind.speed, units.wind, symbols)}</div>
      {#if estimated}<div class="basis" title={basis}>{wind.source === "model" ? "at 10 m, from the model" : "at 10 m, estimated"}</div>{/if}
      <div class="muted">{wind.description ?? ""}{wind.compass && wind.beaufort ? ` from the ${wind.compass}` : ""}</div>
    </div>
  </div>
  <dl>
    <div><dt>Gusts</dt><dd>{quantity(wind.gust, units.wind, symbols)}</dd></div>
    {#if wind.max_gust_today}
      <div>
        <dt>Strongest today</dt>
        <dd>{quantity(wind.max_gust_today.value, units.wind, symbols)} at {clock(wind.max_gust_today.time, timezone)}</dd>
      </div>
    {/if}
    {#if estimated}
      <div class="measured" title="What the anemometer read, at its own height">
        <dt>Measured here</dt>
        <dd>{quantity(wind.measured_speed, units.wind, symbols)}, gusts {quantity(wind.measured_gust, units.wind, symbols)}</dd>
      </div>
    {/if}
  </dl>
</button>

<style>
  .row {
    display: flex;
    gap: 1rem;
    align-items: center;
  }
  .compass {
    width: 6rem;
    height: 6rem;
    flex: none;
  }
  .ring {
    fill: none;
    stroke: var(--line);
    stroke-width: 2;
  }
  text {
    font-size: 11px;
    fill: var(--muted);
  }
  .arrow {
    fill: var(--accent);
  }
  .basis {
    color: var(--muted);
    font-size: 0.8rem;
  }
  .measured {
    font-size: 0.85rem;
    color: var(--muted);
  }
  .measured dd {
    color: var(--muted);
  }
</style>
