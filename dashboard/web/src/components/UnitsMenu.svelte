<script lang="ts">
  /**
   * The visitor's settings: units, one choice per quantity, where "station" leaves a quantity as
   * stored; for a station whose wind is estimated at 10 m, whether the page leads with that or the
   * measurement; the theme; and full screen, where the browser offers it.
   */
  import type { Meta, UnitChoice, Units } from "../lib/api";
  import type { WindHeight } from "../lib/prefs";
  import type { ThemeChoice } from "../lib/theme";

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
  }: Props = $props();

  const THEMES: Record<ThemeChoice, string> = {
    system: "As the device",
    light: "Light",
    dark: "Dark",
    sun: "Dark at night",
  };

  const LABELS: Record<string, string> = {
    temperature: "Temperature",
    pressure: "Pressure",
    wind: "Wind",
    rain: "Rain",
  };

  function choose(quantity: string, code: string): void {
    const next: UnitChoice = { ...chosen };
    if (code) next[quantity as keyof Units] = code;
    else delete next[quantity as keyof Units];
    onchange(next);
  }
</script>

<details class="menu">
  <summary>Settings</summary>
  <div class="panel">
    {#each Object.keys(LABELS) as quantity (quantity)}
      <label>
        {LABELS[quantity]}
        <select
          value={chosen[quantity as keyof Units] ?? ""}
          onchange={(e) => choose(quantity, e.currentTarget.value)}>
          <option value="">As stored</option>
          {#each meta.units[quantity] ?? [] as unit (unit.code)}
            <option value={unit.code}>{unit.symbol}</option>
          {/each}
        </select>
      </label>
    {/each}
    {#if wind}
      <label>
        Wind at
        <select value={wind} onchange={(e) => onwind(e.currentTarget.value as WindHeight)}>
          <option value="10m">10 m, estimated</option>
          <option value="sensor">The sensor</option>
        </select>
      </label>
    {/if}
    <label>
      Theme
      <select value={theme} onchange={(e) => ontheme(e.currentTarget.value as ThemeChoice)}>
        {#each Object.entries(THEMES) as [code, label] (code)}<option value={code}>{label}</option>{/each}
      </select>
    </label>
    {#if fullscreen !== null}
      <!-- A home screen keeps how an app opens from when it was added: an icon added while this
           is on opens full screen every time. -->
      <label title="Added to the home screen while this is on, the page opens full screen">
        Full screen
        <input type="checkbox" checked={fullscreen} onchange={(e) => onfullscreen(e.currentTarget.checked)} />
      </label>
    {/if}
  </div>
</details>

<style>
  .menu {
    position: relative;
  }
  summary {
    cursor: pointer;
    border: 1px solid var(--line);
    border-radius: 0.3rem;
    padding: 0.2rem 0.6rem;
    list-style: none;
  }
  .panel {
    position: absolute;
    right: 0;
    top: 2.2rem;
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
