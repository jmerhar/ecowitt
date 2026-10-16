<script lang="ts">
  /**
   * Whether to open the windows, or to close them while they look open: the house's verdict, up
   * top where it is seen, and what airing would do to the rooms' humidity in two numbers large
   * enough to read across the room.
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

  const HEADLINES = {
    open: m.airing_open,
    keep_closed: m.airing_keep_closed,
    no_need: m.airing_no_need,
    close: m.airing_close,
    aired: m.airing_aired,
  };

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
  <div class="headline">
    <div class="verdict">
      {#if notice?.text}<p class="notice">{notice.text}</p>{/if}
      <div class="big">{HEADLINES[airing.advice]()}</div>
    </div>
    {#if airing.windows_open}
      <div class="side-icon windows" title={m.airing_windows_open_hint()}>
        <!-- A pair of casements, both panes swung open. -->
        <svg viewBox="-4 -4 32 32" aria-hidden="true">
          <rect x="3" y="3" width="18" height="18" rx="1.5" />
          <path d="M3 3l4.5 2.6v12.8L3 21M21 3l-4.5 2.6v12.8L21 21M3 12h4.5M16.5 12H21" />
        </svg>
        <span>{m.airing_windows_open()}</span>
      </div>
    {/if}
  </div>
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
    {:else if airing.advice === "close"}
      {m.airing_explain_close()}
    {:else if airing.advice === "aired"}
      {m.airing_explain_aired()}
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
  .headline {
    display: flex;
    justify-content: space-between;
    gap: 0.5rem;
  }
  .verdict {
    min-width: 0;
  }
  .windows {
    color: var(--good);
  }
  .close .windows {
    color: var(--warn);
  }
  .windows svg {
    fill: none;
    stroke: currentColor;
    stroke-width: 1.5;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  .open .big {
    color: var(--good);
  }
  .keep_closed .big,
  .close .big {
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
