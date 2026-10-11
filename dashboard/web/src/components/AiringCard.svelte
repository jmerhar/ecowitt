<script lang="ts">
  /** Whether to open the windows: the house's verdict, up top where it is seen. */
  import type { HouseAiring } from "../lib/api";
  import { quantity } from "../lib/format";

  type Props = {
    airing: HouseAiring;
    symbols: Record<string, string>;
    onselect: (view: string) => void;
  };
  let { airing, symbols, onselect }: Props = $props();

  const HEADLINES = {
    open: "Good time to air",
    keep_closed: "Keep the windows closed",
    no_need: "No need to air",
  } as const;

  const now = $derived(quantity(airing.humidity, "pct", symbols));
  const after = $derived(quantity(airing.humidity_after, "pct", symbols));
</script>

<button class="card airing {airing.advice}" onclick={() => onselect("rooms-humidity")}>
  <h2>Airing</h2>
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
  .airing {
    border-left-width: 4px;
  }
  .open {
    border-left-color: var(--good);
  }
  .open .big {
    color: var(--good);
  }
  .keep_closed {
    border-left-color: var(--warn);
  }
  .keep_closed .big {
    color: var(--warn);
  }
  p {
    margin: 0.6rem 0 0;
  }
</style>
