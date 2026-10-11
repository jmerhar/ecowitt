/**
 * What a visitor chose last time -- station, units, chart -- kept in this browser only. Storage
 * can be missing or refuse (private windows, blocked site data), so every access is guarded and
 * the defaults stand in.
 */

import type { UnitChoice } from "./api";

export type Prefs = {
  station: string | null;
  units: UnitChoice;
  view: string;
  range: string;
  period: string;
};

export const DEFAULTS: Prefs = {
  station: null,
  units: {},
  view: "temperature",
  range: "24h",
  period: "today",
};

const KEY = "ecowitt-dashboard";

/** The saved choices, each missing or malformed one replaced by its default. */
export function load(storage: Storage | undefined = globalThis.localStorage): Prefs {
  try {
    const saved = JSON.parse(storage?.getItem(KEY) ?? "{}") as Partial<Prefs>;
    if (typeof saved !== "object" || saved === null) return { ...DEFAULTS };
    return {
      station: typeof saved.station === "string" ? saved.station : DEFAULTS.station,
      units: saved.units && typeof saved.units === "object" ? saved.units : DEFAULTS.units,
      view: typeof saved.view === "string" ? saved.view : DEFAULTS.view,
      range: typeof saved.range === "string" ? saved.range : DEFAULTS.range,
      period: typeof saved.period === "string" ? saved.period : DEFAULTS.period,
    };
  } catch {
    return { ...DEFAULTS };
  }
}

/** Remember the choices, if this browser lets the page. */
export function save(prefs: Prefs, storage: Storage | undefined = globalThis.localStorage): void {
  try {
    storage?.setItem(KEY, JSON.stringify(prefs));
  } catch {
    // Nothing to do: the page works the same, it just forgets on reload.
  }
}
