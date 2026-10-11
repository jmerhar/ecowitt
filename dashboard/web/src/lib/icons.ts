/**
 * The icon for each metric and chart tab. Lucide's icons are one module each, so importing only
 * these keeps the rest out of the bundle.
 */

import type { Component } from "svelte";
import CloudRainIcon from "@lucide/svelte/icons/cloud-rain";
import DropletIcon from "@lucide/svelte/icons/droplet";
import DropletsIcon from "@lucide/svelte/icons/droplets";
import GaugeIcon from "@lucide/svelte/icons/gauge";
import HouseIcon from "@lucide/svelte/icons/house";
import SunIcon from "@lucide/svelte/icons/sun";
import SunMediumIcon from "@lucide/svelte/icons/sun-medium";
import ThermometerIcon from "@lucide/svelte/icons/thermometer";
import WindIcon from "@lucide/svelte/icons/wind";

type Icon = Component<any>;

/** By the metric's part after its group: outdoor.temperature and rooms.temperature alike. */
const BY_QUANTITY: Record<string, Icon> = {
  temperature: ThermometerIcon,
  humidity: DropletsIcon,
  dew_point: DropletIcon,
  airing_humidity: DropletsIcon,
  speed: WindIcon,
  gust: WindIcon,
  direction: WindIcon,
  rate: CloudRainIcon,
  daily: CloudRainIcon,
  sea_level: GaugeIcon,
  absolute: GaugeIcon,
  radiation: SunIcon,
  uv_index: SunMediumIcon,
};

/** The icon for a metric, such as outdoor.temperature; a sun for one this does not know. */
export function metricIcon(metric: string): Icon {
  return BY_QUANTITY[metric.split(".").pop() ?? ""] ?? SunIcon;
}

/** The icon for a chart tab. */
export function viewIcon(view: string): Icon {
  if (view.startsWith("rooms")) return HouseIcon;
  return (
    {
      temperature: ThermometerIcon,
      humidity: DropletsIcon,
      wind: WindIcon,
      rain: CloudRainIcon,
      pressure: GaugeIcon,
    }[view] ?? SunIcon
  );
}
