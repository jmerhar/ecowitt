import { fireEvent, render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import NowCard from "./NowCard.svelte";
import WindCard from "./WindCard.svelte";
import RainCard from "./RainCard.svelte";
import PressureCard from "./PressureCard.svelte";
import SunCard from "./SunCard.svelte";
import Rooms from "./Rooms.svelte";
import Sensors from "./Sensors.svelte";
import UnitsMenu from "./UnitsMenu.svelte";
import { META, now, SYMBOLS, UNITS } from "../testing";

const tz = "Europe/Lisbon";

describe("NowCard", () => {
  it("leads with the temperature, what it feels like and today's range", async () => {
    const onselect = vi.fn();
    render(NowCard, { now: now(), symbols: SYMBOLS, timezone: tz, onselect });
    expect(screen.getByText("18.0 °C")).toBeInTheDocument();
    expect(screen.getByText("Feels like 16.0 °C")).toBeInTheDocument();
    // Times are in the station's zone (UTC+1 in October), in the test environment's locale.
    expect(screen.getByText("↓ 9.5 °C").getAttribute("title")).toMatch(/^at 0?7:00/);
    expect(screen.getByText("↑ 21.0 °C").getAttribute("title")).toMatch(/^at (14|0?2):00/);
    await fireEvent.click(screen.getByRole("button"));
    expect(onselect).toHaveBeenCalledWith("temperature");
  });

  it("leaves out what it does not have", () => {
    const base = now();
    render(NowCard, {
      now: now({ outdoor: { ...base.outdoor!, feels_like: 18, high: null, low: null } }),
      symbols: SYMBOLS, timezone: tz, onselect: vi.fn(),
    });
    expect(screen.queryByText(/Feels like/)).not.toBeInTheDocument();
    expect(screen.queryByText("Today")).not.toBeInTheDocument();
  });

  it("shows only the summary without an outdoor sensor", () => {
    render(NowCard, { now: now({ outdoor: null, summary: "Calm." }), symbols: SYMBOLS, timezone: tz, onselect: vi.fn() });
    expect(screen.getByText("Calm.")).toBeInTheDocument();
    expect(screen.queryByText("Humidity")).not.toBeInTheDocument();
  });
});

describe("WindCard", () => {
  it("points the arrow the way the wind blows and names where it comes from", async () => {
    const onselect = vi.fn();
    const { container } = render(WindCard, { wind: now().wind!, units: UNITS, symbols: SYMBOLS, timezone: tz, onselect });
    expect(screen.getByRole("img", { name: "From the SE" })).toBeInTheDocument();
    expect(container.querySelector("g")).toHaveAttribute("transform", "rotate(135)");
    expect(screen.getByText("Gentle breeze from the SE")).toBeInTheDocument();
    expect(screen.getByText(/^52\.0 km\/h at 11:00/)).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button"));
    expect(onselect).toHaveBeenCalledWith("wind");
  });

  it("has no arrow or direction in a calm", () => {
    const calm = { ...now().wind!, direction: null, compass: null, beaufort: 0, description: "Calm", max_gust_today: null };
    const { container } = render(WindCard, { wind: calm, units: UNITS, symbols: SYMBOLS, timezone: tz, onselect: vi.fn() });
    expect(screen.getByRole("img", { name: "Direction unknown" })).toBeInTheDocument();
    expect(container.querySelector("g")).toBeNull();
    expect(screen.getByText("Calm")).toBeInTheDocument();
    expect(screen.queryByText("Strongest today")).not.toBeInTheDocument();
  });
});

describe("RainCard", () => {
  it("shows today's total when dry and the rate while raining", async () => {
    const onselect = vi.fn();
    const dry = render(RainCard, { rain: now().rain!, units: UNITS, symbols: SYMBOLS, onselect });
    expect(screen.getByText("1.2 mm")).toBeInTheDocument();
    expect(screen.getByText("today, not raining now")).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button"));
    expect(onselect).toHaveBeenCalledWith("rain");
    dry.unmount();
    render(RainCard, {
      rain: { ...now().rain!, raining: true, rate: 0.1 },
      units: { ...UNITS, rain: "in" }, symbols: SYMBOLS, onselect,
    });
    expect(screen.getByText("0.10 in/h")).toBeInTheDocument();
    expect(screen.getByText("Raining now")).toBeInTheDocument();
  });
});

describe("PressureCard", () => {
  it.each([
    [{ change: -3, hours: 3, tendency: "falling" }, "↘", "Falling: -3.0 hPa in 3 h"],
    [{ change: 1, hours: 3, tendency: "rising slowly" }, "↗", "Rising slowly: +1.0 hPa in 3 h"],
    [{ change: 0, hours: 3, tendency: "steady" }, "→", "Steady: 0.0 hPa in 3 h"],
  ])("shows the trend %#", async (trend, arrow, words) => {
    const onselect = vi.fn();
    render(PressureCard, { pressure: { ...now().pressure!, trend }, units: UNITS, symbols: SYMBOLS, onselect });
    expect(screen.getByText(arrow)).toBeInTheDocument();
    expect(screen.getByText(words, { exact: false })).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button"));
    expect(onselect).toHaveBeenCalledWith("pressure");
  });

  it("falls back to relative pressure, and shows no trend without one", () => {
    render(PressureCard, {
      pressure: { ...now().pressure!, sea_level: null, trend: null }, units: UNITS, symbols: SYMBOLS, onselect: vi.fn(),
    });
    expect(screen.getByText("1,013.0 hPa", { exact: false })).toBeInTheDocument();
    expect(screen.queryByText(/in 3 h/)).not.toBeInTheDocument();
  });
});

describe("SunCard", () => {
  it("gives today's sunrise, sunset and daylight, and the UV risk", async () => {
    const onselect = vi.fn();
    render(SunCard, { sun: now().sun!, symbols: SYMBOLS, timezone: tz, onselect });
    expect(screen.getByText(/^↑ 0?7:42.*↓ (19|0?7):07/)).toBeInTheDocument();
    expect(screen.getByText("11 h 25 min of daylight")).toBeInTheDocument();
    expect(screen.getByText("4 Moderate")).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button"));
    expect(onselect).toHaveBeenCalledWith("sun");
  });

  it.each([
    ["day", "Up all day"],
    ["night", "Down all day"],
  ] as const)("says so in polar %s", (polar, words) => {
    render(SunCard, {
      sun: { ...now().sun!, polar, sunrise: null, sunset: null, uv_index: null },
      symbols: SYMBOLS, timezone: tz, onselect: vi.fn(),
    });
    expect(screen.getByText(words)).toBeInTheDocument();
    expect(screen.queryByText("UV index")).not.toBeInTheDocument();
  });

  it("shows only the light without sun times", () => {
    render(SunCard, {
      sun: { ...now().sun!, sunrise: null }, symbols: SYMBOLS, timezone: tz, onselect: vi.fn(),
    });
    expect(screen.queryByText(/daylight/)).not.toBeInTheDocument();
  });
});

describe("Rooms", () => {
  it("lists each room with advice only where there is some", async () => {
    const onselect = vi.fn();
    render(Rooms, { rooms: now().rooms, units: UNITS, symbols: SYMBOLS, onselect });
    expect(screen.getByText("Air it")).toHaveAttribute("title", expect.stringContaining("drier"));
    expect(screen.getByText("→ 49%")).toBeInTheDocument();
    expect(screen.getByText("Keep closed")).toBeInTheDocument();
    expect(screen.queryByText("→ 71%")).not.toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(4);
    await fireEvent.click(screen.getByRole("button", { name: "Temperature" }));
    expect(onselect).toHaveBeenCalledWith("rooms-temperature");
    await fireEvent.click(screen.getByRole("button", { name: "Humidity" }));
    expect(onselect).toHaveBeenCalledWith("rooms-humidity");
  });

  it("shows a room without a comparison without advice", () => {
    render(Rooms, { rooms: [{ ...now().rooms[0], airing: null }], units: UNITS, symbols: SYMBOLS, onselect: vi.fn() });
    expect(screen.queryByText("Air it")).not.toBeInTheDocument();
  });
});

describe("Sensors", () => {
  it("opens when a sensor needs attention, naming what is wrong", () => {
    const { container } = render(Sensors, { sensors: now().sensors });
    expect(container.querySelector("details")).toHaveAttribute("open");
    expect(screen.getByText("1 needs attention")).toBeInTheDocument();
    expect(screen.getByText("Not updating for 5 h 33 min")).toBeInTheDocument();
    expect(screen.getByText("Battery low")).toBeInTheDocument();
  });

  it("stays folded when all is well, and counts several problems", () => {
    const fine = render(Sensors, { sensors: [now().sensors[0]] });
    expect(fine.container.querySelector("details")).not.toHaveAttribute("open");
    expect(screen.getByText("All reporting")).toBeInTheDocument();
    fine.unmount();
    render(Sensors, { sensors: [now().sensors[1], { ...now().sensors[1], sensor: "ch2" }] });
    expect(screen.getByText("2 need attention")).toBeInTheDocument();
  });
});

describe("UnitsMenu", () => {
  it("offers each quantity's units and reports a choice, or its removal", async () => {
    const onchange = vi.fn();
    render(UnitsMenu, { meta: META, chosen: { wind: "mph" }, onchange });
    const wind = screen.getByLabelText("Wind") as HTMLSelectElement;
    expect(wind.value).toBe("mph");
    await fireEvent.change(screen.getByLabelText("Temperature"), { target: { value: "f" } });
    expect(onchange).toHaveBeenLastCalledWith({ wind: "mph", temperature: "f" });
    await fireEvent.change(wind, { target: { value: "" } });
    expect(onchange).toHaveBeenLastCalledWith({});
  });

  it("copes with a quantity the API lists no units for", () => {
    render(UnitsMenu, { meta: { ...META, units: {} }, chosen: {}, onchange: vi.fn() });
    expect((screen.getByLabelText("Rain") as HTMLSelectElement).options).toHaveLength(1);
  });
});
