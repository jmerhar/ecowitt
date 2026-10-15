import { describe, expect, it } from "vitest";
import CloudRainIcon from "@lucide/svelte/icons/cloud-rain";
import DropletIcon from "@lucide/svelte/icons/droplet";
import HouseIcon from "@lucide/svelte/icons/house";
import SunIcon from "@lucide/svelte/icons/sun";
import ThermometerIcon from "@lucide/svelte/icons/thermometer";
import { metricIcon, viewIcon } from "./icons";
import { VIEWS } from "./chart";

describe("icons", () => {
  it("follow a metric's quantity, whichever group it is in", () => {
    expect(metricIcon("outdoor.temperature")).toBe(ThermometerIcon);
    expect(metricIcon("rooms.temperature")).toBe(ThermometerIcon);
    expect(metricIcon("outdoor.dew_point")).toBe(DropletIcon);
    expect(metricIcon("rain.daily")).toBe(CloudRainIcon);
    expect(metricIcon("wind.measured_gust")).toBe(metricIcon("wind.gust"));
    expect(metricIcon("something.new")).toBe(SunIcon);
  });

  it("give every chart tab one, rooms a house", () => {
    expect(viewIcon("rooms-humidity")).toBe(HouseIcon);
    expect(viewIcon("temperature")).toBe(ThermometerIcon);
    expect(viewIcon("sun")).toBe(SunIcon);
    for (const view of VIEWS) expect(viewIcon(view.id)).toBeTruthy();
  });
});
