import { fireEvent, render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import NowCard from "./NowCard.svelte";
import WindCard from "./WindCard.svelte";
import RainCard from "./RainCard.svelte";
import PressureCard from "./PressureCard.svelte";
import SunCard from "./SunCard.svelte";
import Rooms from "./Rooms.svelte";
import AiringCard from "./AiringCard.svelte";
import Sensors from "./Sensors.svelte";
import UnitsMenu from "./UnitsMenu.svelte";
import { META, now, SYMBOLS, UNITS } from "../testing";
import { skyIcon } from "../lib/sky";

const tz = "Europe/Lisbon";

describe("NowCard", () => {
  it("leads with the temperature, what it feels like and today's range", async () => {
    const onselect = vi.fn();
    render(NowCard, { now: now(), symbols: SYMBOLS, timezone: tz, onselect });
    expect(screen.getByText("18.0 °C")).toBeInTheDocument();
    expect(screen.getByText("Feels like 16.0 °C")).toBeInTheDocument();
    // Times are in the station's zone, UTC+1 in October.
    expect(screen.getByText("↓ 9.5 °C")).toHaveAttribute("title", "at 07:00");
    expect(screen.getByText("↑ 21.0 °C")).toHaveAttribute("title", "at 14:00");
    expect(screen.getByText("Gentle breeze from the SE.")).toBeInTheDocument();
    expect(screen.queryByText(/^18 °C\./)).not.toBeInTheDocument();
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

  it("shows no summary when it said only the temperature", () => {
    render(NowCard, { now: now({ summary: "18 °C." }), symbols: SYMBOLS, timezone: tz, onselect: vi.fn() });
    expect(document.querySelector(".summary")).toBeNull();
  });

  it("shows the sky from the weather model, and leaves it out of the summary", () => {
    render(NowCard, {
      now: now({
        sky: { code: 3, description: "Overcast", is_day: true, cloud_cover: 95, time: "2026-10-10T13:45:00Z" },
        summary: "Overcast. 18 °C. Gentle breeze from the SE.",
      }),
      symbols: SYMBOLS, timezone: tz, onselect: vi.fn(),
    });
    const sky = screen.getByText("Overcast");
    expect(sky.closest(".sky")).toHaveAttribute("title", "From the weather model, for 14:45");
    expect(sky.closest(".sky")!.querySelector("img")!.getAttribute("src")).toBe(skyIcon(3, true));
    expect(screen.getByText("Gentle breeze from the SE.")).toBeInTheDocument();
    expect(screen.queryByText(/Overcast\. /)).not.toBeInTheDocument();
  });

  it("shows the night's sky at night, and no sky without a model", () => {
    const night = { code: 0, description: "Clear", is_day: false, cloud_cover: 0, time: "2026-10-10T22:00:00Z" };
    const first = render(NowCard, { now: now({ sky: night, summary: "Clear. 18 °C." }), symbols: SYMBOLS, timezone: tz, onselect: vi.fn() });
    expect(document.querySelector(".sky img")!.getAttribute("src")).toBe(skyIcon(0, false));
    expect(document.querySelector(".summary")).toBeNull();
    first.unmount();
    render(NowCard, { now: now(), symbols: SYMBOLS, timezone: tz, onselect: vi.fn() });
    expect(document.querySelector(".sky")).toBeNull();
  });

  it("keeps the summary whole when it has no temperature to leave out", () => {
    const base = now();
    render(NowCard, {
      now: now({ outdoor: { ...base.outdoor!, temperature: null }, summary: "Gentle breeze from the SE." }),
      symbols: SYMBOLS, timezone: tz, onselect: vi.fn(),
    });
    expect(screen.getByText("Gentle breeze from the SE.")).toBeInTheDocument();
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
    expect(screen.getByText("52.0 km/h at 11:00")).toBeInTheDocument();
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
    expect(screen.getByTitle("Sunrise")).toHaveTextContent("07:42");
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
  it("lists each room with advice only where there is some", () => {
    render(Rooms, { rooms: now().rooms, units: UNITS, symbols: SYMBOLS });
    expect(screen.getByText("Air it")).toHaveAttribute("title", expect.stringContaining("drier"));
    expect(screen.getByText("Keep closed")).toBeInTheDocument();
    // Airing would dry the bathroom (75% to 49%) and dampen the lounge (55% to 58%) and the
    // attic (70% to 71%, a point).
    expect(screen.getByText("49%")).toHaveClass("good");
    expect(screen.getByText("58%")).toHaveClass("bad");
    expect(screen.getByText("71%")).toHaveClass("bad");
    expect(screen.getAllByRole("row")).toHaveLength(4);
  });

  it("sorts by the column clicked, and turns round on a second click", async () => {
    const names = () => screen.getAllByRole("row").slice(1).map((r) => r.querySelector("td")!.textContent);
    render(Rooms, { rooms: now().rooms, units: UNITS, symbols: SYMBOLS });
    // The station's own order until a column is chosen.
    expect(names()).toEqual(["Lounge", "Bathroom", "Attic"]);
    expect(screen.getByRole("columnheader", { name: /Temperature/ })).toHaveAttribute("aria-sort", "none");
    await fireEvent.click(screen.getByRole("button", { name: "Temperature" }));
    expect(names()).toEqual(["Attic", "Bathroom", "Lounge"]);
    expect(screen.getByRole("columnheader", { name: /Temperature/ })).toHaveAttribute("aria-sort", "ascending");
    expect(screen.getByRole("button", { name: /Temperature/ })).toHaveTextContent("Temperature ↑");
    await fireEvent.click(screen.getByRole("button", { name: /Temperature/ }));
    expect(names()).toEqual(["Lounge", "Bathroom", "Attic"]);
    expect(screen.getByRole("columnheader", { name: /Temperature/ })).toHaveAttribute("aria-sort", "descending");
    await fireEvent.click(screen.getByRole("button", { name: "Room" }));
    expect(names()).toEqual(["Attic", "Bathroom", "Lounge"]);
    await fireEvent.click(screen.getByRole("button", { name: "If aired" }));
    expect(names()).toEqual(["Bathroom", "Lounge", "Attic"]);
    await fireEvent.click(screen.getByRole("button", { name: "Dew point" }));
    expect(names()).toEqual(["Lounge", "Attic", "Bathroom"]);
  });

  it("keeps a room without the value last, whichever way the column runs", () => {
    const rooms = [{ ...now().rooms[0], humidity: null }, ...now().rooms.slice(1)];
    const names = () => screen.getAllByRole("row").slice(1).map((r) => r.querySelector("td")!.textContent);
    const first = render(Rooms, { rooms, units: UNITS, symbols: SYMBOLS, sort: { column: "humidity", descending: false } });
    expect(names()).toEqual(["Attic", "Bathroom", "Lounge"]);
    first.unmount();
    render(Rooms, { rooms, units: UNITS, symbols: SYMBOLS, sort: { column: "humidity", descending: true } });
    expect(names()).toEqual(["Bathroom", "Attic", "Lounge"]);
  });

  it("keeps the station's order for a column it does not know", () => {
    render(Rooms, { rooms: now().rooms, units: UNITS, symbols: SYMBOLS, sort: { column: "colour", descending: false } });
    const names = screen.getAllByRole("row").slice(1).map((r) => r.querySelector("td")!.textContent);
    expect(names).toEqual(["Lounge", "Bathroom", "Attic"]);
  });

  it("has no airing column while no room has advice", () => {
    render(Rooms, {
      rooms: [{ ...now().rooms[0], airing: null }, { ...now().rooms[0], sensor: "ch9" }],
      units: UNITS, symbols: SYMBOLS,
    });
    expect(screen.queryByRole("columnheader", { name: "Airing" })).not.toBeInTheDocument();
    expect(screen.getAllByRole("cell")).toHaveLength(10);
    expect(screen.getAllByRole("cell")[4]).toHaveTextContent("–");
    expect(screen.getAllByRole("cell")[4]).toHaveClass("muted");
  });

  it("leaves the change muted when it is under a point", () => {
    const room = { ...now().rooms[0], humidity: 58.6 };
    render(Rooms, { rooms: [room], units: UNITS, symbols: SYMBOLS });
    expect(screen.getByText("58%")).toHaveClass("muted");
  });
});

describe("highlights", () => {
  it("give a card with a warning its edge and its words", () => {
    const notice = { level: "warning" as const, text: "Strong gusts." };
    const { container } = render(WindCard, {
      wind: now().wind!, units: UNITS, symbols: SYMBOLS, timezone: tz, onselect: vi.fn(), notice,
    });
    expect(container.querySelector(".card")).toHaveClass("warning");
    expect(screen.getByText("Strong gusts.")).toHaveClass("notice");
  });

  it.each([
    ["outdoor", NowCard, { now: now() }],
    ["rain", RainCard, { rain: now().rain!, units: UNITS }],
    ["pressure", PressureCard, { pressure: now().pressure!, units: UNITS }],
    ["sun", SunCard, { sun: now().sun!, timezone: tz }],
  ] as const)("reach the %s card", (_, Card, props) => {
    const { container } = render(Card as never, {
      ...props, symbols: SYMBOLS, timezone: tz, onselect: vi.fn(), notice: { level: "warning", text: "Look." },
    } as never);
    expect(container.querySelector(".card")).toHaveClass("warning");
    expect(screen.getByText("Look.")).toBeInTheDocument();
  });

  it("leave an unremarkable card plain, and a notice without words wordless", () => {
    const plain = render(SunCard, { sun: now().sun!, symbols: SYMBOLS, timezone: tz, onselect: vi.fn() });
    expect(plain.container.querySelector(".card")!.className).not.toMatch(/warning|good/);
    plain.unmount();
    const { container } = render(AiringCard, {
      airing: now().airing!, symbols: SYMBOLS, onselect: vi.fn(), notice: { level: "good", text: "" },
    });
    expect(container.querySelector(".card")).toHaveClass("good");
    expect(container.querySelector(".notice")).toBeNull();
  });

  it("colour a room's cold or damp readings, and edge the table", () => {
    const { container } = render(Rooms, {
      rooms: now().rooms, units: UNITS, symbols: SYMBOLS, notice: now().notices.rooms,
    });
    expect(container.querySelector(".card")).toHaveClass("warning");
    expect(screen.getByText("Damp: Bathroom. Cold: Attic.")).toBeInTheDocument();
    expect(screen.getByText("75%")).toHaveClass("warn");
    expect(screen.getByText("19.0 °C")).toHaveClass("warn");
    expect(screen.getByText("21.0 °C")).not.toHaveClass("warn");
  });

  it("edge the sensors when one needs attention", () => {
    const { container } = render(Sensors, { sensors: now().sensors, notice: now().notices.sensors });
    expect(container.querySelector(".card")).toHaveClass("warning");
  });

  it("show sunrise and sunset by icon", () => {
    render(SunCard, { sun: now().sun!, symbols: SYMBOLS, timezone: tz, onselect: vi.fn() });
    expect(screen.getByTitle("Sunrise")).toHaveTextContent("07:42");
    expect(screen.getByTitle("Sunset")).toHaveTextContent("19:07");
  });
});

describe("AiringCard", () => {
  it.each([
    [{ advice: "open", rooms: ["Bathroom", "Kitchen"] }, "Good time to air", "airing would dry Bathroom, Kitchen."],
    [{ advice: "keep_closed", rooms: [] }, "Keep the windows closed", "airing would leave the rooms damp."],
    [{ advice: "no_need", rooms: [] }, "No need to air", "dry enough."],
    [{ advice: "no_need", rooms: [], humidity_after: null }, "No need to air", "dry enough."],
    [{ advice: "no_need", rooms: [], humidity: 60, humidity_after: 59.5 }, "No need to air", "would make little difference."],
    [{ advice: "no_need", rooms: [], humidity: 55, humidity_after: 62 }, "No need to air", "would not leave the rooms damp."],
  ] as const)("says what to do: %#", async (overrides, headline, words) => {
    const onselect = vi.fn();
    const { container } = render(AiringCard, {
      airing: { ...now().airing!, ...overrides, rooms: [...overrides.rooms] }, symbols: SYMBOLS, onselect,
    });
    expect(screen.getByText(headline)).toBeInTheDocument();
    expect(container.querySelector("p")!.textContent!.replace(/\s+/g, " ")).toContain(words);
    expect(container.querySelector(".airing")).toHaveClass(overrides.advice);
    await fireEvent.click(screen.getByRole("button"));
    expect(onselect).toHaveBeenCalledWith("rooms-humidity");
  });

  it("shows what airing would do to the rooms' humidity in large numbers, coloured", () => {
    const shown = (humidity: number, humidity_after: number | null) => {
      const card = render(AiringCard, {
        airing: { ...now().airing!, humidity, humidity_after }, symbols: SYMBOLS, onselect: vi.fn(),
      });
      const values = [...card.container.querySelectorAll(".value")].map((v) => [v.textContent, v.className.replace(/\s*svelte-\S+/g, "").trim()]);
      card.unmount();
      return values;
    };
    // Drier: good. Damper: bad. Under a point either way: plain. Unknown: only the present.
    expect(shown(70, 58)).toEqual([["70%", "value"], ["58%", "value good"]]);
    expect(shown(53, 63)).toEqual([["53%", "value"], ["63%", "value bad"]]);
    expect(shown(60, 60.6)).toEqual([["60%", "value"], ["61%", "value"]]);
    expect(shown(60, null)).toEqual([["60%", "value"]]);
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
