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

  /** Whether airing would dry a room (good) or dampen it (bad), by a point or more. */
  function effect(room: Room): string {
    const after = room.airing?.humidity_after;
    if (after === null || after === undefined || room.humidity === null) return "muted";
    if (after <= room.humidity - 1) return "good";
    return after >= room.humidity + 1 ? "bad" : "muted";
  }

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
          <th class="num wide-only">Dew point</th>
          <th class="num" title="The humidity each room would settle at once its air had been replaced by outdoor air">If aired</th>
          {#if advised}<th class="wide-only">Airing</th>{/if}
        </tr>
      </thead>
      <tbody>
        {#each rooms as room (room.sensor)}
          {@const advice = room.airing ? ADVICE[room.airing.advice] : null}
          <tr>
            <td>{room.name}</td>
            <td class="num">{quantity(room.temperature, units.temperature, symbols)}</td>
            <td class="num">{quantity(room.humidity, "pct", symbols)}</td>
            <td class="num wide-only">{quantity(room.dew_point, units.temperature, symbols)}</td>
            <td class="num {effect(room)}">{quantity(room.airing?.humidity_after, "pct", symbols)}</td>
            {#if advised}<td class="wide-only">
              {#if advice?.text}
                <span class="badge {room.airing?.advice}" title={advice.hint}>{advice.text}</span>
              {/if}
            </td>{/if}
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
</section>

<style>
  /* A phone has room for what each room is and what airing would do to it, coloured; the dew
     point and the advice in words wait for a wider screen. */
  @media (max-width: 30rem) {
    .wide-only {
      display: none;
    }
  }
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
