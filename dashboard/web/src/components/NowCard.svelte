<script lang="ts">
  /**
   * The headline: outdoor temperature, what it feels like, the sky from the weather model, the
   * day's range and one line in words.
   */
  import type { Notice, Now } from "../lib/api";
  import { clock, quantity } from "../lib/format";
  import { skyIcon } from "../lib/sky";
  import ThermometerIcon from "@lucide/svelte/icons/thermometer";

  type Props = {
    notice?: Notice;
    now: Now;
    symbols: Record<string, string>;
    timezone: string;
    onselect: (view: string) => void;
  };
  let { now, symbols, timezone, onselect, notice }: Props = $props();

  const t = $derived(now.units.temperature);
  const outdoor = $derived(now.outdoor);
  const sky = $derived(now.sky);
  /** The summary leads with the sky and the temperature, which the card shows already. */
  const summary = $derived.by(() => {
    const parts = now.summary.split(". ");
    if (sky && parts[0] === sky.description) parts.shift();
    if (outdoor?.temperature != null) parts.shift();
    return parts.join(". ");
  });
</script>

<button class="card hero {notice?.level ?? ''}" onclick={() => onselect("temperature")}>
  <h2><ThermometerIcon size={16} aria-hidden="true" /> Outdoors</h2>
  <div class="headline">
    {#if outdoor}
      <div>
        <div class="temperature">{quantity(outdoor.temperature, t, symbols)}</div>
        {#if outdoor.feels_like !== null && outdoor.feels_like !== outdoor.temperature}
          <div class="feels">Feels like {quantity(outdoor.feels_like, t, symbols)}</div>
        {/if}
      </div>
    {/if}
    {#if sky}
      <div class="sky" title="From the weather model, for {clock(sky.time, timezone)}">
        <img src={skyIcon(sky.code, sky.is_day)} alt="" width="72" height="72" />
        <span>{sky.description}</span>
      </div>
    {/if}
  </div>
  {#if notice?.text}<p class="notice">{notice.text}</p>{/if}
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
  .headline {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 0.5rem;
  }
  .sky {
    display: flex;
    flex-direction: column;
    align-items: center;
    color: var(--muted);
    font-size: 0.85rem;
    text-align: center;
    /* The icon's own margin, so it does not push the temperature down. */
    margin-top: -0.5rem;
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
