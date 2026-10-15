<script lang="ts">
  /**
   * The visitor's settings: units, one choice per quantity, where "station" leaves a quantity as
   * stored; for a station whose wind is estimated at 10 m, whether the page leads with that or the
   * measurement; the theme; full screen, where the browser offers it; and the page's language,
   * or the browser's.
   */
  import SlidersHorizontalIcon from "@lucide/svelte/icons/sliders-horizontal";
  import type { Meta, UnitChoice, Units } from "../lib/api";
  import type { WindHeight } from "../lib/prefs";
  import type { ThemeChoice } from "../lib/theme";
  import { LANGUAGE_NAMES } from "../lib/language";
  import { locales, type Locale } from "../paraglide/runtime.js";
  import { m } from "../paraglide/messages.js";

  type Props = {
    meta: Meta;
    chosen: UnitChoice;
    onchange: (units: UnitChoice) => void;
    /** Which wind the page leads with; null hides the choice, for a station without an estimate. */
    wind?: WindHeight | null;
    onwind?: (wind: WindHeight) => void;
    theme?: ThemeChoice;
    ontheme?: (theme: ThemeChoice) => void;
    /** Whether the page fills the screen now; null hides the switch, where the browser cannot. */
    fullscreen?: boolean | null;
    onfullscreen?: (fullscreen: boolean) => void;
    /** The visitor's chosen language, or null to follow the browser's. */
    language?: Locale | null;
    onlanguage?: (language: Locale | null) => void;
  };
  let {
    meta,
    chosen,
    onchange,
    wind = null,
    onwind = () => {},
    theme = "system",
    ontheme = () => {},
    fullscreen = null,
    onfullscreen = () => {},
    language = null,
    onlanguage = () => {},
  }: Props = $props();

  const THEMES: Record<ThemeChoice, () => string> = {
    system: m.theme_system,
    light: m.theme_light,
    dark: m.theme_dark,
    sun: m.theme_sun,
  };

  const LABELS: Record<string, () => string> = {
    temperature: m.temperature,
    pressure: m.pressure_title,
    wind: m.wind_title,
    rain: m.rain_title,
  };

  function choose(quantity: string, code: string): void {
    const next: UnitChoice = { ...chosen };
    if (code) next[quantity as keyof Units] = code;
    else delete next[quantity as keyof Units];
    onchange(next);
  }
</script>

<details class="menu">
  <summary aria-label={m.settings()} title={m.settings()}>
    <SlidersHorizontalIcon size={18} aria-hidden="true" />
  </summary>
  <div class="panel">
    {#each Object.keys(LABELS) as quantity (quantity)}
      <label>
        {LABELS[quantity]()}
        <select
          value={chosen[quantity as keyof Units] ?? ""}
          onchange={(e) => choose(quantity, e.currentTarget.value)}>
          <option value="">{m.as_stored()}</option>
          {#each meta.units[quantity] ?? [] as unit (unit.code)}
            <option value={unit.code}>{unit.symbol}</option>
          {/each}
        </select>
      </label>
    {/each}
    {#if wind}
      <label>
        {m.wind_at()}
        <select value={wind} onchange={(e) => onwind(e.currentTarget.value as WindHeight)}>
          <option value="10m">{m.wind_at_10m_choice()}</option>
          <option value="sensor">{m.wind_at_sensor_choice()}</option>
        </select>
      </label>
    {/if}
    <label>
      {m.theme()}
      <select value={theme} onchange={(e) => ontheme(e.currentTarget.value as ThemeChoice)}>
        {#each Object.entries(THEMES) as [code, label] (code)}<option value={code}>{label()}</option>{/each}
      </select>
    </label>
    <label>
      {m.language()}
      <select value={language ?? ""} onchange={(e) => onlanguage((e.currentTarget.value || null) as Locale | null)}>
        <option value="">{m.language_browser()}</option>
        {#each locales as code (code)}<option value={code} lang={code}>{LANGUAGE_NAMES[code]}</option>{/each}
      </select>
    </label>
    {#if fullscreen !== null}
      <!-- A home screen keeps how an app opens from when it was added: an icon added while this
           is on opens full screen every time. -->
      <label title={m.fullscreen_hint()}>
        {m.fullscreen()}
        <input type="checkbox" checked={fullscreen} onchange={(e) => onfullscreen(e.currentTarget.checked)} />
      </label>
    {/if}
  </div>
</details>

<style>
  .menu {
    position: relative;
  }
  /* An icon, in a square big enough to tap; the word is its name for screen readers and its
     tooltip. */
  summary {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 2.25rem;
    height: 2.25rem;
    box-sizing: border-box;
    cursor: pointer;
    color: var(--muted);
    border: 1px solid var(--line);
    border-radius: 0.3rem;
    list-style: none;
  }
  summary:hover {
    color: var(--fg);
  }
  /* Chrome before 89 and Safari draw the triangle as this, which list-style does not reach. */
  summary::-webkit-details-marker {
    display: none;
  }
  .panel {
    position: absolute;
    right: 0;
    top: calc(100% + 0.35rem);
    z-index: 2;
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 0.4rem;
    padding: 0.75rem;
    display: grid;
    gap: 0.5rem;
    min-width: 13rem;
  }
  label {
    display: flex;
    justify-content: space-between;
    gap: 0.75rem;
    align-items: center;
    color: var(--fg);
    white-space: nowrap;
  }
</style>
