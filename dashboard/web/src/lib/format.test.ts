import { describe, expect, it } from "vitest";
import {
  ago, axisLabels, clock, coming, dayLabel, duration, hourOf, moment, number, quantity, today, uvRisk, whichDay, whole, zoneCity,
} from "./format";
import { speaking } from "../testing";
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

describe("today", () => {
  it("gives the weekday, date and time at the station", () => {
    expect(today("2026-10-11T23:30:00Z", "Europe/Lisbon")).toBe("Mon 12 Oct, 00:30");
  });
});

describe("zoneCity", () => {
  it.each([
    ["Europe/Lisbon", "Lisbon"], ["America/New_York", "New York"],
    ["America/Argentina/Buenos_Aires", "Buenos Aires"], ["UTC", "UTC"],
  ])("%s is %s", (zone, city) => {
    expect(zoneCity(zone)).toBe(city);
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


describe("coming and dayLabel", () => {
  // 10 Oct, 15:00 in Lisbon.
  const now = new Date("2026-10-10T14:00:00Z");

  it("name today, tomorrow and later days in the station's time", () => {
    expect(dayLabel("2026-10-10T20:00:00Z", "Europe/Lisbon", now)).toBe("Today");
    // 23:30 UTC is already the 11th in Lisbon.
    expect(dayLabel("2026-10-10T23:30:00Z", "Europe/Lisbon", now)).toBe("Tomorrow");
    expect(dayLabel("2026-10-12T10:00:00Z", "Europe/Lisbon", now)).toBe("Mon 12 Oct");
  });

  it("tell today, tomorrow and other days apart by the station's calendar, not by their words", () => {
    expect(whichDay("2026-10-10T22:59:00Z", "Europe/Lisbon", now)).toBe("today");
    expect(whichDay("2026-10-10T23:00:00Z", "Europe/Lisbon", now)).toBe("tomorrow");
    expect(whichDay("2026-10-11T22:59:00Z", "Europe/Lisbon", now)).toBe("tomorrow");
    expect(whichDay("2026-10-11T23:00:00Z", "Europe/Lisbon", now)).toBe("other");
    expect(whichDay("2026-10-09T12:00:00Z", "Europe/Lisbon", now)).toBe("other");
  });

  it("name tomorrow by the calendar on the days the clocks change", () => {
    // 23:30 on Saturday 28 Mar: 24 hours on is Monday, since Sunday is 23 hours long.
    const spring = new Date("2026-03-28T23:30:00Z");
    expect(dayLabel("2026-03-29T12:00:00Z", "Europe/Lisbon", spring)).toBe("Tomorrow");
    expect(dayLabel("2026-03-30T12:00:00Z", "Europe/Lisbon", spring)).toBe("Mon 30 Mar");
    // 00:30 on Sunday 25 Oct: 24 hours on is still Sunday, which is 25 hours long.
    const autumn = new Date("2026-10-24T23:30:00Z");
    expect(dayLabel("2026-10-26T12:00:00Z", "Europe/Lisbon", autumn)).toBe("Tomorrow");
  });

  it("give a time to come with its day when it is not today", () => {
    expect(coming("2026-10-10T17:00:00Z", "Europe/Lisbon", now)).toBe("18:00");
    expect(coming("2026-10-11T05:00:00Z", "Europe/Lisbon", now)).toBe("tomorrow 06:00");
    expect(coming("2026-10-13T05:00:00Z", "Europe/Lisbon", now)).toBe("Tue 13 Oct, 06:00");
  });
});

describe("whole", () => {
  it("rounds to a whole number with the unit's symbol", () => {
    expect(whole(17.6, "c", SYMBOLS)).toBe("18 °C");
    expect(whole(69.5, "pct", SYMBOLS)).toBe("70%");
    expect(whole(3.2, "", SYMBOLS)).toBe("3");
    expect(whole(null, "c", SYMBOLS)).toBe("–");
  });
});

describe("in European Portuguese", () => {
  // 10 Oct, 15:00 in Lisbon.
  const now = new Date("2026-10-10T14:00:00Z");

  it("names a time to come with the article its hour takes", () => {
    speaking("pt-PT");
    expect(coming("2026-10-10T17:00:00Z", "Europe/Lisbon", now)).toBe("hoje às 18:00");
    expect(coming("2026-10-11T00:30:00Z", "Europe/Lisbon", now)).toBe("amanhã à 01:30");
    expect(coming("2026-10-10T23:30:00Z", "Europe/Lisbon", now)).toBe("amanhã às 00:30");
    expect(coming("2026-10-13T05:00:00Z", "Europe/Lisbon", now)).toMatch(/^ter[^,]*, 13\/10 às 06:00$/);
  });

  it("writes how long ago, days and numbers the Portuguese way", () => {
    speaking("pt-PT");
    expect(ago("2026-10-10T13:55:00Z", now)).toBe("há 5 min");
    expect(dayLabel("2026-10-11T10:00:00Z", "Europe/Lisbon", now)).toBe("Amanhã");
    expect(number(2.4, "mm")).toBe("2,4");
    expect(uvRisk(9)).toBe("Muito elevado");
  });
});

describe("hourOf", () => {
  it("gives the hour at the station, midnight as 0", () => {
    expect(hourOf("2026-10-10T23:30:00Z", "Europe/Lisbon")).toBe(0);
    expect(hourOf("2026-10-11T00:15:00Z", "Europe/Lisbon")).toBe(1);
    expect(hourOf("2026-10-10T12:00:00Z", "UTC")).toBe(12);
  });
});
