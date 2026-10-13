import { describe, expect, it } from "vitest";
import { dewPointLevel, humidityLevel } from "./levels";

describe("humidityLevel", () => {
  it.each([
    [10, "bad", "Very dry"],
    [24.9, "bad", "Very dry"],
    [25, "warn", "Dry"],
    [39.9, "warn", "Dry"],
    [40, "good", "Comfortable"],
    [74.9, "good", "Comfortable"],
    [75, "cool", "Humid"],
    [94.9, "cool", "Humid"],
    [95, "warn", "Very humid: fog likely"],
  ] as const)("%s%% is %s", (pct, tone, words) => {
    expect(humidityLevel(pct)).toEqual({ fill: pct, tone, words });
  });

  it("fills no further than the bar", () => {
    expect(humidityLevel(104).fill).toBe(100);
    expect(humidityLevel(-1).fill).toBe(0);
  });
});

describe("dewPointLevel", () => {
  it.each([
    [9.9, "cool", "Dry, crisp"],
    [10, "good", "Comfortable"],
    [15.9, "good", "Comfortable"],
    [16, "warn", "Muggy"],
    [20.9, "warn", "Muggy"],
    [21, "bad", "Oppressive"],
  ] as const)("%s °C is %s", (c, tone, words) => {
    expect(dewPointLevel(c, "c")).toMatchObject({ tone, words });
  });

  it("fills from -5 °C to 25 °C, and no further", () => {
    expect(dewPointLevel(-5, "c").fill).toBe(0);
    expect(dewPointLevel(10, "c").fill).toBe(50);
    expect(dewPointLevel(25, "c").fill).toBe(100);
    expect(dewPointLevel(-20, "c").fill).toBe(0);
    expect(dewPointLevel(30, "c").fill).toBe(100);
  });

  it("reads a Fahrenheit dew point on the same scale", () => {
    // 60.8 °F is 16 °C, muggy, half way up the bar plus a fifth.
    expect(dewPointLevel(60.8, "f")).toMatchObject({ tone: "warn", words: "Muggy" });
    expect(dewPointLevel(50, "f").fill).toBeCloseTo(50);
  });
});
