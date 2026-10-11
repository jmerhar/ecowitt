import { describe, expect, it } from "vitest";
import { ago, axisLabels, clock, duration, moment, number, quantity, uvRisk } from "./format";
import { SYMBOLS } from "../testing";

describe("number", () => {
  it("shows each unit to the precision it is worth", () => {
    expect(number(1019.66, "hpa", "en-GB")).toBe("1,019.7");
    expect(number(29.921, "inhg", "en-GB")).toBe("29.92");
    expect(number(62.4, "pct", "en-GB")).toBe("62");
    expect(number(5, "c", "en-GB")).toBe("5.0");
  });

  it("shows nothing as an en dash", () => {
    expect(number(null)).toBe("–");
    expect(number(undefined)).toBe("–");
    expect(number(Number.NaN)).toBe("–");
  });
});

describe("quantity", () => {
  it("puts a space before units but not before % or °", () => {
    expect(quantity(17.6, "c", SYMBOLS, "en-GB")).toBe("17.6 °C");
    expect(quantity(62, "pct", SYMBOLS, "en-GB")).toBe("62%");
    expect(quantity(135, "deg", SYMBOLS, "en-GB")).toBe("135°");
  });

  it("leaves a unitless or missing value bare", () => {
    expect(quantity(4, "", SYMBOLS, "en-GB")).toBe("4");
    expect(quantity(null, "c", SYMBOLS)).toBe("–");
    expect(quantity(3, "parsec", SYMBOLS, "en-GB")).toBe("3.0");
  });
});

describe("times", () => {
  it("are shown in the station's zone", () => {
    expect(clock("2026-10-10T13:05:00Z", "Europe/Lisbon", "en-GB")).toBe("14:05");
    expect(moment("2026-10-09T13:05:00Z", "Europe/Lisbon", "en-GB")).toBe("9 Oct, 14:05");
    expect(clock(null, "UTC")).toBe("–");
    expect(moment(undefined, "UTC")).toBe("–");
  });

  it("are said relative to now", () => {
    const now = new Date("2026-10-10T14:00:00Z");
    expect(ago("2026-10-10T13:59:00Z", now)).toBe("just now");
    expect(ago("2026-10-10T13:30:00Z", now)).toBe("30 min ago");
    expect(ago("2026-10-10T09:00:00Z", now)).toBe("5 h ago");
    expect(ago("2026-10-07T14:00:00Z", now)).toBe("3 days ago");
    expect(ago(null, now)).toBe("never");
    expect(ago("2026-10-10T15:00:00Z", now)).toBe("just now");
    expect(ago("2026-10-10T13:59:00Z")).toMatch(/ago|just now/);
  });

  it("give durations in hours and minutes", () => {
    expect(duration(41100)).toBe("11 h 25 min");
    expect(duration(1500)).toBe("25 min");
    expect(duration(null)).toBe("–");
  });
});

describe("axisLabels", () => {
  const midnight = Date.UTC(2026, 9, 9, 23) / 1000; // 00:00 on 10 Oct in Lisbon
  it("gives times, with the date on the first label and at midnight", () => {
    expect(axisLabels([midnight - 7200, midnight, midnight + 7200], 7200, "Europe/Lisbon")).toEqual([
      "22:00\n9 Oct", "00:00\n10 Oct", "02:00",
    ]);
  });

  it("gives dates alone for steps of a day or more", () => {
    expect(axisLabels([midnight, midnight + 86400], 86400, "Europe/Lisbon")).toEqual(["10 Oct", "11 Oct"]);
  });
});

describe("uvRisk", () => {
  it.each([
    [0, "Low"], [2.9, "Low"], [3, "Moderate"], [6, "High"], [8, "Very high"], [11, "Extreme"],
  ])("%s is %s", (index, words) => {
    expect(uvRisk(index)).toBe(words);
  });

  it("says nothing without a reading", () => {
    expect(uvRisk(null)).toBe("");
  });
});
