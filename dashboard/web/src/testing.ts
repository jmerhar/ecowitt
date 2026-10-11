/** API answers for tests, shaped as the dashboard API gives them, and a stand-in Api. */
import { vi } from "vitest";
import type { Api, ExtremesOut, Meta, Now, SeriesOut, Station } from "./lib/api";

export const SYMBOLS: Record<string, string> = {
  c: "°C", f: "°F", hpa: "hPa", inhg: "inHg", mmhg: "mmHg", mm: "mm", in: "in",
  mm_h: "mm/h", in_h: "in/h", kmh: "km/h", ms: "m/s", mph: "mph", kn: "kn",
  km: "km", mi: "mi", pct: "%", deg: "°", wm2: "W/m²", "": "",
};

export const UNITS = { temperature: "c", pressure: "hpa", rain: "mm", wind: "kmh", distance: "km" };

export const META: Meta = {
  title: "Test weather",
  metrics: [
    { id: "outdoor.temperature", label: "Temperature", quantity: "temperature", unit: null, aggregates: ["mean", "min", "max"], extremes: "both", per_sensor: false },
    { id: "outdoor.dew_point", label: "Dew point", quantity: "temperature", unit: null, aggregates: ["mean", "min", "max"], extremes: "both", per_sensor: false },
    { id: "wind.gust", label: "Wind gust", quantity: "wind", unit: null, aggregates: ["max"], extremes: "max", per_sensor: false },
    { id: "rain.daily", label: "Rain today", quantity: "rain", unit: null, aggregates: ["max"], extremes: "max", per_sensor: false },
    { id: "rooms.temperature", label: "Temperature", quantity: "temperature", unit: null, aggregates: ["mean", "min", "max"], extremes: "both", per_sensor: true },
  ],
  units: {
    temperature: [{ code: "c", symbol: "°C" }, { code: "f", symbol: "°F" }],
    pressure: [{ code: "hpa", symbol: "hPa" }, { code: "inhg", symbol: "inHg" }],
    rain: [{ code: "mm", symbol: "mm" }, { code: "in", symbol: "in" }],
    wind: [{ code: "kmh", symbol: "km/h" }, { code: "mph", symbol: "mph" }],
    distance: [{ code: "km", symbol: "km" }],
  },
  symbols: SYMBOLS,
  ranges: ["24h", "7d", "30d", "1y"],
  periods: ["today", "month", "year"],
};

export const STATION: Station = {
  id: "Home", latitude: 38.72, longitude: -9.14, altitude_m: 100, timezone: "Europe/Lisbon", units: UNITS,
};

export function now(overrides: Partial<Now> = {}): Now {
  return {
    station: "Home",
    time: "2026-10-10T13:59:00Z",
    online: true,
    timezone: "Europe/Lisbon",
    units: UNITS,
    summary: "18 °C. Gentle breeze from the SE.",
    outdoor: {
      temperature: 18, humidity: 70, dew_point: 12.5, feels_like: 16,
      high: { value: 21, time: "2026-10-10T13:00:00Z" }, low: { value: 9.5, time: "2026-10-10T06:00:00Z" },
    },
    wind: {
      speed: 15, gust: 25, direction: 135, compass: "SE", beaufort: 3, description: "Gentle breeze",
      max_gust_today: { value: 52, time: "2026-10-10T10:00:00Z" },
    },
    rain: {
      gauge: "bucket", rate: 0, event: 0, hourly: 0, daily: 1.2, last_24h: 3.5, weekly: 9,
      monthly: 20, yearly: 400, raining: false,
    },
    pressure: {
      sea_level: 1012, absolute: 1000, relative: 1013,
      trend: { change: -3, hours: 3, tendency: "falling" },
    },
    sun: {
      radiation: 450, uv_index: 4, sunrise: "2026-10-10T06:42:00Z", noon: "2026-10-10T12:24:00Z",
      sunset: "2026-10-10T18:07:00Z", daylight_s: 41100, polar: null,
    },
    rooms: [
      { sensor: "indoor", name: "Lounge", temperature: 21, humidity: 55, dew_point: 11.9,
        airing: { advice: "no_need", humidity_after: 58, dew_point_difference: 0.3 } },
      { sensor: "ch1", name: "Bathroom", temperature: 20, humidity: 75, dew_point: 15.4,
        airing: { advice: "open", humidity_after: 49, dew_point_difference: 2.9 } },
      { sensor: "ch2", name: "Attic", temperature: 19, humidity: 70, dew_point: 13.4,
        airing: { advice: "keep_closed", humidity_after: 71, dew_point_difference: 0.2 } },
    ],
    sensors: [
      { sensor: "outdoor", name: "Outdoor", battery_low: false, unchanged_s: 0, updating: true },
      { sensor: "ch1", name: "Bathroom", battery_low: true, unchanged_s: 20000, updating: false },
    ],
    ...overrides,
  };
}

export function series(overrides: Partial<SeriesOut> = {}): SeriesOut {
  return {
    station: "Home", range: "24h", step_s: 300, start: "2026-10-09T14:00:00Z", end: "2026-10-10T14:00:00Z",
    units: UNITS,
    series: [
      { metric: "outdoor.temperature", sensor: "outdoor", name: "Outdoor", unit: "c", t: [100, 400, 700],
        values: { mean: [10, 11, 12], min: [9, 10, 11], max: [11, 12, 13] } },
      { metric: "outdoor.dew_point", sensor: "outdoor", name: "Outdoor", unit: "c", t: [100, 700],
        values: { mean: [5, 6], min: [4, 5], max: [6, 7] } },
    ],
    ...overrides,
  };
}

export function extremes(overrides: Partial<ExtremesOut> = {}): ExtremesOut {
  return {
    station: "Home", period: "today", start: "2026-10-09T23:00:00Z", end: "2026-10-10T14:00:00Z",
    units: UNITS,
    extremes: [
      { metric: "outdoor.temperature", sensor: "outdoor", name: "Outdoor", unit: "c",
        min: { value: 9.5, time: "2026-10-10T06:00:00Z" }, max: { value: 21, time: "2026-10-10T13:00:00Z" } },
      { metric: "wind.gust", sensor: null, name: null, unit: "kmh", min: null,
        max: { value: 52, time: "2026-10-10T10:00:00Z" } },
      { metric: "rain.daily", sensor: "bucket", name: null, unit: "mm", min: null,
        max: { value: 0, time: "2026-10-10T00:00:00Z" } },
      { metric: "rooms.temperature", sensor: "ch1", name: "Bathroom", unit: "c",
        min: { value: 17.2, time: "2026-10-10T05:00:00Z" }, max: { value: 22, time: "2026-10-10T12:00:00Z" } },
    ],
    ...overrides,
  };
}

/** An Api whose every method is a mock answering from the fixtures above. */
export function fakeApi(): Api & Record<"meta" | "stations" | "now" | "series" | "extremes", ReturnType<typeof vi.fn>> {
  return {
    meta: vi.fn(async () => META),
    stations: vi.fn(async () => [STATION]),
    now: vi.fn(async () => now()),
    series: vi.fn(async () => series()),
    extremes: vi.fn(async () => extremes()),
  } as never;
}
