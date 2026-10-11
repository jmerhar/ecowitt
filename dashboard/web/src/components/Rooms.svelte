<script lang="ts">
  /** Every room's latest reading, with whether opening its windows would dry it. */
  import type { Room, Units } from "../lib/api";
  import { quantity } from "../lib/format";

  type Props = {
    rooms: Room[];
    units: Units;
    symbols: Record<string, string>;
    onselect: (view: string) => void;
  };
  let { rooms, units, symbols, onselect }: Props = $props();

  const ADVICE = {
    open: { text: "Air it", hint: "The outside air is drier: airing would bring humidity down" },
    keep_closed: {
      text: "Keep closed",
      hint: "The outside air holds as much moisture or more: airing would not dry it",
    },
    no_need: { text: "", hint: "" },
  } as const;

  /** The airing column, only while some room has advice to give. */
  const advised = $derived(rooms.some((r) => r.airing && r.airing.advice !== "no_need"));
</script>

<section class="card wide">
  <h2>Rooms</h2>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Room</th>
          <th class="num"><button class="link" onclick={() => onselect("rooms-temperature")}>Temperature</button></th>
          <th class="num"><button class="link" onclick={() => onselect("rooms-humidity")}>Humidity</button></th>
          <th class="num">Dew point</th>
          {#if advised}<th>Airing</th>{/if}
        </tr>
      </thead>
      <tbody>
        {#each rooms as room (room.sensor)}
          {@const advice = room.airing ? ADVICE[room.airing.advice] : null}
          <tr>
            <td>{room.name}</td>
            <td class="num">{quantity(room.temperature, units.temperature, symbols)}</td>
            <td class="num">{quantity(room.humidity, "pct", symbols)}</td>
            <td class="num">{quantity(room.dew_point, units.temperature, symbols)}</td>
            {#if advised}<td>
              {#if advice?.text}
                <span class="badge {room.airing?.advice}" title={advice.hint}>{advice.text}</span>
                {#if room.airing?.humidity_after !== null && room.airing?.advice === "open"}
                  <span class="muted">→ {quantity(room.airing?.humidity_after, "pct", symbols)}</span>
                {/if}
              {/if}
            </td>{/if}
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
</section>

<style>
  .badge {
    border-radius: 1rem;
    padding: 0.05rem 0.55rem;
    font-size: 0.85rem;
    border: 1px solid currentColor;
  }
  .badge.open {
    color: var(--good);
  }
  .badge.keep_closed {
    color: var(--warn);
  }
</style>
