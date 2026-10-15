import { describe, expect, it } from "vitest";
import { m } from "./paraglide/messages.js";
import en from "../messages/en.json";
import pt from "../messages/pt-PT.json";

/** Every text a message can give: a plain string, or each of its variants. */
function texts(message: unknown): string[] {
  if (typeof message === "string") return [message];
  return (message as { match: Record<string, string> }[]).flatMap((m) => Object.values(m.match));
}

/** The placeholders in a text. */
function placeholders(text: string): Set<string> {
  return new Set(text.match(/{\w+}/g) ?? []);
}

describe("the page's messages", () => {
  // Paraglide falls back to English for a message a language lacks, so a missing one would show
  // up only as an English word on a Portuguese page.
  it("are in every language", () => {
    expect(Object.keys(pt)).toEqual(Object.keys(en));
  });

  it.each([
    ["today_at", { time: "", day: "", value: "", model: "" }],
    ["tomorrow_at", {}],
    ["day_at", { day: "terça, 13/10" }],
    ["at_time", {}],
    ["value_at_time", { value: "72 km/h" }],
    ["forecast_source", { model: "ICON" }],
    ["sky_from_model", {}],
  ] as const)("put %s's time with the article its hour takes in Portuguese", (key, inputs) => {
    const say = m[key] as (inputs: object, options: { locale: "pt-PT" }) => string;
    const one = say({ ...inputs, time: "01:30", hour: 1 }, { locale: "pt-PT" });
    const other = say({ ...inputs, time: "13:30", hour: 13 }, { locale: "pt-PT" });
    expect(one).toMatch(/(^|\s)(à|a) 01:30/);
    expect(other).toMatch(/(^|\s)(às|as) 13:30/);
  });

  it("name nothing their English does not", () => {
    const english = en as Record<string, unknown>;
    const strays = Object.entries(pt as Record<string, unknown>).flatMap(([key, message]) => {
      if (key === "$schema") return [];
      const allowed = new Set(texts(english[key]).flatMap((text) => [...placeholders(text)]));
      return texts(message)
        .flatMap((text) => [...placeholders(text)])
        .filter((name) => !allowed.has(name))
        .map((name) => `${key}: ${name}`);
    });
    expect(strays).toEqual([]);
  });
});
