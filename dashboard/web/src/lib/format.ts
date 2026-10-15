/**
 * Values and times as a visitor reads them. Times are shown in the station's time zone, since
 * "today's high at 14:10" means the station's afternoon wherever the visitor is.
 *
 * Dates and numbers follow the page's language (`intlLocale`), English with the day first and a
 * 24-hour clock ("9 Oct, 14:05") whatever the browser's locale: a month-first short date is
 * ambiguous to most of the world.
 */

import { intlLocale } from "./language";
import { m } from "../paraglide/messages.js";

/** Decimal places worth showing per unit, as the API rounds them; anything else gets one. */
const DECIMALS: Record<string, number> = { inhg: 2, in: 2, in_h: 2, pct: 0, deg: 0, wm2: 0, "": 0 };

/** A number to the precision its unit is worth, or an en dash when there is none. */
export function number(value: number | null | undefined, unit = "", locale = intlLocale()): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "–";
  const digits = DECIMALS[unit] ?? 1;
  return value.toLocaleString(locale, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

/** A value with its unit's symbol: "17.6 °C", "62 %", "1019.7 hPa". */
export function quantity(
  value: number | null | undefined,
  unit: string,
  symbols: Record<string, string>,
  locale = intlLocale(),
): string {
  const text = number(value, unit, locale);
  const symbol = symbols[unit] ?? "";
  if (text === "–" || !symbol) return text;
  // Percent and plain degrees sit against the number; units of measure take a space.
  return symbol === "%" || symbol === "°" ? `${text}${symbol}` : `${text} ${symbol}`;
}

/** A value rounded to a whole number, with its unit's symbol: "17 °C", "12 km/h". */
export function whole(
  value: number | null | undefined,
  unit: string,
  symbols: Record<string, string>,
  locale = intlLocale(),
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "–";
  const symbol = symbols[unit] ?? "";
  const text = Math.round(value).toLocaleString(locale);
  if (!symbol) return text;
  return symbol === "%" || symbol === "°" ? `${text}${symbol}` : `${text} ${symbol}`;
}

/** The time of day at the station: "14:05". */
export function clock(iso: string | null | undefined, timezone: string, locale = intlLocale()): string {
  if (!iso) return "–";
  return new Intl.DateTimeFormat(locale, {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: timezone,
  }).format(new Date(iso));
}

/**
 * The hour of a time at the station, 0 to 23, for a message whose words agree with it (the
 * Portuguese "à 01:00" but "às 02:00"). Read from the 24-hour clock: Intl's hourCycle option is
 * missing from the oldest browsers the page runs in, and hour12: false gives 24 for midnight in
 * some of them.
 */
export function hourOf(iso: string, timezone: string): number {
  return Number(clock(iso, timezone, "en-GB").split(":")[0]) % 24;
}

/** A date and time at the station: "9 Oct, 14:05" -- day first, as most of the world reads it. */
export function moment(iso: string | null | undefined, timezone: string, locale = intlLocale()): string {
  if (!iso) return "–";
  return new Intl.DateTimeFormat(locale, {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: timezone,
  }).format(new Date(iso));
}

/** How long ago something happened, in the largest unit that fits: "just now", "5 min ago". */
export function ago(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return m.never();
  const seconds = Math.max(0, (now.getTime() - new Date(iso).getTime()) / 1000);
  if (seconds < 90) return m.just_now();
  const minutes = Math.round(seconds / 60);
  if (minutes < 90) return m.minutes_ago({ minutes });
  const hours = Math.round(minutes / 60);
  if (hours < 36) return m.hours_ago({ hours });
  return m.days_ago({ days: Math.round(hours / 24) });
}

/**
 * A chart's time labels: the time of day for steps under a day, with the date beneath at
 * midnight and on the first label; the date alone for longer steps.
 */
export function axisLabels(ticks: number[], stepSeconds: number, timezone: string, locale = intlLocale()): string[] {
  const day = new Intl.DateTimeFormat(locale, { day: "numeric", month: "short", timeZone: timezone });
  const time = new Intl.DateTimeFormat(locale, { hour: "2-digit", minute: "2-digit", timeZone: timezone });
  return ticks.map((t, i) => {
    const at = new Date(t * 1000);
    if (stepSeconds >= 86400) return day.format(at);
    const hhmm = time.format(at);
    return i === 0 || hhmm === "00:00" ? `${hhmm}\n${day.format(at)}` : hhmm;
  });
}

/** The day, date and time at the station: "Sun 11 Oct, 12:20". */
export function today(iso: string, timezone: string, locale = intlLocale()): string {
  return new Intl.DateTimeFormat(locale, {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: timezone,
  }).format(new Date(iso));
}

/** The place a time zone is named after: "Europe/Lisbon" is Lisbon, "America/New_York" New York. */
export function zoneCity(timezone: string): string {
  const city = timezone.split("/").pop() ?? timezone;
  return city.replaceAll("_", " ");
}

/** A duration in hours and minutes: "11 h 22 min". */
export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "–";
  const minutes = Math.round(seconds / 60);
  const hours = Math.floor(minutes / 60);
  return hours ? m.duration_hours_minutes({ hours, minutes: minutes % 60 }) : m.duration_minutes({ minutes });
}

/** The WHO's words for a UV index. */
export function uvRisk(index: number | null | undefined): string {
  if (index === null || index === undefined) return "";
  if (index < 3) return m.uv_low();
  if (index < 6) return m.uv_moderate();
  if (index < 8) return m.uv_high();
  if (index < 11) return m.uv_very_high();
  return m.uv_extreme();
}

/** A time to come at the station: "14:00" today, "tomorrow 06:00", or "Thu 15 Oct, 06:00". */
export function coming(iso: string, timezone: string, now: Date = new Date()): string {
  const time = clock(iso, timezone);
  const hour = hourOf(iso, timezone);
  const day = whichDay(iso, timezone, now);
  if (day === "today") return m.today_at({ time, hour });
  if (day === "tomorrow") return m.tomorrow_at({ time, hour });
  return m.day_at({ day: dayLabel(iso, timezone, now), time, hour });
}

/** Whether a moment falls on today, tomorrow or another day, by the station's calendar. */
export function whichDay(iso: string, timezone: string, now: Date = new Date()): "today" | "tomorrow" | "other" {
  const date = (d: Date) => new Intl.DateTimeFormat("en-CA", { timeZone: timezone }).format(d);
  const day = date(new Date(iso));
  const today = date(now);
  if (day === today) return "today";
  // The calendar's next date, not the date a day from now: a day can be 23 or 25 hours long.
  const [y, m, d] = today.split("-").map(Number);
  return day === new Date(Date.UTC(y, m - 1, d + 1)).toISOString().slice(0, 10) ? "tomorrow" : "other";
}

/** A day at the station, as a forecast names it: "Today", "Tomorrow", or "Thu 15 Oct". */
export function dayLabel(iso: string, timezone: string, now: Date = new Date(), locale = intlLocale()): string {
  const day = whichDay(iso, timezone, now);
  if (day === "today") return m.today();
  if (day === "tomorrow") return m.tomorrow();
  return new Intl.DateTimeFormat(locale, {
    weekday: "short",
    day: "numeric",
    month: "short",
    timeZone: timezone,
  }).format(new Date(iso));
}
