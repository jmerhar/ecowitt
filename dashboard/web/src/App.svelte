<script lang="ts">
  /**
   * The page: a station at a glance first, then its history and records. Everything shown comes
   * from the API; this only lays it out, remembers the visitor's choices and keeps it fresh.
   */
  import { onDestroy, onMount } from "svelte";
  import { Api, ApiError, type Meta, type Now, type Station, type UnitChoice } from "./lib/api";
  import { ago } from "./lib/format";
  import { load, save, type Prefs } from "./lib/prefs";
  import NowCard from "./components/NowCard.svelte";
  import WindCard from "./components/WindCard.svelte";
  import RainCard from "./components/RainCard.svelte";
  import PressureCard from "./components/PressureCard.svelte";
  import SunCard from "./components/SunCard.svelte";
  import Rooms from "./components/Rooms.svelte";
  import History from "./components/History.svelte";
  import Records from "./components/Records.svelte";
  import Sensors from "./components/Sensors.svelte";
  import UnitsMenu from "./components/UnitsMenu.svelte";

  type Props = {
    api?: Api;
    /** How often the current conditions are fetched again, in milliseconds. */
    refreshMs?: number;
    storage?: Storage;
  };
  let { api = new Api(), refreshMs = 60_000, storage }: Props = $props();

  // The saved choices are read once, when the page opens.
  // svelte-ignore state_referenced_locally
  let prefs = $state<Prefs>(load(storage));
  let meta = $state<Meta | null>(null);
  let stations = $state<Station[]>([]);
  let now = $state<Now | null>(null);
  let error = $state("");
  let clock = $state(new Date());
  let timer: ReturnType<typeof setInterval> | undefined;

  const station = $derived(
    stations.find((s) => s.id === prefs.station) ?? stations[0] ?? null,
  );
  const symbols = $derived(meta?.symbols ?? {});
  const timezone = $derived(now?.timezone ?? station?.timezone ?? "UTC");

  $effect(() => {
    save($state.snapshot(prefs), storage);
  });

  $effect(() => {
    if (meta) document.title = station ? `${station.id} · ${meta.title}` : meta.title;
  });

  async function start(): Promise<void> {
    try {
      [meta, stations] = await Promise.all([api.meta(), api.stations()]);
      error = "";
    } catch (exc) {
      error = message(exc);
      return;
    }
    await refresh();
    timer = setInterval(() => {
      clock = new Date();
      void refresh();
    }, refreshMs);
  }

  async function refresh(): Promise<void> {
    if (!station) return;
    try {
      now = await api.now(station.id, prefs.units);
      error = "";
    } catch (exc) {
      // The last answer stays on screen; the banner says it may be stale.
      error = message(exc);
    }
  }

  function message(exc: unknown): string {
    return exc instanceof ApiError ? exc.message : "Something went wrong loading the weather.";
  }

  function chooseStation(id: string): void {
    prefs.station = id;
    now = null;
    void refresh();
  }

  function chooseUnits(units: UnitChoice): void {
    prefs.units = units;
    void refresh();
  }

  function drill(view: string): void {
    prefs.view = view;
    document.getElementById("history")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  onMount(() => void start());
  onDestroy(() => clearInterval(timer));
</script>

<header>
  <div class="title">
    <h1>{meta?.title ?? "Weather"}</h1>
    {#if stations.length > 1}
      <label>
        <span class="visually-hidden">Station</span>
        <select value={station?.id} onchange={(e) => chooseStation(e.currentTarget.value)}>
          {#each stations as s (s.id)}<option value={s.id}>{s.id}</option>{/each}
        </select>
      </label>
    {:else if station}
      <span class="station">{station.id}</span>
    {/if}
  </div>
  <div class="status">
    {#if now}
      <span class="dot" class:offline={!now.online} title={now.online ? "Reporting" : "Not reporting"}></span>
      <span>{now.online ? "Updated" : "Last report"} {ago(now.time, clock)}</span>
    {/if}
    {#if meta}<UnitsMenu {meta} chosen={prefs.units} onchange={chooseUnits} />{/if}
  </div>
</header>

<main>
  {#if error}<p class="banner" role="alert">{error}</p>{/if}

  {#if meta && !stations.length && !error}
    <p class="empty">No station has published its settings yet.</p>
  {/if}

  {#if now && station && meta}
    <section class="glance">
      <NowCard {now} {symbols} {timezone} onselect={drill} />
      {#if now.wind}<WindCard wind={now.wind} units={now.units} {symbols} {timezone} onselect={drill} />{/if}
      {#if now.rain}<RainCard rain={now.rain} units={now.units} {symbols} onselect={drill} />{/if}
      {#if now.pressure}<PressureCard pressure={now.pressure} units={now.units} {symbols} onselect={drill} />{/if}
      {#if now.sun}<SunCard sun={now.sun} {symbols} {timezone} onselect={drill} />{/if}
    </section>

    {#if now.rooms.length}<Rooms rooms={now.rooms} units={now.units} {symbols} onselect={drill} />{/if}

    <History
      {api}
      {meta}
      station={station.id}
      units={prefs.units}
      {timezone}
      bind:view={prefs.view}
      bind:range={prefs.range}
    />

    <Records {api} {meta} station={station.id} units={prefs.units} {timezone} bind:period={prefs.period} />

    {#if now.sensors.length}<Sensors sensors={now.sensors} />{/if}
  {/if}
</main>

<style>
  header {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem 1.5rem;
    align-items: center;
    justify-content: space-between;
    padding: 0.9rem var(--gutter);
    border-bottom: 1px solid var(--line);
  }
  .title {
    display: flex;
    gap: 0.75rem;
    align-items: baseline;
    flex-wrap: wrap;
  }
  h1 {
    font-size: 1.25rem;
    margin: 0;
  }
  .station {
    color: var(--muted);
  }
  .status {
    display: flex;
    gap: 0.75rem;
    align-items: center;
    color: var(--muted);
    font-size: 0.9rem;
  }
  .dot {
    width: 0.6rem;
    height: 0.6rem;
    border-radius: 50%;
    background: var(--good);
  }
  .dot.offline {
    background: var(--bad);
  }
  main {
    max-width: 80rem;
    margin: 0 auto;
    padding: 1rem var(--gutter) 3rem;
  }
  .glance {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(15rem, 1fr));
    gap: 1rem;
  }
  .banner {
    border: 1px solid var(--bad);
    color: var(--bad);
    border-radius: 0.4rem;
    padding: 0.6rem 1rem;
  }
  .empty {
    color: var(--muted);
  }
</style>
