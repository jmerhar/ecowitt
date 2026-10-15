<script lang="ts">
  /**
   * The weather forecast from the station's model: the next 24 hours as a strip to scroll, and
   * the days ahead as a table. Fetched again on every refresh; absent for a station without a
   * model or a forecast recent enough to show.
   */
  import CalendarDaysIcon from "@lucide/svelte/icons/calendar-days";
  import DropletsIcon from "@lucide/svelte/icons/droplets";
  import UmbrellaIcon from "@lucide/svelte/icons/umbrella";
  import { untrack } from "svelte";
  import type { Api, ForecastOut, UnitChoice } from "../lib/api";
  import { ApiError } from "../lib/api";
  import { clock, dayLabel, quantity, whole } from "../lib/format";
  import { skyIcon } from "../lib/sky";

  type Props = {
    api: Api;
    station: string;
    units: UnitChoice;
    timezone: string;
    symbols: Record<string, string>;
    /** Changes whenever the page refreshes, which fetches the forecast again. */
    tick?: number;
  };
  let { api, station, units, timezone, symbols, tick = 0 }: Props = $props();

  let answer = $state<ForecastOut | null>(null);
  let error = $state("");

  $effect(() => {
    const wanted = { tick, station, units: $state.snapshot(units) };
    // Another station's forecast is not shown while this one's loads.
    if (untrack(() => answer?.station) !== wanted.station) answer = null;
    let stale = false;
    api
      .forecast(wanted.station, wanted.units)
      .then((found) => {
        if (stale) return;
        answer = found;
        error = "";
      })
      .catch((exc: unknown) => {
        // A refresh that fails keeps the forecast already shown.
        if (stale) return;
        error = exc instanceof ApiError ? exc.message : "The forecast could not be loaded.";
      });
    return () => {
      stale = true;
    };
  });

  const t = $derived(answer?.units.temperature ?? "c");
  const w = $derived(answer?.units.wind ?? "kmh");
  const r = $derived(answer?.units.rain ?? "mm");
  /** A chance of rain worth showing: anything from one in ten. */
  const wet = (pct: number | null) => pct !== null && pct >= 10;
</script>

{#if answer?.issued}
  <section class="card wide forecast">
    <h2>
      <CalendarDaysIcon size={16} aria-hidden="true" /> Forecast
      <span class="source">{answer.model?.label ?? "Weather model"}, made {clock(answer.issued, timezone)}</span>
    </h2>

    <div class="hours" role="list" aria-label="The next 24 hours">
      {#each answer.hours as h (h.time)}
        <div class="hour" role="listitem">
          <span class="time">{clock(h.time, timezone)}</span>
          {#if h.weather_code !== null}
            <img src={skyIcon(h.weather_code, h.is_day)} alt={h.description ?? ""} title={h.description ?? ""} width="40" height="40" />
          {/if}
          <span class="temp">{whole(h.temperature, t, symbols)}</span>
          <span class="humidity" title="Humidity">
            <DropletsIcon size={11} aria-hidden="true" />{quantity(h.humidity, "pct", symbols)}
          </span>
          <!-- A model without a chance of rain still has its amount. -->
          {#if h.precipitation_probability === null && h.precipitation !== null}
            <span class="rain" class:dry={h.precipitation === 0} title="Rain">
              <UmbrellaIcon size={11} aria-hidden="true" />{quantity(h.precipitation, r, symbols)}
            </span>
          {:else}
            <span class="rain" class:dry={!wet(h.precipitation_probability)} title="Chance of rain">
              <UmbrellaIcon size={11} aria-hidden="true" />{quantity(h.precipitation_probability, "pct", symbols)}
            </span>
          {/if}
          <span class="wind" title="Wind, gusts {whole(h.wind_gust, w, symbols)}">
            <span>{whole(h.wind_speed, w, symbols)}</span>
            <span>{h.compass ?? ""}</span>
          </span>
        </div>
      {/each}
    </div>

    <div class="table-wrap">
      <table class="days">
        <thead>
          <tr>
            <th>Day</th><th><span class="visually-hidden">Sky</span></th>
            <th class="num">Low</th><th class="num">High</th>
            <th class="num">Rain</th><th class="num">
              <span class="wide-only">Humidity</span>
              <span class="narrow-only" title="Humidity">
                <DropletsIcon size={14} aria-hidden="true" /><span class="visually-hidden">Humidity</span>
              </span>
            </th><th class="num wide-only">Gusts</th>
          </tr>
        </thead>
        <tbody>
          {#each answer.days as d (d.date)}
            <tr>
              <td>{dayLabel(d.date, timezone)}</td>
              <td>
                {#if d.weather_code !== null}
                  <div class="sky">
                    <img src={skyIcon(d.weather_code, true)} alt={d.description ?? ""} width="32" height="32" />
                    <span class="wide-only" aria-hidden="true">{d.description}</span>
                  </div>
                {/if}
              </td>
              <td class="num muted">{whole(d.temperature_min, t, symbols)}</td>
              <td class="num">{whole(d.temperature_max, t, symbols)}</td>
              <td class="num" class:muted={!wet(d.precipitation_probability)}>
                {quantity(d.precipitation, r, symbols)}{#if wet(d.precipitation_probability)}{" "}<span class="chance">{quantity(d.precipitation_probability, "pct", symbols)}</span>{/if}
              </td>
              <td class="num">{quantity(d.humidity, "pct", symbols)}</td>
              <td class="num wide-only">{whole(d.wind_gust_max, w, symbols)}{d.compass ? ` ${d.compass}` : ""}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  </section>
{:else if error}
  <section class="card wide"><p class="bad">{error}</p></section>
{/if}

<style>
  .source {
    color: var(--muted);
    font-size: 0.8rem;
    font-weight: 400;
    margin-left: auto;
    text-align: right;
  }
  /* The hours scroll sideways on a narrow screen rather than wrapping into a grid. */
  .hours {
    display: flex;
    gap: 0.25rem;
    overflow-x: auto;
    padding-bottom: 0.4rem;
    margin: 0.4rem 0 0.9rem;
    scroll-snap-type: x proximity;
  }
  .hour {
    flex: none;
    width: 3.6rem;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.05rem;
    scroll-snap-align: start;
    font-variant-numeric: tabular-nums;
  }
  .time,
  .wind {
    color: var(--muted);
    font-size: 0.75rem;
  }
  /* Speed above direction in every hour, however long the two are. */
  .wind {
    display: flex;
    flex-direction: column;
    align-items: center;
    line-height: 1.25;
  }
  .humidity {
    display: inline-flex;
    align-items: center;
    gap: 0.1rem;
    font-size: 0.8rem;
  }
  .temp {
    font-weight: 600;
  }
  .rain {
    display: inline-flex;
    align-items: center;
    gap: 0.1rem;
    color: var(--cool);
    font-size: 0.8rem;
  }
  .rain.dry {
    color: var(--muted);
    opacity: 0.6;
  }
  /* On a wrapper, not the cell: a flex cell stops being a table cell, so it no longer takes its
     row's height and its border falls out of line with the others'. */
  .days .sky {
    display: flex;
    align-items: center;
    gap: 0.4rem;
  }
  .days img {
    flex: none;
  }
  .chance {
    color: var(--cool);
    font-size: 0.8rem;
  }
  .narrow-only {
    display: none;
  }
  @media (max-width: 30rem) {
    .wide-only {
      display: none;
    }
    .narrow-only {
      display: inline;
    }
    /* Beneath the amount rather than beside it, which leaves room for the humidity. */
    .chance {
      display: block;
    }
  }
</style>
