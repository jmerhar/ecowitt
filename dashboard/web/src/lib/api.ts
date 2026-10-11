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

export type Station = {
  id: string;
  latitude: number | null;
  longitude: number | null;
  altitude_m: number | null;
  timezone: string;
  units: Units;
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
  outdoor: Outdoor | null;
  wind: Wind | null;
  rain: Rain | null;
  pressure: Pressure | null;
  sun: Sun | null;
  rooms: Room[];
  sensors: SensorHealth[];
};

export type Series = {
  metric: string;
  sensor: string | null;
  name: string | null;
  unit: string;
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
  ): Promise<SeriesOut> {
    return this.get(`/stations/${encodeURIComponent(station)}/series`, {
      ...units,
      metrics: metrics.join(","),
      range,
    });
  }

  extremes(station: string, period: string, units: UnitChoice = {}): Promise<ExtremesOut> {
    return this.get(`/stations/${encodeURIComponent(station)}/extremes`, { ...units, period });
  }

  private async get<T>(path: string, query: Record<string, string | undefined> = {}): Promise<T> {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(query)) {
      if (value) params.set(key, value);
    }
    const url = this.base + path + (params.size ? `?${params}` : "");
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
