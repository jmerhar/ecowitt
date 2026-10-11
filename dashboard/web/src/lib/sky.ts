/**
 * The sky's icon: Meteocons (Bas Milius, MIT), line style to sit beside Lucide's icons. Each
 * import is one small SVG, so only these reach the bundle. The WMO codes are Open-Meteo's.
 */

import clearDay from "@bybas/weather-icons/production/line/all/clear-day.svg";
import clearNight from "@bybas/weather-icons/production/line/all/clear-night.svg";
import drizzle from "@bybas/weather-icons/production/line/all/drizzle.svg";
import fogDay from "@bybas/weather-icons/production/line/all/fog-day.svg";
import fogNight from "@bybas/weather-icons/production/line/all/fog-night.svg";
import hail from "@bybas/weather-icons/production/line/all/hail.svg";
import notAvailable from "@bybas/weather-icons/production/line/all/not-available.svg";
import overcast from "@bybas/weather-icons/production/line/all/overcast.svg";
import partlyCloudyDay from "@bybas/weather-icons/production/line/all/partly-cloudy-day.svg";
import partlyCloudyDayRain from "@bybas/weather-icons/production/line/all/partly-cloudy-day-rain.svg";
import partlyCloudyDaySnow from "@bybas/weather-icons/production/line/all/partly-cloudy-day-snow.svg";
import partlyCloudyNight from "@bybas/weather-icons/production/line/all/partly-cloudy-night.svg";
import partlyCloudyNightRain from "@bybas/weather-icons/production/line/all/partly-cloudy-night-rain.svg";
import partlyCloudyNightSnow from "@bybas/weather-icons/production/line/all/partly-cloudy-night-snow.svg";
import rain from "@bybas/weather-icons/production/line/all/rain.svg";
import sleet from "@bybas/weather-icons/production/line/all/sleet.svg";
import snow from "@bybas/weather-icons/production/line/all/snow.svg";
import thunderstormsRain from "@bybas/weather-icons/production/line/all/thunderstorms-rain.svg";

/** An icon for the day and one for the night; the same one when the sky looks alike in both. */
type Pair = [day: string, night: string];

const same = (icon: string): Pair => [icon, icon];

/** By WMO code. Showers are rain with breaks of sun or stars, so they show the sky between. */
const ICONS: Record<number, Pair> = {
  0: [clearDay, clearNight],
  1: [partlyCloudyDay, partlyCloudyNight],
  2: [partlyCloudyDay, partlyCloudyNight],
  3: same(overcast),
  45: [fogDay, fogNight],
  48: [fogDay, fogNight],
  51: same(drizzle),
  53: same(drizzle),
  55: same(drizzle),
  56: same(sleet),
  57: same(sleet),
  61: same(rain),
  63: same(rain),
  65: same(rain),
  66: same(sleet),
  67: same(sleet),
  71: same(snow),
  73: same(snow),
  75: same(snow),
  77: same(snow),
  80: [partlyCloudyDayRain, partlyCloudyNightRain],
  81: [partlyCloudyDayRain, partlyCloudyNightRain],
  82: [partlyCloudyDayRain, partlyCloudyNightRain],
  85: [partlyCloudyDaySnow, partlyCloudyNightSnow],
  86: [partlyCloudyDaySnow, partlyCloudyNightSnow],
  95: same(thunderstormsRain),
  96: same(hail),
  99: same(hail),
};

/** The icon for a weather code; the day's when the model did not say whether it is day. */
export function skyIcon(code: number, isDay: boolean | null): string {
  const [day, night] = ICONS[code] ?? same(notAvailable);
  return isDay === false ? night : day;
}
