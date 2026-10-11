<script lang="ts">
  /**
   * Every room's latest reading, with whether opening its windows would dry it; sorted by any
   * column its header is clicked for, in the order the station lists the rooms until then.
   */
  import HouseIcon from "@lucide/svelte/icons/house";
  import type { Notice, Room, Units } from "../lib/api";
  import { quantity } from "../lib/format";
  import type { RoomSort } from "../lib/prefs";

  type Props = {
    rooms: Room[];
    units: Units;
    symbols: Record<string, string>;
    notice?: Notice;
    /** The order chosen, kept with the visitor's other choices. */
    sort?: RoomSort | null;
  };
  let { rooms, units, symbols, notice, sort = $bindable(null) }: Props = $props();

  /** What each sortable column sorts by. */
  const COLUMNS: Record<string, (room: Room) => string | number | null | undefined> = {
    name: (r) => r.name,
    temperature: (r) => r.temperature,
    humidity: (r) => r.humidity,
    dew_point: (r) => r.dew_point,
    after: (r) => r.airing?.humidity_after,
  };

  /** The rooms in the chosen order; a room without the value sorts last whichever way. */
  const sorted = $derived.by(() => {
    const by = sort ? COLUMNS[sort.column] : undefined;
    if (!sort || !by) return rooms;
    const sign = sort.descending ? -1 : 1;
    return [...rooms].sort((a, b) => {
      const x = by(a);
      const y = by(b);
      if (x == null || y == null) return x == null ? (y == null ? 0 : 1) : -1;
      return sign * (typeof x === "string" ? x.localeCompare(String(y)) : x - (y as number));
    });
  });

  /** Sort by a column, or turn it round when it is the one sorted by already. */
  function choose(column: string): void {
    sort = sort?.column === column ? { column, descending: !sort.descending } : { column, descending: false };
  }

  function ariaSort(column: string): "ascending" | "descending" | "none" {
    if (sort?.column !== column) return "none";
    return sort.descending ? "descending" : "ascending";
  }

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

<section class="card wide {notice?.level ?? ''}">
  <h2><HouseIcon size={16} aria-hidden="true" /> Rooms</h2>
  {#if notice?.text}<p class="notice">{notice.text}</p>{/if}
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          {#snippet header(column: string, label: string, classes: string, hint?: string)}
            <th class={classes} aria-sort={ariaSort(column)} title={hint}>
              <button class="link" onclick={() => choose(column)}>{label}<span class="arrow" aria-hidden="true"
                >{sort?.column === column ? (sort.descending ? " ↓" : " ↑") : ""}</span></button>
            </th>
          {/snippet}
          {@render header("name", "Room", "")}
          {@render header("temperature", "Temperature", "num")}
          {@render header("humidity", "Humidity", "num")}
          {@render header("dew_point", "Dew point", "num wide-only")}
          {@render header("after", "If aired", "num", "The humidity each room would settle at once its air had been replaced by outdoor air")}
          {#if advised}<th class="wide-only">Airing</th>{/if}
        </tr>
      </thead>
      <tbody>
        {#each sorted as room (room.sensor)}
          {@const advice = room.airing ? ADVICE[room.airing.advice] : null}
          <tr>
            <td>{room.name}</td>
            <td class="num" class:warn={room.flags.includes("cold") || room.flags.includes("hot")}>
              {quantity(room.temperature, units.temperature, symbols)}</td>
            <td class="num" class:warn={room.flags.includes("damp") || room.flags.includes("dry")}>
              {quantity(room.humidity, "pct", symbols)}</td>
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
