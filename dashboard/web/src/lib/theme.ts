/**
 * Light or dark: the system's choice, a fixed one, or the sun's -- dark from sunset to sunrise at
 * the station, which suits a screen left on a wall, and a browser too old to know the system's.
 */

import type { Sun } from "./api";

/** What the visitor chose: follow the system, always light or dark, or follow the sun. */
export type ThemeChoice = "system" | "light" | "dark" | "sun";

/** The theme the page shows; null leaves it to the system. */
export type Theme = "light" | "dark" | null;

export const THEME_CHOICES: readonly ThemeChoice[] = ["system", "light", "dark", "sun"];

/**
 * The theme for a choice at a moment. Following the sun needs the station's sunrise and sunset
 * for its current day, or the polar day or night that has none; without them it is the system's.
 */
export function themeAt(choice: ThemeChoice, sun: Sun | null, now: Date): Theme {
  if (choice === "light" || choice === "dark") return choice;
  if (choice !== "sun" || !sun) return null;
  if (sun.polar) return sun.polar === "day" ? "light" : "dark";
  if (!sun.sunrise || !sun.sunset) return null;
  const t = now.getTime();
  return t >= Date.parse(sun.sunrise) && t < Date.parse(sun.sunset) ? "light" : "dark";
}

/**
 * Show a theme: `data-theme` on the root element, which app.css keys its colours on, and the
 * browser's bar in the page's background. Null hands both back to the system: the bar to the
 * colours index.html gives each scheme, kept on each tag as it is first overridden.
 */
export function applyTheme(theme: Theme, root: HTMLElement = document.documentElement): void {
  if (theme) root.dataset.theme = theme;
  else delete root.dataset.theme;
  const background = theme ? getComputedStyle(root).getPropertyValue("--bg").trim() : "";
  root.ownerDocument.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]').forEach((tag) => {
    if (tag.dataset.scheme === undefined) tag.dataset.scheme = tag.content;
    tag.content = background || tag.dataset.scheme;
  });
}
