<script lang="ts">
  /**
   * Whether to open the windows: the house's verdict, up top where it is seen, and what airing
   * would do to the rooms' humidity in two numbers large enough to read across the room.
   */
  import DoorOpenIcon from "@lucide/svelte/icons/door-open";
  import type { Notice, HouseAiring } from "../lib/api";
  import { coming, list, quantity } from "../lib/format";
  import { m } from "../paraglide/messages.js";

  type Props = {
    notice?: Notice;
    airing: HouseAiring;
    symbols: Record<string, string>;
    onselect: (view: string) => void;
    /** The station's time zone, for when the forecast says the air turns drier. */
    timezone?: string;
  };
  let { airing, symbols, onselect, notice, timezone = "UTC" }: Props = $props();

  const HEADLINES = { open: m.airing_open, keep_closed: m.airing_keep_closed, no_need: m.airing_no_need };

  const now = $derived(quantity(airing.humidity, "pct", symbols));
  const after = $derived(quantity(airing.humidity_after, "pct", symbols));
  /** The humidity where a room starts to be damp: the API's AIRING_HUMIDITY_PCT. */
  const DAMP_PCT = 65;
  /** A smaller change is within the sensors' error: the API's DAMPER_BY_PCT. */
  const MARGIN_PCT = 5;

  /** How airing would change the rooms' humidity: down, up, or by less than the sensors tell. */
  const change = $derived.by(() => {
    const later = airing.humidity_after;
    if (later === null) return null;
    if (later <= airing.humidity - MARGIN_PCT) return "down";
    return later >= airing.humidity + MARGIN_PCT ? "up" : "same";
  });
  /** Green when airing would dry the rooms; red only when it would make them damp. */
  const colour = $derived(
    change === "down" ? "good" : airing.advice === "keep_closed" ? "bad" : "",
  );
</script>

<button class="card airing {airing.advice} {notice?.level ?? ''}" onclick={() => onselect("rooms-humidity")}>
  <h2><DoorOpenIcon size={16} aria-hidden="true" /> {m.airing_title()}</h2>
  {#if notice?.text}<p class="notice">{notice.text}</p>{/if}
  <div class="big">{HEADLINES[airing.advice]()}</div>
  <div class="change" title={m.airing_change_hint()}>
    <div><span class="value">{now}</span><span class="label">{m.airing_indoors_now()}</span></div>
    {#if airing.humidity_after !== null}
      <span class="arrow" aria-hidden="true">→</span>
      <div><span class="value {colour}">{after}</span><span class="label">{m.airing_after()}</span></div>
    {/if}
  </div>
  <p>
    {#if airing.advice === "open"}
      {m.airing_explain_open({ rooms: list(airing.rooms) })}
    {:else if airing.advice === "keep_closed"}
      {m.airing_explain_keep_closed({ damp: DAMP_PCT })}
    {:else if change === "up"}
      {m.airing_explain_up({ damp: DAMP_PCT })}
    {:else if change === "same"}
      {m.airing_explain_same()}
    {:else}
      {m.airing_explain_dry()}
    {/if}
  </p>
  {#if airing.drier_from}
    <p class="later">{m.airing_drier_from({ time: coming(airing.drier_from, timezone) })}</p>
  {/if}
</button>

<style>
  .open .big {
    color: var(--good);
  }
  .keep_closed .big {
    color: var(--warn);
  }
  p {
    margin: 0.6rem 0 0;
  }
  .later {
    color: var(--good);
    font-weight: 500;
  }
  .change {
    display: flex;
    align-items: center;
    gap: 1.25rem;
    margin-top: 0.9rem;
  }
  .change > div {
    display: flex;
    flex-direction: column;
  }
  .value {
    font-size: clamp(2.2rem, 7vw, 3rem);
    font-weight: 600;
    line-height: 1;
    font-variant-numeric: tabular-nums;
  }
  .value.good {
    color: var(--good);
  }
  .value.bad {
    color: var(--bad);
  }
  .label {
    color: var(--muted);
    font-size: 0.85rem;
    margin-top: 0.25rem;
  }
  .arrow {
    font-size: 1.8rem;
    color: var(--muted);
    /* Level with the numbers, not with the numbers and their labels. */
    margin-bottom: 1.3rem;
  }
</style>
