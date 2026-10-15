/**
 * What a visitor chose last time -- station, units, chart, theme -- kept in this browser only. Storage
 * can be missing or refuse (private windows, blocked site data), so every access is guarded and
 * the defaults stand in.
 */

import type { UnitChoice } from "./api";
import { THEME_CHOICES, type Theme, type ThemeChoice } from "./theme";

export type Prefs = {
  station: string | null;
  units: UnitChoice;
  view: string;
  range: string;
  period: string;
  /** Whether the charts show the weather model's lines beside the station's. */
  model: boolean;
  /** How the rooms table is sorted, or null for the order the station lists them in. */
  rooms: RoomSort | null;
  /** Which wind the wind card and chart lead with. */
  wind: WindHeight;
  /** Light or dark: the system's, a fixed one, or the sun's. */
  theme: ThemeChoice;
  /** What following the sun last showed, for the moment before its times arrive. */
  sunTheme: Theme;
  /** Whether the page, added to a home screen from this browser, opens without the system's bars. */
  fullscreen: boolean;
};

/** Wind estimated at the standard 10 m, or as the anemometer measured it at its own height. */
export type WindHeight = "10m" | "sensor";

/** A column of the rooms table, and which way it runs. */
export type RoomSort = { column: string; descending: boolean };

export const DEFAULTS: Prefs = {
  station: null,
  units: {},
  view: "temperature",
  range: "24h",
  period: "today",
  model: false,
  rooms: null,
  wind: "10m",
  theme: "system",
  sunTheme: null,
  fullscreen: false,
};

const KEY = "ecowitt-dashboard";

/**
 * The browser's storage, or undefined where it refuses it: with cookies blocked, merely reading
 * window.localStorage throws, which as a default argument would throw before any try around its
 * use.
 */
export function browserStorage(): Storage | undefined {
  try {
    return globalThis.localStorage;
  } catch {
    return undefined;
  }
}

/** The saved choices, each missing or malformed one replaced by its default. */
export function load(storage: Storage | undefined = browserStorage()): Prefs {
  try {
    const saved = JSON.parse(storage?.getItem(KEY) ?? "{}") as Partial<Prefs>;
    if (typeof saved !== "object" || saved === null) return { ...DEFAULTS };
    return {
      station: typeof saved.station === "string" ? saved.station : DEFAULTS.station,
      units: saved.units && typeof saved.units === "object" ? saved.units : DEFAULTS.units,
      view: typeof saved.view === "string" ? saved.view : DEFAULTS.view,
      range: typeof saved.range === "string" ? saved.range : DEFAULTS.range,
      period: typeof saved.period === "string" ? saved.period : DEFAULTS.period,
      model: typeof saved.model === "boolean" ? saved.model : DEFAULTS.model,
      rooms: roomSort(saved.rooms),
      wind: saved.wind === "10m" || saved.wind === "sensor" ? saved.wind : DEFAULTS.wind,
      theme: THEME_CHOICES.includes(saved.theme as ThemeChoice) ? (saved.theme as ThemeChoice) : DEFAULTS.theme,
      sunTheme: saved.sunTheme === "light" || saved.sunTheme === "dark" ? saved.sunTheme : DEFAULTS.sunTheme,
      fullscreen: typeof saved.fullscreen === "boolean" ? saved.fullscreen : DEFAULTS.fullscreen,
    };
  } catch {
    return { ...DEFAULTS };
  }
}

/** A saved rooms order, or null for anything that is not one. */
function roomSort(saved: unknown): RoomSort | null {
  if (typeof saved !== "object" || saved === null) return null;
  const { column, descending } = saved as Partial<RoomSort>;
  return typeof column === "string" && typeof descending === "boolean" ? { column, descending } : null;
}

/** Remember the choices, if this browser lets the page. */
export function save(prefs: Prefs, storage: Storage | undefined = browserStorage()): void {
  try {
    storage?.setItem(KEY, JSON.stringify(prefs));
  } catch {
    // Nothing to do: the page works the same, it just forgets on reload.
  }
}
