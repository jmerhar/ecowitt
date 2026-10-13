import { fireEvent, render, screen, waitFor, within } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import History from "./History.svelte";
import Records from "./Records.svelte";
import Forecast from "./Forecast.svelte";
import { ApiError } from "../lib/api";
import { extremes, fakeApi, forecast, META, series, SYMBOLS } from "../testing";

vi.mock("./Chart.svelte", async () => ({ default: (await import("./ChartStub.svelte")).default }));

const base = { meta: META, station: "Home", units: {}, timezone: "Europe/Lisbon" };

describe("History", () => {
  it("charts the chosen view over the chosen range, and asks again when either changes", async () => {
    const api = fakeApi();
    render(History, { ...base, api, view: "temperature", range: "24h" });
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(await screen.findByText("Temperature", { selector: "li" })).toBeInTheDocument();
    expect(screen.getByText("Dew point", { selector: "li" })).toBeInTheDocument();
    await fireEvent.change(screen.getByRole("combobox", { name: "Range" }), { target: { value: "7d" } });
    await waitFor(() => expect(api.series).toHaveBeenLastCalledWith("Home", ["outdoor.temperature", "outdoor.dew_point"], "7d", {}, false));
    await fireEvent.click(screen.getByRole("tab", { name: "Pressure" }));
    await waitFor(() => expect(api.series).toHaveBeenLastCalledWith("Home", ["pressure.sea_level"], "7d", {}, false));
    expect(screen.getByRole("tab", { name: "Pressure" })).toHaveAttribute("aria-selected", "true");
  });

  it("offers the short ranges first, by their length", async () => {
    const api = fakeApi();
    render(History, { ...base, api, view: "temperature", range: "24h" });
    const ranges = screen.getByRole("combobox", { name: "Range" }) as HTMLSelectElement;
    expect([...ranges.options].map((o) => o.textContent)).toEqual([
      "1 h", "3 h", "6 h", "12 h", "Day", "Week", "Month", "Year",
    ]);
    expect(ranges.value).toBe("24h");
    await fireEvent.change(ranges, { target: { value: "12h" } });
    await waitFor(() => expect(api.series).toHaveBeenLastCalledWith("Home", ["outdoor.temperature", "outdoor.dew_point"], "12h", {}, false));
    expect(ranges.value).toBe("12h");
  });

  it("offers the weather model where the station has one and the chart has a metric it covers", async () => {
    const api = fakeApi();
    const weatherModel = { id: "best_match", label: "Best for this location" };
    render(History, { ...base, api, view: "temperature", range: "24h", weatherModel });
    const toggle = await screen.findByRole("button", { name: "Model" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    expect(toggle.getAttribute("title")).toContain("Best for this location");
    await fireEvent.click(toggle);
    await waitFor(() =>
      expect(api.series).toHaveBeenLastCalledWith("Home", ["outdoor.temperature", "outdoor.dew_point"], "24h", {}, true));
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    // The rooms have nothing the model covers, so the chart neither offers nor asks for it.
    await fireEvent.click(screen.getByRole("tab", { name: "Rooms °" }));
    await waitFor(() => expect(api.series).toHaveBeenLastCalledWith("Home", ["rooms.temperature"], "24h", {}, false));
    expect(screen.queryByRole("button", { name: "Model" })).not.toBeInTheDocument();
    // Hidden in place, so the range beside it does not move.
    const hidden = document.querySelector<HTMLButtonElement>("button.toggle")!;
    expect(hidden.style.visibility).toBe("hidden");
    expect(hidden).toBeDisabled();
  });

  it("does not offer a model the station does not have", async () => {
    const api = fakeApi();
    render(History, { ...base, api, view: "temperature", range: "24h", model: true });
    await screen.findByText("Temperature", { selector: "li" });
    expect(screen.queryByRole("button", { name: "Model" })).not.toBeInTheDocument();
    expect(api.series).toHaveBeenLastCalledWith("Home", ["outdoor.temperature", "outdoor.dew_point"], "24h", {}, false);
  });

  it("shows a chart only for the view its answer was for, not 'nothing' while loading", async () => {
    const api = fakeApi();
    render(History, { ...base, api, view: "temperature", range: "24h" });
    await screen.findByText("Temperature", { selector: "li" });
    api.series.mockImplementation(() => new Promise(() => {}));
    await fireEvent.click(screen.getByRole("tab", { name: "Wind" }));
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(screen.queryByText(/Nothing recorded/)).not.toBeInTheDocument();
  });

  it("says when the range holds nothing to draw", async () => {
    const api = fakeApi();
    api.series.mockResolvedValue(series({ series: [] }));
    render(History, { ...base, api, view: "temperature", range: "24h" });
    expect(await screen.findByText(/Nothing recorded/)).toBeInTheDocument();
  });

  it("explains a failure, in the API's words when it has some", async () => {
    const api = fakeApi();
    api.series.mockRejectedValue(new ApiError(503, "the database could not be read"));
    const first = render(History, { ...base, api, view: "temperature", range: "24h" });
    expect(await screen.findByText("the database could not be read")).toBeInTheDocument();
    first.unmount();
    api.series.mockRejectedValue(new Error("boom"));
    render(History, { ...base, api, view: "temperature", range: "24h" });
    expect(await screen.findByText("The chart could not be loaded.")).toBeInTheDocument();
  });

  it("drops an answer that arrives after the question changed", async () => {
    const api = fakeApi();
    let release: (v: unknown) => void = () => {};
    let fail: (e: unknown) => void = () => {};
    api.series.mockImplementationOnce(() => new Promise((r) => (release = r)));
    api.series.mockImplementationOnce(() => new Promise((_, reject) => (fail = reject)));
    render(History, { ...base, api, view: "temperature", range: "24h" });
    await fireEvent.change(screen.getByRole("combobox", { name: "Range" }), { target: { value: "1y" } });
    await waitFor(() => expect(api.series).toHaveBeenCalledTimes(2));
    await fireEvent.change(screen.getByRole("combobox", { name: "Range" }), { target: { value: "30d" } });
    await waitFor(() => expect(api.series).toHaveBeenCalledTimes(3));
    // The day's and the year's answers arrive after the month was chosen, and are dropped.
    release(series({ series: [] }));
    fail(new Error("late"));
    expect(await screen.findByText("Temperature", { selector: "li" })).toBeInTheDocument();
    expect(screen.queryByText(/Nothing recorded/)).not.toBeInTheDocument();
    expect(screen.queryByText(/could not be loaded/)).not.toBeInTheDocument();
  });
});

describe("Records", () => {
  it("shows each outdoor record with when it was set, leaving out records of nothing", async () => {
    const api = fakeApi();
    render(Records, { ...base, api, period: "today" });
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    const temperature = (await screen.findByText("Temperature", { selector: ".label" })).closest(".tile")!;
    expect(temperature).toHaveTextContent("Low 9.5 °C 07:00");
    expect(temperature).toHaveTextContent("High 21.0 °C 14:00");
    const gust = screen.getByText("Wind gust", { selector: ".label" }).closest(".tile")!;
    expect(gust).toHaveTextContent("High 52.0 km/h 11:00");
    expect(gust).not.toHaveTextContent("Low");
    expect(screen.queryByText("Rain today")).not.toBeInTheDocument();
  });

  it("folds the rooms beneath, a tile each with temperature and humidity", async () => {
    const api = fakeApi();
    api.extremes.mockResolvedValue(extremes({
      extremes: [
        ...extremes().extremes,
        { metric: "rooms.humidity", sensor: "ch1", name: "Bathroom", unit: "pct",
          min: { value: 60, time: "2026-10-10T05:00:00Z" }, max: { value: 75, time: "2026-10-10T12:00:00Z" } },
        { metric: "rooms.humidity", sensor: "ch2", name: null, unit: "pct", min: null, max: null },
        { metric: "rooms.dew_point", sensor: "ch1", name: "Bathroom", unit: "c",
          min: { value: 9, time: "2026-10-10T05:00:00Z" }, max: { value: 10, time: "2026-10-10T12:00:00Z" } },
        { metric: "rooms.temperature", sensor: null, name: null, unit: "c", min: null, max: null },
      ],
    }));
    render(Records, { ...base, api, period: "month" });
    const bathroom = (await screen.findByText("Bathroom", { selector: ".label" })).closest(".tile")!;
    expect(bathroom).toHaveTextContent("Low 17.2 °C 10 Oct, 06:00");
    expect(bathroom).toHaveTextContent("High 22.0 °C 10 Oct, 13:00");
    expect(bathroom).toHaveTextContent("Low 60% 10 Oct, 06:00");
    expect(bathroom).toHaveTextContent("High 75% 10 Oct, 13:00");
    expect(bathroom).not.toHaveTextContent("9.0 °C");
    // A room whose humidity record came back empty has a tile with nothing in it to show.
    expect(screen.getByText("ch2", { selector: ".label" }).closest(".tile")!.querySelectorAll("dd")).toHaveLength(0);
    expect(screen.getByText("Temperature", { selector: ".label" }).closest(".tile")).toHaveTextContent(
      "Low 9.5 °C 10 Oct, 07:00",
    );
  });

  it("asks for another period when it is chosen", async () => {
    const api = fakeApi();
    render(Records, { ...base, api, period: "today" });
    await fireEvent.click(screen.getByRole("tab", { name: "This year" }));
    await waitFor(() => expect(api.extremes).toHaveBeenLastCalledWith("Home", "year", {}));
  });

  it("names a metric the catalogue lacks by its id", async () => {
    const api = fakeApi();
    api.extremes.mockResolvedValue(extremes({
      extremes: [{ metric: "x.y", sensor: null, name: null, unit: "", min: null, max: { value: 1, time: "2026-10-10T00:00:00Z" } }],
    }));
    render(Records, { ...base, api, period: "today" });
    expect(await screen.findByText("x.y")).toBeInTheDocument();
    expect(screen.queryByText("Rooms")).not.toBeInTheDocument();
  });

  it("explains a failure", async () => {
    const api = fakeApi();
    api.extremes.mockRejectedValue(new ApiError(503, "the database could not be read"));
    const first = render(Records, { ...base, api, period: "today" });
    expect(await screen.findByText("the database could not be read")).toBeInTheDocument();
    first.unmount();
    api.extremes.mockRejectedValue(new Error("boom"));
    render(Records, { ...base, api, period: "today" });
    expect(await screen.findByText("The records could not be loaded.")).toBeInTheDocument();
  });
});


describe("Forecast", () => {
  const props = { station: "Home", units: {}, timezone: "Europe/Lisbon", symbols: SYMBOLS };

  it("shows the coming hours and the days, in the station's time", async () => {
    const api = fakeApi();
    render(Forecast, { ...props, api });
    const hours = await screen.findByRole("list", { name: "The next 24 hours" });
    const items = [...hours.querySelectorAll("[role=listitem]")].map((i) => i.textContent!.replace(/\s+/g, " ").trim());
    // 14:00 UTC is 15:00 in Lisbon; whole degrees and km/h in the strip.
    expect(items[0]).toBe("15:00 18 °C 70% 0% 15 km/h N");
    expect(items[1]).toContain("70%");
    expect(screen.getByText(/Best for this location, made 14:00/)).toBeInTheDocument();
    const cells = (row: HTMLElement) =>
      [...row.querySelectorAll("td")].map((c) => c.textContent!.replace(/\s+/g, " ").trim());
    const [first, second] = screen.getAllByRole("row").slice(1);
    // The day that began at 23:00 UTC on 9 Oct is 10 Oct in Lisbon; a chance of rain worth
    // showing comes after the amount, a small one not at all.
    expect(cells(first)).toEqual(["Sat 10 Oct", "Light rain", "13 °C", "21 °C", "2.4 mm 70%", "78%", "41 km/h N"]);
    expect(cells(second)).toEqual(["Sun 11 Oct", "Overcast", "11 °C", "19 °C", "0.0 mm", "–", "20 km/h N"]);
    // The sky is named once to a screen reader: by the icon, whose column has a header.
    expect(within(screen.getByRole("table")).getByRole("img", { name: "Light rain" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Sky" })).toBeInTheDocument();
  });

  it("marks only the chances of rain worth showing", async () => {
    const api = fakeApi();
    const { container } = render(Forecast, { ...props, api });
    await screen.findByRole("list", { name: "The next 24 hours" });
    const rain = [...container.querySelectorAll(".hour .rain")];
    expect(rain.map((r) => r.classList.contains("dry"))).toEqual([true, false, true]);
    // The night's icon at night, the day's by day.
    const icons = [...container.querySelectorAll<HTMLImageElement>(".hour img")].map((i) => i.alt);
    expect(icons).toEqual(["Overcast", "Light rain", "Overcast"]);
  });

  it("leaves out what the forecast does not have", async () => {
    const api = fakeApi();
    const base = forecast();
    api.forecast.mockResolvedValue(forecast({
      model: null,
      hours: [{ ...base.hours[0], weather_code: null, description: null, compass: null }],
      days: [{ ...base.days[1], weather_code: null, compass: null }],
    }));
    const { container } = render(Forecast, { ...props, api });
    await screen.findByRole("list", { name: "The next 24 hours" });
    expect(container.querySelectorAll("img")).toHaveLength(0);
    expect(screen.getByText(/Weather model, made/)).toBeInTheDocument();
    expect(container.querySelector(".hour .wind")!.textContent!.trim()).toBe("15 km/h");
  });

  it("gives an hour's rain as an amount from a model without a chance of it", async () => {
    const api = fakeApi();
    const base = forecast();
    api.forecast.mockResolvedValue(forecast({
      hours: [
        { ...base.hours[0], precipitation_probability: null, precipitation: 0.6 },
        { ...base.hours[1], precipitation_probability: null, precipitation: 0 },
      ],
    }));
    const { container } = render(Forecast, { ...props, api });
    await screen.findByRole("list", { name: "The next 24 hours" });
    const rain = [...container.querySelectorAll(".hour .rain")];
    expect(rain.map((r) => [r.textContent!.trim(), r.classList.contains("dry")])).toEqual([
      ["0.6 mm", false], ["0.0 mm", true],
    ]);
  });

  it("shows only the station asked for last, whichever answer comes first", async () => {
    const api = fakeApi();
    let release: (f: ReturnType<typeof forecast>) => void = () => {};
    api.forecast
      .mockReturnValueOnce(new Promise((resolve) => (release = resolve)))
      .mockResolvedValueOnce(forecast({ station: "Cabin", model: { id: "icon", label: "ICON" } }));
    const view = render(Forecast, { ...props, api });
    await view.rerender({ ...props, api, station: "Cabin" });
    expect(await screen.findByText(/ICON, made/)).toBeInTheDocument();
    release(forecast());
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.getByText(/ICON, made/)).toBeInTheDocument();
    expect(screen.queryByText(/Best for this location/)).not.toBeInTheDocument();
  });

  it("keeps the forecast shown when a refresh fails, and drops it for another station", async () => {
    const api = fakeApi();
    let fail: (e: Error) => void = () => {};
    const view = render(Forecast, { ...props, api });
    await screen.findByText(/Best for this location, made/);
    api.forecast.mockReturnValueOnce(new Promise((_, reject) => (fail = reject)));
    await view.rerender({ ...props, api, tick: 1 });
    fail(new ApiError(503, "the database could not be read"));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.getByText(/Best for this location, made/)).toBeInTheDocument();
    expect(screen.queryByText("the database could not be read")).not.toBeInTheDocument();
    api.forecast.mockReturnValueOnce(new Promise(() => {}));
    await view.rerender({ ...props, api, tick: 1, station: "Cabin" });
    expect(screen.queryByText(/Best for this location, made/)).not.toBeInTheDocument();
  });

  it("does not show another station's failure while this one's forecast loads", async () => {
    const api = fakeApi();
    let fail: (e: Error) => void = () => {};
    api.forecast
      .mockReturnValueOnce(new Promise((_, reject) => (fail = reject)))
      .mockReturnValueOnce(new Promise(() => {}));
    const view = render(Forecast, { ...props, api });
    await view.rerender({ ...props, api, station: "Cabin" });
    fail(new ApiError(503, "the database could not be read"));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.queryByText("the database could not be read")).not.toBeInTheDocument();
  });

  it("asks again on each refresh and in the units chosen", async () => {
    const api = fakeApi();
    const view = render(Forecast, { ...props, api });
    await screen.findByRole("list", { name: "The next 24 hours" });
    await view.rerender({ ...props, api, units: { temperature: "f" }, tick: 1 });
    await waitFor(() => expect(api.forecast).toHaveBeenLastCalledWith("Home", { temperature: "f" }));
  });

  it("is absent without a forecast to show, and says when it cannot be loaded", async () => {
    const api = fakeApi();
    api.forecast.mockResolvedValue(forecast({ issued: null, hours: [], days: [] }));
    const { container } = render(Forecast, { ...props, api });
    await waitFor(() => expect(api.forecast).toHaveBeenCalled());
    expect(container.querySelector(".forecast")).toBeNull();
    const failing = fakeApi();
    failing.forecast.mockRejectedValue(new ApiError(503, "the database could not be read"));
    render(Forecast, { ...props, api: failing });
    expect(await screen.findByText("the database could not be read")).toBeInTheDocument();
    const broken = fakeApi();
    broken.forecast.mockRejectedValue(new Error("x"));
    render(Forecast, { ...props, api: broken });
    expect(await screen.findByText("The forecast could not be loaded.")).toBeInTheDocument();
  });
});
