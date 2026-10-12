<script lang="ts">
  /**
   * Whether to open the windows: the house's verdict, up top where it is seen, and what airing
   * would do to the rooms' humidity in two numbers large enough to read across the room.
   */
  import DoorOpenIcon from "@lucide/svelte/icons/door-open";
  import type { Notice, HouseAiring } from "../lib/api";
  import { quantity } from "../lib/format";

  type Props = {
    notice?: Notice;
    airing: HouseAiring;
    symbols: Record<string, string>;
    onselect: (view: string) => void;
  };
  let { airing, symbols, onselect, notice }: Props = $props();

  const HEADLINES = {
    open: "Good time to air",
    keep_closed: "Keep the windows closed",
    no_need: "No need to air",
  } as const;

  const now = $derived(quantity(airing.humidity, "pct", symbols));
  const after = $derived(quantity(airing.humidity_after, "pct", symbols));
  /** The humidity where a room starts to be damp: the API's AIRING_HUMIDITY_PCT. */
  const DAMP_PCT = 65;

  /** How airing would change the rooms' humidity: down, up, or by under a point. */
  const change = $derived.by(() => {
    const later = airing.humidity_after;
    if (later === null) return null;
    if (later <= airing.humidity - 1) return "down";
    return later >= airing.humidity + 1 ? "up" : "same";
  });
  /** Green when airing would dry the rooms; red only when it would make them damp. */
  const colour = $derived(
    change === "down" ? "good" : airing.advice === "keep_closed" ? "bad" : "",
  );
</script>

<button class="card airing {airing.advice} {notice?.level ?? ''}" onclick={() => onselect("rooms-humidity")}>
  <h2><DoorOpenIcon size={16} aria-hidden="true" /> Airing</h2>
  {#if notice?.text}<p class="notice">{notice.text}</p>{/if}
  <div class="big">{HEADLINES[airing.advice]}</div>
  <div class="change" title="The middle room's humidity, now and once its air had been replaced by outdoor air">
    <div><span class="value">{now}</span><span class="label">indoors now</span></div>
    {#if airing.humidity_after !== null}
      <span class="arrow" aria-hidden="true">→</span>
      <div><span class="value {colour}">{after}</span><span class="label">after airing</span></div>
    {/if}
  </div>
  <p>
    {#if airing.advice === "open"}
      The outside air is drier: airing would dry {airing.rooms.join(", ")}.
    {:else if airing.advice === "keep_closed"}
      The outside air is more humid: airing would take the rooms to {DAMP_PCT}% or more, where
      damp starts.
    {:else if change === "up"}
      Airing would make the rooms a little more humid, but not enough to matter: they would stay
      under {DAMP_PCT}%.
    {:else if change === "same"}
      Airing would make little difference: the outside air is about as humid as the rooms.
    {:else}
      The rooms are dry enough.
    {/if}
  </p>
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
