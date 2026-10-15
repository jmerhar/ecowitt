<script lang="ts">
  /**
   * The wind: a compass showing where it comes from, its speed, gusts and the day's strongest --
   * at the standard 10 m where the station estimates it, with what its sensor measured below; or,
   * for a visitor who chose the sensor, the other way round.
   */
  import WindIcon from "@lucide/svelte/icons/wind";
  import type { Notice, Units, Wind } from "../lib/api";
  import { clock, hourOf, quantity } from "../lib/format";
  import type { WindHeight } from "../lib/prefs";
  import { intlLocale } from "../lib/language";
  import { m } from "../paraglide/messages.js";

  type Props = {
    notice?: Notice;
    wind: Wind;
    /** Which wind leads, where the station estimates one at 10 m. */
    height?: WindHeight;
    units: Units;
    symbols: Record<string, string>;
    timezone: string;
    onselect: (view: string) => void;
  };
  let { wind, height = "10m", units, symbols, timezone, onselect, notice }: Props = $props();

  /** Whether the figures shown are an estimate at 10 m rather than the measurement itself. */
  const estimated = $derived(wind.source === "model" || (wind.source !== null && wind.height_factor !== 1));
  const basis = $derived(
    wind.source === "model"
      ? m.wind_basis_model()
      : m.wind_basis_estimated({ factor: wind.height_factor.toLocaleString(intlLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }),
  );
  /** Whether the measured wind leads, with the estimate beneath it. */
  const fromSensor = $derived(estimated && height === "sensor");
  const lead = $derived(
    fromSensor
      ? {
          speed: wind.measured_speed,
          gust: wind.measured_gust,
          max: wind.measured_max_gust_today,
          beaufort: wind.measured_beaufort,
          description: wind.measured_description,
        }
      : {
          speed: wind.speed,
          gust: wind.gust,
          max: wind.max_gust_today,
          beaufort: wind.beaufort,
          description: wind.description,
        },
  );
</script>

<button class="card {notice?.level ?? ''}" onclick={() => onselect("wind")}>
  <h2><WindIcon size={16} aria-hidden="true" /> {m.wind_title()}</h2>
  {#if notice?.text}<p class="notice">{notice.text}</p>{/if}
  <div class="row">
    <svg viewBox="-50 -50 100 100" class="compass" role="img" aria-label={wind.compass ? m.wind_from({ compass: wind.compass }) : m.wind_direction_unknown()}>
      <circle r="44" class="ring" />
      {#each [[m.compass_n(), 0], [m.compass_e(), 90], [m.compass_s(), 180], [m.compass_w(), 270]] as [label, angle] (angle)}
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
      <div class="big">{quantity(lead.speed, units.wind, symbols)}</div>
      {#if fromSensor}
        <div class="basis" title={m.wind_sensor_hint()}>{m.wind_at_sensor()}</div>
      {:else if estimated}
        <div class="basis" title={basis}>{wind.source === "model" ? m.wind_at_10m_model() : m.wind_at_10m_estimated()}</div>
      {/if}
      <div class="muted">{wind.compass && lead.beaufort
          ? m.wind_description_from({ description: lead.description ?? "", compass: wind.compass })
          : (lead.description ?? "")}</div>
    </div>
  </div>
  <dl>
    <div><dt>{m.gusts()}</dt><dd>{quantity(lead.gust, units.wind, symbols)}</dd></div>
    {#if lead.max}
      <div>
        <dt>{m.strongest_today()}</dt>
        <dd>{m.value_at_time({
          value: quantity(lead.max.value, units.wind, symbols),
          time: clock(lead.max.time, timezone),
          hour: hourOf(lead.max.time, timezone),
        })}</dd>
      </div>
    {/if}
    {#if fromSensor}
      <div class="measured" title={basis}>
        <dt>{m.wind_at_10m()}</dt>
        <dd>{m.wind_with_gusts({ speed: quantity(wind.speed, units.wind, symbols), gust: quantity(wind.gust, units.wind, symbols) })}</dd>
      </div>
    {:else if estimated}
      <div class="measured" title={m.wind_sensor_hint()}>
        <dt>{m.wind_measured_here()}</dt>
        <dd>{m.wind_with_gusts({ speed: quantity(wind.measured_speed, units.wind, symbols), gust: quantity(wind.measured_gust, units.wind, symbols) })}</dd>
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
