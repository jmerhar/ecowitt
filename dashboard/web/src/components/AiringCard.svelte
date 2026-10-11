<script lang="ts">
  /** Whether to open the windows: the house's verdict, up top where it is seen. */
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
</script>

<button class="card airing {airing.advice} {notice?.level ?? ''}" onclick={() => onselect("rooms-humidity")}>
  <h2><DoorOpenIcon size={16} aria-hidden="true" /> Airing</h2>
  {#if notice?.text}<p class="notice">{notice.text}</p>{/if}
  <div class="big">{HEADLINES[airing.advice]}</div>
  <p>
    {#if airing.advice === "open"}
      The outside air is drier: airing would dry {airing.rooms.join(", ")}.
    {:else if airing.advice === "keep_closed"}
      The outside air holds as much moisture as the rooms, or more{#if airing.humidity_after !== null}:
        airing would take them from about {now} to {after}{/if}.
    {:else}
      The rooms are dry enough, at about {now}.
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
</style>
