/** API answers for tests, shaped as the dashboard API gives them, and a stand-in Api. */
import { onTestFinished, vi } from "vitest";
import { getLocale, overwriteGetLocale, type Locale } from "./paraglide/runtime.js";
import type {
  Api, ExtremesOut, ForecastHour, ForecastOut, Meta, Now, SeriesOut, Station,
} from "./lib/api";

export const SYMBOLS: Record<string, string> = {
  c: "°C", f: "°F", hpa: "hPa", inhg: "inHg", mmhg: "mmHg", mm: "mm", in: "in",
  mm_h: "mm/h", in_h: "in/h", kmh: "km/h", ms: "m/s", mph: "mph", kn: "kn",
  km: "km", mi: "mi", pct: "%", deg: "°", wm2: "W/m²", "": "",
};

export const UNITS = { temperature: "c", pressure: "hpa", rain: "mm", wind: "kmh", distance: "km" };

export const META: Meta = {
  title: "Test weather",
  version: "2.8.0",
  metrics: [
    { id: "outdoor.temperature", label: "Temperature", quantity: "temperature", unit: null, aggregates: ["mean", "min", "max"], extremes: "both", per_sensor: false, model: true },
    { id: "outdoor.dew_point", label: "Dew point", quantity: "temperature", unit: null, aggregates: ["mean", "min", "max"], extremes: "both", per_sensor: false, model: true },
    { id: "wind.gust", label: "Wind gust", quantity: "wind", unit: null, aggregates: ["max"], extremes: "max", per_sensor: false, model: true },
    { id: "wind.measured_gust", label: "Wind gust, measured", quantity: "wind", unit: null, aggregates: ["max"], extremes: "max", per_sensor: false, model: false },
    { id: "rain.daily", label: "Rain today", quantity: "rain", unit: null, aggregates: ["max"], extremes: "max", per_sensor: false, model: false },
    { id: "rooms.temperature", label: "Temperature", quantity: "temperature", unit: null, aggregates: ["mean", "min", "max"], extremes: "both", per_sensor: true, model: false },
  ],
  units: {
    temperature: [{ code: "c", symbol: "°C" }, { code: "f", symbol: "°F" }],
    pressure: [{ code: "hpa", symbol: "hPa" }, { code: "inhg", symbol: "inHg" }],
    rain: [{ code: "mm", symbol: "mm" }, { code: "in", symbol: "in" }],
    wind: [{ code: "kmh", symbol: "km/h" }, { code: "mph", symbol: "mph" }],
    distance: [{ code: "km", symbol: "km" }],
  },
  symbols: SYMBOLS,
  ranges: ["1h", "3h", "6h", "12h", "24h", "7d", "30d", "1y"],
  periods: ["today", "month", "year"],
};

export const STATION: Station = {
  id: "Home", latitude: 38.72, longitude: -9.14, altitude_m: 100, timezone: "Europe/Lisbon", units: UNITS,
  weather_model: null,
  wind_factor: 1,
};

export function now(overrides: Partial<Now> = {}): Now {
  return {
    station: "Home",
    time: "2026-10-10T13:59:00Z",
    online: true,
    timezone: "Europe/Lisbon",
    units: UNITS,
    summary: "18 °C. Gentle breeze from the SE.",
    summary_parts: [
      { code: "temperature", text: "18 °C" },
      { code: "wind", text: "Gentle breeze from the SE" },
    ],
    sky: null,
    outdoor: {
      temperature: 18, humidity: 70, dew_point: 12.5, feels_like: 16,
      high: { value: 21, time: "2026-10-10T13:00:00Z" }, low: { value: 9.5, time: "2026-10-10T06:00:00Z" },
    },
    wind: {
      speed: 15, gust: 25, direction: 135, compass: "SE", beaufort: 3, description: "Gentle breeze",
      max_gust_today: { value: 52, time: "2026-10-10T10:00:00Z" },
      source: null, height_factor: 1, measured_speed: 15, measured_gust: 25,
      measured_max_gust_today: { value: 52, time: "2026-10-10T10:00:00Z" },
      measured_beaufort: 3, measured_description: "Gentle breeze",
    },
    rain: {
      gauge: "bucket", rate: 0, event: 0, hourly: 0, daily: 1.2, last_24h: 3.5, weekly: 9,
      monthly: 20, yearly: 400, raining: false,
    },
    pressure: {
      sea_level: 1012, absolute: 1000, relative: 1013,
      trend: { change: -3, hours: 3, code: "falling", tendency: "falling" },
    },
    sun: {
      radiation: 450, uv_index: 4, sunrise: "2026-10-10T06:42:00Z", noon: "2026-10-10T12:24:00Z",
      sunset: "2026-10-10T18:07:00Z", daylight_s: 41100, polar: null,
    },
    airing: {
      advice: "open", rooms: ["Bathroom"], humidity: 70, humidity_after: 58, dew_point_difference: 0.3,
      drier_from: null,
    },
    rooms: [
      { sensor: "indoor", name: "Lounge", temperature: 21, humidity: 55, dew_point: 11.9,
        airing: { advice: "no_need", humidity_after: 58, dew_point_difference: 0.3 }, flags: [] },
      { sensor: "ch1", name: "Bathroom", temperature: 20, humidity: 75, dew_point: 15.4,
        airing: { advice: "open", humidity_after: 49, dew_point_difference: 2.9 }, flags: ["damp"] },
      { sensor: "ch2", name: "Attic", temperature: 19, humidity: 70, dew_point: 13.4,
        airing: { advice: "keep_closed", humidity_after: 76, dew_point_difference: -1.2 }, flags: ["cold"] },
    ],
    sensors: [
      { sensor: "outdoor", name: "Outdoor", battery_low: false, unchanged_s: 0, updating: true },
      { sensor: "ch1", name: "Bathroom", battery_low: true, unchanged_s: 20000, updating: false },
    ],
    notices: {
      airing: { level: "good", items: [], text: "" },
      rooms: {
        level: "warning",
        items: [
          { code: "room_flag", value: null, unit: null, time: null, flag: "damp", rooms: ["Bathroom"], text: "Damp: Bathroom." },
          { code: "room_flag", value: null, unit: null, time: null, flag: "cold", rooms: ["Attic"], text: "Cold: Attic." },
        ],
        text: "Damp: Bathroom. Cold: Attic.",
      },
      sensors: { level: "warning", items: [], text: "" },
    },
    ...overrides,
  };
}

export function series(overrides: Partial<SeriesOut> = {}): SeriesOut {
  return {
    station: "Home", range: "24h", step_s: 300, start: "2026-10-09T14:00:00Z", end: "2026-10-10T14:00:00Z",
    units: UNITS,
    series: [
      { metric: "outdoor.temperature", sensor: "outdoor", name: "Outdoor", unit: "c", source: "station", t: [100, 400, 700],
        values: { mean: [10, 11, 12], min: [9, 10, 11], max: [11, 12, 13] } },
      { metric: "outdoor.dew_point", sensor: "outdoor", name: "Outdoor", unit: "c", source: "station", t: [100, 700],
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
      { metric: "wind.measured_gust", sensor: null, name: null, unit: "kmh", min: null,
        max: { value: 26, time: "2026-10-10T10:00:00Z" } },
      { metric: "rain.daily", sensor: "bucket", name: null, unit: "mm", min: null,
        max: { value: 0, time: "2026-10-10T00:00:00Z" } },
      { metric: "rooms.temperature", sensor: "ch1", name: "Bathroom", unit: "c",
        min: { value: 17.2, time: "2026-10-10T05:00:00Z" }, max: { value: 22, time: "2026-10-10T12:00:00Z" } },
    ],
    ...overrides,
  };
}

/** An Api whose every method is a mock answering from the fixtures above. */
export function fakeApi(): Api & Record<"meta" | "stations" | "now" | "series" | "extremes" | "forecast", ReturnType<typeof vi.fn>> {
  return {
    meta: vi.fn(async () => META),
    stations: vi.fn(async () => [STATION]),
    now: vi.fn(async () => now()),
    series: vi.fn(async () => series()),
    extremes: vi.fn(async () => extremes()),
    forecast: vi.fn(async () => forecast()),
  } as never;
}

/** A forecast made at 13:00 UTC on 10 Oct: three hours and two days. */
export function forecast(overrides: Partial<ForecastOut> = {}): ForecastOut {
  const hour = (time: string, temperature: number, chance: number, code: number, is_day: boolean): ForecastHour => ({
    time, temperature, humidity: 70, dew_point: 12, precipitation: 0, precipitation_probability: chance,
    weather_code: code, description: code === 61 ? "Light rain" : "Overcast", is_day,
    wind_speed: 14.6, wind_gust: 30.2, wind_direction: 350, compass: "N",
  });
  return {
    station: "Home",
    model: { id: "best_match", label: "Best for this location" },
    issued: "2026-10-10T13:00:00Z",
    units: UNITS,
    hours: [
      hour("2026-10-10T14:00:00Z", 17.6, 0, 3, true),
      hour("2026-10-10T15:00:00Z", 16.4, 70, 61, true),
      hour("2026-10-10T20:00:00Z", 13.2, 5, 3, false),
    ],
    days: [
      { date: "2026-10-09T23:00:00Z", weather_code: 61, description: "Light rain", temperature_max: 21.4,
        temperature_min: 12.6, precipitation: 2.4, precipitation_probability: 70, wind_speed_max: 20,
        wind_gust_max: 41.3, wind_direction: 350, compass: "N", uv_index_max: 5, humidity: 78 },
      { date: "2026-10-10T23:00:00Z", weather_code: 3, description: "Overcast", temperature_max: 19,
        temperature_min: 11, precipitation: 0, precipitation_probability: 5, wind_speed_max: 12,
        wind_gust_max: 20, wind_direction: 10, compass: "N", uv_index_max: 4, humidity: null },
    ],
    ...overrides,
  };
}

/** Paraglide's own getLocale, which follows the page's strategies. */
const pageLocale = getLocale;

/** Renders the rest of the calling test in `locale`; the page's own language returns after it. */
export function speaking(locale: Locale): void {
  overwriteGetLocale(() => locale);
  onTestFinished(() => overwriteGetLocale(pageLocale));
}
