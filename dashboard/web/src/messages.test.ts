import { catalogueProblems } from "@jmerhar/jigkit/i18n/testing";
import { describe, expect, it } from "vitest";
import { m } from "./paraglide/messages.js";
import en from "../messages/en.json";
import pt from "../messages/pt-PT.json";

describe("the page's messages", () => {
  // Paraglide falls back to English for a message a language lacks, so a missing one would show
  // up only as an English word on a Portuguese page. Portuguese may leave a placeholder out where
  // its phrasing does better without one ("hora da estação"), but never names one English lacks.
  it("are in every language, naming nothing their English does not", () => {
    expect(catalogueProblems({ en, "pt-PT": pt }, { allowFewer: true })).toEqual([]);
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
});
