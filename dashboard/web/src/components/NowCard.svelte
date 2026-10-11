<script lang="ts">
  /** The headline: outdoor temperature, what it feels like, the day's range and one line in words. */
  import type { Now } from "../lib/api";
  import { clock, quantity } from "../lib/format";

  type Props = {
    now: Now;
    symbols: Record<string, string>;
    timezone: string;
    onselect: (view: string) => void;
  };
  let { now, symbols, timezone, onselect }: Props = $props();

  const t = $derived(now.units.temperature);
  const outdoor = $derived(now.outdoor);
  /** The summary leads with the temperature and feels-like, which the card shows already. */
  const summary = $derived(outdoor ? now.summary.split(". ").slice(1).join(". ") : now.summary);
</script>

<button class="card hero" onclick={() => onselect("temperature")}>
  {#if outdoor}
    <div class="temperature">{quantity(outdoor.temperature, t, symbols)}</div>
    {#if outdoor.feels_like !== null && outdoor.feels_like !== outdoor.temperature}
      <div class="feels">Feels like {quantity(outdoor.feels_like, t, symbols)}</div>
    {/if}
  {/if}
  {#if summary}<p class="summary">{summary}</p>{/if}
  {#if outdoor}
    <dl>
      <div><dt>Humidity</dt><dd>{quantity(outdoor.humidity, "pct", symbols)}</dd></div>
      <div><dt>Dew point</dt><dd>{quantity(outdoor.dew_point, t, symbols)}</dd></div>
      {#if outdoor.high && outdoor.low}
        <div>
          <dt>Today</dt>
          <dd>
            <span title="at {clock(outdoor.low.time, timezone)}">↓ {quantity(outdoor.low.value, t, symbols)}</span>
            <span title="at {clock(outdoor.high.time, timezone)}">↑ {quantity(outdoor.high.value, t, symbols)}</span>
          </dd>
        </div>
      {/if}
    </dl>
  {/if}
</button>

<style>
  @media (min-width: 36rem) {
    .hero {
      grid-column: span 2;
    }
  }
  .temperature {
    font-size: clamp(2.8rem, 9vw, 4rem);
    font-weight: 600;
    line-height: 1;
  }
  .feels {
    color: var(--muted);
    margin-top: 0.3rem;
  }
  .summary {
    margin: 0.8rem 0;
  }
  dd span + span {
    margin-left: 0.6rem;
  }
</style>
