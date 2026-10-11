/**
 * Values and times as a visitor reads them. Times are shown in the station's time zone, since
 * "today's high at 14:10" means the station's afternoon wherever the visitor is.
 */

/** Decimal places worth showing per unit, as the API rounds them; anything else gets one. */
const DECIMALS: Record<string, number> = { inhg: 2, in: 2, in_h: 2, pct: 0, deg: 0, wm2: 0, "": 0 };

/** A number to the precision its unit is worth, or an en dash when there is none. */
export function number(value: number | null | undefined, unit = "", locale?: string): string {
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
  locale?: string,
): string {
  const text = number(value, unit, locale);
  const symbol = symbols[unit] ?? "";
  if (text === "–" || !symbol) return text;
  // Percent and plain degrees sit against the number; units of measure take a space.
  return symbol === "%" || symbol === "°" ? `${text}${symbol}` : `${text} ${symbol}`;
}

/** The time of day at the station: "14:05". */
export function clock(iso: string | null | undefined, timezone: string, locale?: string): string {
  if (!iso) return "–";
  return new Intl.DateTimeFormat(locale, {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: timezone,
  }).format(new Date(iso));
}

/** A date and time at the station: "9 Oct, 14:05" -- day first, as most of the world reads it. */
export function moment(iso: string | null | undefined, timezone: string, locale?: string): string {
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
  if (!iso) return "never";
  const seconds = Math.max(0, (now.getTime() - new Date(iso).getTime()) / 1000);
  if (seconds < 90) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 90) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 36) return `${hours} h ago`;
  return `${Math.round(hours / 24)} days ago`;
}

/** A duration in hours and minutes: "11 h 22 min". */
export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "–";
  const minutes = Math.round(seconds / 60);
  const hours = Math.floor(minutes / 60);
  return hours ? `${hours} h ${minutes % 60} min` : `${minutes} min`;
}

/** The WHO's words for a UV index. */
export function uvRisk(index: number | null | undefined): string {
  if (index === null || index === undefined) return "";
  if (index < 3) return "Low";
  if (index < 6) return "Moderate";
  if (index < 8) return "High";
  if (index < 11) return "Very high";
  return "Extreme";
}
