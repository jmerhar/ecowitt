/**
 * The dashboard API's answers, as its OpenAPI document (/api/v1/openapi.json) describes them,
 * and a client that fetches them. Values arrive converted and rounded; times are UTC.
 */

export type Units = {
  temperature: string;
  pressure: string;
  rain: string;
  wind: string;
  distance: string;
};

export type At = { value: number; time: string };

/** The weather model stored beside a station's readings. */
export type WeatherModel = { id: string; label: string };

export type Station = {
  id: string;
  latitude: number | null;
  longitude: number | null;
  altitude_m: number | null;
  timezone: string;
  units: Units;
  /** The weather model whose values /series can add, or null when the station has none. */
  weather_model: WeatherModel | null;
  /** What its measured wind is multiplied by to estimate it at 10 m; 1 with no correction. */
  wind_factor: number;
};

export type Outdoor = {
  temperature: number | null;
  humidity: number | null;
  dew_point: number | null;
  feels_like: number | null;
  high: At | null;
  low: At | null;
};

export type Wind = {
  speed: number | null;
  gust: number | null;
  direction: number | null;
  compass: string | null;
  beaufort: number | null;
  description: string | null;
  max_gust_today: At | null;
  /** Where the 10 m figures came from; null when they are the measured wind itself. */
  source: "sensor" | "model" | null;
  /** What measured wind is multiplied by for the estimate at 10 m; 1 with no correction. */
  height_factor: number;
  measured_speed: number | null;
  measured_gust: number | null;
  measured_max_gust_today: At | null;
};

export type Rain = {
  gauge: string | null;
  rate: number | null;
  event: number | null;
  hourly: number | null;
  daily: number | null;
  last_24h: number | null;
  weekly: number | null;
  monthly: number | null;
  yearly: number | null;
  raining: boolean;
};

export type Pressure = {
  sea_level: number | null;
  absolute: number | null;
  relative: number | null;
  trend: { change: number; hours: number; tendency: string } | null;
};

export type Sun = {
  radiation: number | null;
  uv_index: number | null;
  sunrise: string | null;
  noon: string | null;
  sunset: string | null;
  daylight_s: number | null;
  polar: "day" | "night" | null;
};

export type Room = {
  sensor: string;
  name: string;
  temperature: number | null;
  humidity: number | null;
  dew_point: number | null;
  airing: {
    advice: "open" | "keep_closed" | "no_need";
    humidity_after: number | null;
    dew_point_difference: number;
  } | null;
  /** What is wrong with it: cold, hot, damp or dry. */
  flags: string[];
};

/** The sky at the station, from its weather model. */
export type Sky = {
  /** The WMO weather code, and the same in words. */
  code: number;
  description: string;
  is_day: boolean | null;
  cloud_cover: number | null;
  time: string;
};

/** Something on a card that deserves attention: a warning, or good news worth acting on. */
export type Notice = { level: "warning" | "good"; text: string };

export type HouseAiring = {
  advice: "open" | "keep_closed" | "no_need";
  rooms: string[];
  humidity: number;
  humidity_after: number | null;
  dew_point_difference: number;
  /** When the forecast has the air turning dry enough to air a damp room, if it is not now. */
  drier_from: string | null;
};

export type SensorHealth = {
  sensor: string;
  name: string;
  battery_low: boolean | null;
  unchanged_s: number | null;
  updating: boolean;
};

export type Now = {
  station: string;
  time: string | null;
  online: boolean;
  timezone: string;
  units: Units;
  summary: string;
  /** The sky from the weather model, when the station has one and its values are recent. */
  sky: Sky | null;
  outdoor: Outdoor | null;
  wind: Wind | null;
  rain: Rain | null;
  pressure: Pressure | null;
  sun: Sun | null;
  airing: HouseAiring | null;
  rooms: Room[];
  sensors: SensorHealth[];
  /** What deserves attention, by card; a card missing from it is unremarkable. */
  notices: Partial<Record<string, Notice>>;
};

export type ForecastHour = {
  time: string;
  temperature: number | null;
  humidity: number | null;
  dew_point: number | null;
  precipitation: number | null;
  precipitation_probability: number | null;
  weather_code: number | null;
  description: string | null;
  is_day: boolean | null;
  wind_speed: number | null;
  wind_gust: number | null;
  wind_direction: number | null;
  compass: string | null;
};

export type ForecastDay = {
  /** The day's start, at midnight in the station's time zone. */
  date: string;
  weather_code: number | null;
  description: string | null;
  temperature_max: number | null;
  temperature_min: number | null;
  precipitation: number | null;
  precipitation_probability: number | null;
  wind_speed_max: number | null;
  wind_gust_max: number | null;
  wind_direction: number | null;
  compass: string | null;
  uv_index_max: number | null;
};

export type ForecastOut = {
  station: string;
  model: WeatherModel | null;
  /** When it was made; null without a forecast recent enough to show. */
  issued: string | null;
  units: Units;
  hours: ForecastHour[];
  days: ForecastDay[];
};

export type Series = {
  metric: string;
  sensor: string | null;
  name: string | null;
  unit: string;
  /** "model" for the weather model's values of the same metric. */
  source: "station" | "model";
  t: number[];
  values: Record<string, (number | null)[]>;
};

export type SeriesOut = {
  station: string;
  range: string;
  step_s: number;
  start: string;
  end: string;
  units: Units;
  series: Series[];
};

export type Extreme = {
  metric: string;
  sensor: string | null;
  name: string | null;
  unit: string;
  min: At | null;
  max: At | null;
};

export type ExtremesOut = {
  station: string;
  period: string;
  start: string;
  end: string;
  units: Units;
  extremes: Extreme[];
};

export type MetricInfo = {
  id: string;
  label: string;
  quantity: string | null;
  unit: string | null;
  aggregates: string[];
  extremes: "none" | "max" | "both";
  per_sensor: boolean;
  /** Whether the weather model has it, so /series can add the model's series. */
  model: boolean;
};

export type Meta = {
  title: string;
  metrics: MetricInfo[];
  units: Record<string, { code: string; symbol: string }[]>;
  symbols: Record<string, string>;
  ranges: string[];
  periods: string[];
};

/** Unit choices sent with a request; a quantity left out comes in the station's own unit. */
export type UnitChoice = Partial<Units>;

/** The API refused or could not answer; `status` is 0 when it could not be reached at all. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

/** Fetches the API's answers, relative to `base` (the page's own origin by default). */
export class Api {
  constructor(
    private readonly base = "/api/v1",
    private readonly fetcher: typeof fetch = (...args) => fetch(...args),
  ) {}

  meta(): Promise<Meta> {
    return this.get("/meta");
  }

  stations(): Promise<Station[]> {
    return this.get("/stations");
  }

  now(station: string, units: UnitChoice = {}): Promise<Now> {
    return this.get(`/stations/${encodeURIComponent(station)}/now`, units);
  }

  series(
    station: string,
    metrics: string[],
    range: string,
    units: UnitChoice = {},
    model = false,
  ): Promise<SeriesOut> {
    return this.get(`/stations/${encodeURIComponent(station)}/series`, {
      ...units,
      metrics: metrics.join(","),
      range,
      model: model ? "true" : undefined,
    });
  }

  forecast(station: string, units: UnitChoice = {}): Promise<ForecastOut> {
    return this.get(`/stations/${encodeURIComponent(station)}/forecast`, units);
  }

  extremes(station: string, period: string, units: UnitChoice = {}): Promise<ExtremesOut> {
    return this.get(`/stations/${encodeURIComponent(station)}/extremes`, { ...units, period });
  }

  private async get<T>(path: string, query: Record<string, string | undefined> = {}): Promise<T> {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(query)) {
      if (value) params.set(key, value);
    }
    // The query's text, not URLSearchParams.size: Safari before 17 has no size, and would send
    // every request without its parameters.
    const search = params.toString();
    const url = this.base + path + (search ? `?${search}` : "");
    let response: Response;
    try {
      response = await this.fetcher(url, { headers: { Accept: "application/json" } });
    } catch {
      throw new ApiError(0, "The weather service cannot be reached.");
    }
    if (!response.ok) {
      let detail = `The weather service answered ${response.status}.`;
      try {
        const body = (await response.json()) as { detail?: unknown };
        if (typeof body.detail === "string") detail = body.detail;
      } catch {
        // A proxy's error page is not JSON; the status says enough.
      }
      throw new ApiError(response.status, detail);
    }
    return (await response.json()) as T;
  }
}
