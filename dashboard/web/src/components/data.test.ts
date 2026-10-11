import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import History from "./History.svelte";
import Records from "./Records.svelte";
import { ApiError } from "../lib/api";
import { extremes, fakeApi, META, series } from "../testing";

vi.mock("./Chart.svelte", async () => ({ default: (await import("./ChartStub.svelte")).default }));

const base = { meta: META, station: "Home", units: {}, timezone: "Europe/Lisbon" };

describe("History", () => {
  it("charts the chosen view over the chosen range, and asks again when either changes", async () => {
    const api = fakeApi();
    render(History, { ...base, api, view: "temperature", range: "24h" });
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(await screen.findByText("Temperature", { selector: "li" })).toBeInTheDocument();
    expect(screen.getByText("Dew point", { selector: "li" })).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("tab", { name: "Week" }));
    await waitFor(() => expect(api.series).toHaveBeenLastCalledWith("Home", ["outdoor.temperature", "outdoor.dew_point"], "7d", {}));
    await fireEvent.click(screen.getByRole("tab", { name: "Pressure" }));
    await waitFor(() => expect(api.series).toHaveBeenLastCalledWith("Home", ["pressure.sea_level"], "7d", {}));
    expect(screen.getByRole("tab", { name: "Pressure" })).toHaveAttribute("aria-selected", "true");
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
    await fireEvent.click(screen.getByRole("tab", { name: "Year" }));
    await waitFor(() => expect(api.series).toHaveBeenCalledTimes(2));
    await fireEvent.click(screen.getByRole("tab", { name: "Month" }));
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
    expect(temperature).toHaveTextContent("Low 9.5 °C at 07:00");
    expect(temperature).toHaveTextContent("High 21.0 °C at 14:00");
    const gust = screen.getByText("Wind gust", { selector: ".label" }).closest(".tile")!;
    expect(gust).toHaveTextContent("High 52.0 km/h at 11:00");
    expect(gust).not.toHaveTextContent("Low");
    expect(screen.queryByText("Rain today")).not.toBeInTheDocument();
  });

  it("folds the rooms into a table of ranges, with when on hover", async () => {
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
    const bathroom = (await screen.findByText("Bathroom")).closest("tr")!;
    expect(bathroom).toHaveTextContent("17.2–22.0 °C");
    expect(bathroom).toHaveTextContent("60–75%");
    expect(bathroom.querySelector("td[title]")).toHaveAttribute(
      "title", "Lowest at 10 Oct, 06:00, highest at 10 Oct, 13:00",
    );
    expect(screen.getByText("ch2").closest("tr")).toHaveTextContent("ch2––");
    expect(screen.getByText("Temperature", { selector: ".label" }).closest(".tile")).toHaveTextContent(
      "Low 9.5 °C at 10 Oct, 07:00",
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
