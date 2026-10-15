<script lang="ts">
  /**
   * The page: a station at a glance first, then its history and records. Everything shown comes
   * from the API; this only lays it out, remembers the visitor's choices and keeps it fresh.
   */
  import { onDestroy, onMount } from "svelte";
  import { Api, ApiError, type Meta, type Now, type Station, type UnitChoice } from "./lib/api";
  import { ago, today, zoneCity } from "./lib/format";
  import { load, save, type Prefs } from "./lib/prefs";
  import { applyTheme, themeAt } from "./lib/theme";
  import { canFullscreen, enterFullscreen, exitFullscreen, isFullscreen, onFullscreenChange } from "./lib/fullscreen";
  import NowCard from "./components/NowCard.svelte";
  import AiringCard from "./components/AiringCard.svelte";
  import WindCard from "./components/WindCard.svelte";
  import RainCard from "./components/RainCard.svelte";
  import PressureCard from "./components/PressureCard.svelte";
  import SunCard from "./components/SunCard.svelte";
  import Rooms from "./components/Rooms.svelte";
  import History from "./components/History.svelte";
  import Records from "./components/Records.svelte";
  import Forecast from "./components/Forecast.svelte";
  import Sensors from "./components/Sensors.svelte";
  import UnitsMenu from "./components/UnitsMenu.svelte";

  type Props = {
    api?: Api;
    /** How often the current conditions are fetched again, in milliseconds. */
    refreshMs?: number;
    /** How often the clock in the header moves, in milliseconds. */
    clockMs?: number;
    storage?: Storage;
  };
  let { api = new Api(), refreshMs = 60_000, clockMs = 10_000, storage }: Props = $props();

  // The saved choices are read once, when the page opens.
  // svelte-ignore state_referenced_locally
  let prefs = $state<Prefs>(load(storage));
  let meta = $state<Meta | null>(null);
  let stations = $state<Station[]>([]);
  let now = $state<Now | null>(null);
  let error = $state("");
  let clock = $state(new Date());
  /** Whether the page fills the screen, which the browser may change on its own (a back gesture). */
  let fullscreen = $state(isFullscreen());
  let stopWatchingFullscreen: (() => void) | undefined;
  /** Counts the refreshes, so the charts and records fetch again on each as well. */
  let tick = $state(0);
  let timer: ReturnType<typeof setInterval> | undefined;
  /** Keeps the clock and "updated ... ago" current between refreshes. */
  let ticker: ReturnType<typeof setInterval> | undefined;

  const station = $derived(
    stations.find((s) => s.id === prefs.station) ?? stations[0] ?? null,
  );
  const symbols = $derived(meta?.symbols ?? {});
  /** Whether the station's wind can differ from the measurement: scaled to 10 m, or the weather
   * model's while the cups stall. */
  const estimatesWind = $derived(station !== null && (station.wind_factor !== 1 || station.weather_model !== null));
  /** The wind the page leads with: the visitor's choice, where the station gives one. */
  const windHeight = $derived(estimatesWind ? prefs.wind : "10m");
  const timezone = $derived(now?.timezone ?? station?.timezone ?? "UTC");
  /** Light or dark, rechecked as the clock moves, so following the sun turns at sunset. */
  const theme = $derived(themeAt(prefs.theme, now?.sun ?? null, clock, prefs.sunTheme));

  // The manifest a home screen reads when the page is added to it: one that opens the app
  // without the system's bars, while the visitor's last choice was full screen. Leaving full
  // screen some other way keeps it, since that is how the browser's menu is reached to add it.
  $effect(() => {
    const href = prefs.fullscreen ? "/manifest.webmanifest?display=fullscreen" : "/manifest.webmanifest";
    document.querySelector('link[rel="manifest"]')?.setAttribute("href", href);
  });

  $effect(() => {
    applyTheme(theme);
    if (prefs.theme === "sun" && theme !== prefs.sunTheme) prefs.sunTheme = theme;
  });

  $effect(() => {
    save($state.snapshot(prefs), storage);
  });

  $effect(() => {
    if (!meta) return;
    document.title = station ? `${station.id} · ${meta.title}` : meta.title;
    // The name iOS gives the page when it is added to the home screen: the site's, like the
    // manifest's, rather than the station's.
    document.querySelector('meta[name="apple-mobile-web-app-title"]')?.setAttribute("content", meta.title);
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
      tick += 1;
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

  /** Fill the screen now, or leave it, and remember the choice for the home screen. */
  function chooseFullscreen(on: boolean): void {
    prefs.fullscreen = on;
    if (on) enterFullscreen();
    else exitFullscreen();
  }

  function drill(view: string): void {
    prefs.view = view;
    document.getElementById("history")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  onMount(() => {
    ticker = setInterval(() => (clock = new Date()), clockMs);
    stopWatchingFullscreen = onFullscreenChange(() => (fullscreen = isFullscreen()));
    void start();
  });
  onDestroy(() => {
    clearInterval(timer);
    clearInterval(ticker);
    stopWatchingFullscreen?.();
  });
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
    {#if station}
      <span class="time" title={timezone}>{today(clock.toISOString(), timezone)} {zoneCity(timezone)} time</span>
    {/if}
    {#if now}
      <span class="dot" class:offline={!now.online} title={now.online ? "Reporting" : "Not reporting"}></span>
      <span>{now.online ? "Updated" : "Last report"} {ago(now.time, clock)}</span>
    {/if}
    {#if meta}
      <UnitsMenu {meta} chosen={prefs.units} onchange={chooseUnits}
        wind={estimatesWind ? prefs.wind : null} onwind={(w) => (prefs.wind = w)}
        theme={prefs.theme} ontheme={(t) => (prefs.theme = t)}
        fullscreen={canFullscreen() || fullscreen ? fullscreen : null} onfullscreen={chooseFullscreen} />
    {/if}
  </div>
</header>

<main>
  {#if error}<p class="banner" role="alert">{error}</p>{/if}

  {#if meta && !stations.length && !error}
    <p class="empty">No station has published its settings yet.</p>
  {/if}

  {#if now && station && meta}
    <section class="glance">
      <NowCard {now} {symbols} {timezone} onselect={drill} notice={now.notices.outdoor} />
      {#if now.airing}<AiringCard airing={now.airing} {symbols} {timezone} onselect={drill} notice={now.notices.airing} />{/if}
      {#if now.wind}<WindCard wind={now.wind} height={windHeight} units={now.units} {symbols} {timezone} onselect={drill} notice={now.notices.wind} />{/if}
      {#if now.rain}<RainCard rain={now.rain} units={now.units} {symbols} onselect={drill} notice={now.notices.rain} />{/if}
      {#if now.pressure}<PressureCard pressure={now.pressure} units={now.units} {symbols} onselect={drill} notice={now.notices.pressure} />{/if}
      {#if now.sun}<SunCard sun={now.sun} {symbols} {timezone} onselect={drill} notice={now.notices.sun} />{/if}
    </section>

    <Forecast {api} station={station.id} units={prefs.units} {timezone} {symbols} {tick} />

    {#if now.rooms.length}<Rooms rooms={now.rooms} units={now.units} {symbols} notice={now.notices.rooms} bind:sort={prefs.rooms} />{/if}

    <History
      {api}
      {meta}
      station={station.id}
      units={prefs.units}
      {timezone}
      {tick}
      bind:view={prefs.view}
      bind:range={prefs.range}
      weatherModel={station.weather_model}
      bind:model={prefs.model}
      wind={windHeight}
    />

    <Records {api} {meta} station={station.id} units={prefs.units} {timezone} {tick} bind:period={prefs.period} wind={windHeight} />

    {#if now.sensors.length}<Sensors sensors={now.sensors} notice={now.notices.sensors} />{/if}
  {/if}
</main>

<footer>
  {#if station?.weather_model}
    Weather model data by <a href="https://open-meteo.com/">Open-Meteo.com</a>
    (<a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>) ·
  {/if}
  Icons by Meteocons and Lucide · <a href="/licenses.md">Licences</a>
  {#if meta}· Ecowitt Server {meta.version}{/if}
</footer>

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
  .time {
    color: var(--fg);
    font-variant-numeric: tabular-nums;
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
  /* Six cards: three columns by two rows on a wide screen, two by three on a narrower one, one
     column on a phone -- always a full grid. */
  .glance {
    display: grid;
    grid-template-columns: 1fr;
    gap: 1rem;
  }
  @media (min-width: 36rem) {
    .glance {
      grid-template-columns: repeat(2, 1fr);
    }
  }
  @media (min-width: 60rem) {
    .glance {
      grid-template-columns: repeat(3, 1fr);
    }
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
  footer {
    max-width: 80rem;
    margin: 0 auto;
    padding: 0 var(--gutter) 2rem;
    color: var(--muted);
    font-size: 0.8rem;
  }
  footer a {
    color: inherit;
  }
</style>
