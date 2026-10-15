import { afterEach, describe, expect, it } from "vitest";
import type { Sun } from "./api";
import { applyTheme, themeAt } from "./theme";
import css from "../app.css?raw";

const SUN: Sun = {
  radiation: null,
  uv_index: null,
  sunrise: "2026-10-10T06:42:00Z",
  noon: "2026-10-10T12:24:00Z",
  sunset: "2026-10-10T18:07:00Z",
  daylight_s: 41100,
  polar: null,
};

const at = (time: string) => new Date(`2026-10-10T${time}Z`);

describe("themeAt", () => {
  it.each([
    ["00:30:00", "dark"],
    ["06:41:59", "dark"],
    ["06:42:00", "light"],
    ["12:00:00", "light"],
    ["18:06:59", "light"],
    ["18:07:00", "dark"],
    ["23:59:00", "dark"],
  ] as const)("following the sun, %s is %s", (time, theme) => {
    expect(themeAt("sun", SUN, at(time))).toBe(theme);
  });

  it("stays light through a polar day and dark through a polar night", () => {
    const polar = { ...SUN, sunrise: null, sunset: null };
    expect(themeAt("sun", { ...polar, polar: "day" }, at("00:30:00"))).toBe("light");
    expect(themeAt("sun", { ...polar, polar: "night" }, at("12:00:00"))).toBe("dark");
  });

  it("leaves the sun's choice to the system when its times are missing", () => {
    expect(themeAt("sun", null, at("23:00:00"))).toBeNull();
    expect(themeAt("sun", { ...SUN, sunset: null }, at("23:00:00"))).toBeNull();
    expect(themeAt("sun", { ...SUN, sunrise: null }, at("03:00:00"))).toBeNull();
  });

  it("keeps a fixed choice whatever the sun does", () => {
    expect(themeAt("light", SUN, at("23:00:00"))).toBe("light");
    expect(themeAt("dark", SUN, at("12:00:00"))).toBe("dark");
    expect(themeAt("system", SUN, at("23:00:00"))).toBeNull();
  });
});

describe("applyTheme", () => {
  const root = document.documentElement;

  function tag(media: string, content: string): HTMLMetaElement {
    const meta = document.createElement("meta");
    meta.name = "theme-color";
    meta.media = media;
    meta.content = content;
    document.head.append(meta);
    return meta;
  }

  afterEach(() => {
    delete root.dataset.theme;
    root.style.removeProperty("--bg");
    document.head.querySelectorAll('meta[name="theme-color"]').forEach((m) => m.remove());
  });

  it("marks the root and paints the browser's bar in the page's background", () => {
    const light = tag("(prefers-color-scheme: light)", "#fbfaf7");
    const dark = tag("(prefers-color-scheme: dark)", "#16181a");
    root.style.setProperty("--bg", "#16181a");
    applyTheme("dark");
    expect(root.dataset.theme).toBe("dark");
    expect(light.content).toBe("#16181a");
    expect(dark.content).toBe("#16181a");
  });

  it("hands both back to the system, with each scheme's own colour", () => {
    const light = tag("(prefers-color-scheme: light)", "#fbfaf7");
    const dark = tag("(prefers-color-scheme: dark)", "#16181a");
    root.style.setProperty("--bg", "#fbfaf7");
    applyTheme("light");
    applyTheme("dark");
    applyTheme(null);
    expect(root.dataset.theme).toBeUndefined();
    expect(light.content).toBe("#fbfaf7");
    expect(dark.content).toBe("#16181a");
  });
});

describe("app.css", () => {
  /** A block's custom properties, in order, from the rule that opens with `selector {`. */
  function colours(selector: string): string[] {
    const start = css.indexOf(`${selector} {`);
    expect(start).toBeGreaterThan(-1);
    const block = css.slice(start, css.indexOf("}", start));
    return block.match(/--[\w-]+:\s*[^;]+/g) ?? [];
  }

  it("gives a chosen dark theme the colours of the system's", () => {
    const system = colours(':root:not([data-theme="light"])');
    expect(system.length).toBeGreaterThan(5);
    expect(colours(':root[data-theme="dark"]')).toEqual(system);
  });
});
