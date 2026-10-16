<script lang="ts">
  /**
   * The headline: outdoor temperature, what it feels like, the sky from the weather model, the
   * day's range and one line in words.
   */
  import type { Notice, Now } from "../lib/api";
  import { clock, hourOf, quantity } from "../lib/format";
  import { skyIcon } from "../lib/sky";
  import { dewPointLevel, humidityLevel, type Level } from "../lib/levels";
  import ThermometerIcon from "@lucide/svelte/icons/thermometer";
  import { m } from "../paraglide/messages.js";

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
  const humidity = $derived(outdoor?.humidity != null ? humidityLevel(outdoor.humidity) : null);
  const dew = $derived(outdoor?.dew_point != null ? dewPointLevel(outdoor.dew_point, t) : null);
  const sky = $derived(now.sky);
  /** The summary without the sky and the temperature, which the card shows already. */
  const summary = $derived(
    now.summary_parts
      .filter((part) => part.code !== "sky" && part.code !== "temperature")
      .map((part) => `${part.text}.`)
      .join(" "),
  );
</script>

<button class="card hero {notice?.level ?? ''}" onclick={() => onselect("temperature")}>
  <h2><ThermometerIcon size={16} aria-hidden="true" /> {m.now_title()}</h2>
  <div class="headline">
    {#if outdoor}
      <div>
        <div class="temperature">{quantity(outdoor.temperature, t, symbols)}</div>
        {#if outdoor.feels_like !== null && outdoor.feels_like !== outdoor.temperature}
          <div class="feels">{m.feels_like({ value: quantity(outdoor.feels_like, t, symbols) })}</div>
        {/if}
      </div>
    {/if}
    {#if sky}
      <div class="side-icon sky" title={m.sky_from_model({ time: clock(sky.time, timezone), hour: hourOf(sky.time, timezone) })}>
        <img src={skyIcon(sky.code, sky.is_day)} alt="" width="72" height="72" />
        <span>{sky.description}</span>
      </div>
    {/if}
  </div>
  {#if notice?.text}<p class="notice">{notice.text}</p>{/if}
  {#if summary}<p class="summary">{summary}</p>{/if}
  {#if outdoor}
    <dl>
      {#snippet bar(label: string, value: string, level: Level | null)}
        <div class="level">
          <dt>{label}</dt>
          {#if level}
            <span class="bar {level.tone}" title={level.words}><span style="width: {level.fill}%"></span></span>
          {/if}
          <dd>{value}{#if level}<span class="visually-hidden">, {level.words}</span>{/if}</dd>
        </div>
      {/snippet}
      {@render bar(m.humidity(), quantity(outdoor.humidity, "pct", symbols), humidity)}
      {@render bar(m.dew_point(), quantity(outdoor.dew_point, t, symbols), dew)}
      {#if outdoor.high && outdoor.low}
        <div>
          <dt>{m.today()}</dt>
          <dd>
            <span title={m.at_time({ time: clock(outdoor.low.time, timezone), hour: hourOf(outdoor.low.time, timezone) })}>↓ {quantity(outdoor.low.value, t, symbols)}</span>
            <span title={m.at_time({ time: clock(outdoor.high.time, timezone), hour: hourOf(outdoor.high.time, timezone) })}>↑ {quantity(outdoor.high.value, t, symbols)}</span>
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
    color: var(--muted);
  }
  /* The temperature is sized to the card, not the window: three cards abreast leave each far
     less room than one card on a phone, and it must stay on one line. */
  .hero {
    container-type: inline-size;
  }
  .temperature {
    font-size: clamp(2.2rem, 19cqi, 4rem);
    font-weight: 600;
    line-height: 1;
    white-space: nowrap;
  }
  /* Humidity and dew point: a bar between the label and the value, coloured by level. */
  .level {
    align-items: center;
  }
  .level dt {
    flex: none;
    width: 5.5rem;
  }
  .bar {
    flex: 1;
    height: 0.5rem;
    border-radius: 0.25rem;
    background: var(--line);
    overflow: hidden;
  }
  .bar span {
    display: block;
    height: 100%;
  }
  .bar.good span {
    background: var(--good);
  }
  .bar.warn span {
    background: var(--warn);
  }
  .bar.bad span {
    background: var(--bad);
  }
  .bar.cool span {
    background: var(--cool);
  }
  .level dd {
    flex: none;
    min-width: 4rem;
    font-weight: 600;
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
