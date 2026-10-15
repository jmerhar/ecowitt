/**
 * How the outdoor humidity and dew point read at a glance: how full their bars are, and which
 * colour they take. Humidity says how near the air is to fog and condensation; the dew point, how
 * muggy it feels, whatever the temperature.
 */

import { m } from "../paraglide/messages.js";

/** A bar's fill, 0 to 100, its colour class, and the level in words. */
export type Level = { fill: number; tone: "bad" | "warn" | "good" | "cool"; words: string };

const clamp = (value: number) => Math.min(100, Math.max(0, value));

/**
 * Relative humidity, in %. The outer lines are the outdoor card's own warnings (very dry air,
 * fog likely); humid air between them is coloured as information, not as a fault, since a coast
 * spends much of its time there.
 */
export function humidityLevel(pct: number): Level {
  const fill = clamp(pct);
  if (pct < 25) return { fill, tone: "bad", words: m.level_very_dry() };
  if (pct < 40) return { fill, tone: "warn", words: m.level_dry() };
  if (pct < 75) return { fill, tone: "good", words: m.level_comfortable() };
  if (pct < 95) return { fill, tone: "cool", words: m.level_humid() };
  return { fill, tone: "warn", words: m.level_fog_likely() };
}

/** The dew point scale's ends, in °C: an empty bar and a full one. */
const DEW_EMPTY_C = -5;
const DEW_FULL_C = 25;

/**
 * The dew point, in the unit given ("c" or "f"), on the US National Weather Service's comfort
 * scale; the bar fills from -5 °C to 25 °C.
 */
export function dewPointLevel(value: number, unit: string): Level {
  const c = unit === "f" ? ((value - 32) * 5) / 9 : value;
  const fill = clamp(((c - DEW_EMPTY_C) / (DEW_FULL_C - DEW_EMPTY_C)) * 100);
  if (c < 10) return { fill, tone: "cool", words: m.level_crisp() };
  if (c < 16) return { fill, tone: "good", words: m.level_comfortable() };
  if (c < 21) return { fill, tone: "warn", words: m.level_muggy() };
  return { fill, tone: "bad", words: m.level_oppressive() };
}
