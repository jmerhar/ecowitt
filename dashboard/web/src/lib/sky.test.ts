import { describe, expect, it } from "vitest";
import clearDay from "@bybas/weather-icons/production/line/all/clear-day.svg";
import clearNight from "@bybas/weather-icons/production/line/all/clear-night.svg";
import fogDay from "@bybas/weather-icons/production/line/all/fog-day.svg";
import hail from "@bybas/weather-icons/production/line/all/hail.svg";
import notAvailable from "@bybas/weather-icons/production/line/all/not-available.svg";
import overcast from "@bybas/weather-icons/production/line/all/overcast.svg";
import partlyCloudyDayRain from "@bybas/weather-icons/production/line/all/partly-cloudy-day-rain.svg";
import partlyCloudyNight from "@bybas/weather-icons/production/line/all/partly-cloudy-night.svg";
import rain from "@bybas/weather-icons/production/line/all/rain.svg";
import { skyIcon } from "./sky";

describe("skyIcon", () => {
  it("shows the day's or the night's sky for a code", () => {
    expect(skyIcon(0, true)).toBe(clearDay);
    expect(skyIcon(0, false)).toBe(clearNight);
    expect(skyIcon(2, false)).toBe(partlyCloudyNight);
    expect(skyIcon(81, true)).toBe(partlyCloudyDayRain);
  });

  it("uses one icon where day and night look alike", () => {
    expect(skyIcon(3, true)).toBe(overcast);
    expect(skyIcon(3, false)).toBe(overcast);
    expect(skyIcon(63, false)).toBe(rain);
    expect(skyIcon(99, true)).toBe(hail);
  });

  it("takes the day when the model did not say, and admits a code it does not know", () => {
    expect(skyIcon(45, null)).toBe(fogDay);
    expect(skyIcon(42, true)).toBe(notAvailable);
  });
});
