import { fireEvent, render, screen, waitFor, within } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App.svelte";
import { ApiError } from "./lib/api";
import { fakeApi, now, STATION } from "./testing";

vi.mock("./components/Chart.svelte", async () => ({ default: (await import("./components/ChartStub.svelte")).default }));

function memory(): Storage {
  const data = new Map<string, string>();
  return {
    getItem: (k) => data.get(k) ?? null,
    setItem: (k, v) => void data.set(k, v),
    removeItem: (k) => void data.delete(k),
    clear: () => data.clear(),
    key: () => null,
    get length() {
      return data.size;
    },
  };
}

describe("App", () => {
  beforeEach(() => {
    Element.prototype.scrollIntoView = vi.fn();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows the station at a glance, its history and records", async () => {
    const api = fakeApi();
    render(App, { api, storage: memory() });
    expect(await screen.findByText("18.0 °C")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Test weather" })).toBeInTheDocument();
    expect(screen.getByText("Home")).toBeInTheDocument();
    expect(screen.getByText("Gentle breeze from the SE")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Rooms" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Records" })).toBeInTheDocument();
    expect(screen.getByText(/1 needs attention/)).toBeInTheDocument();
    expect(document.title).toBe("Home · Test weather");
    expect(api.now).toHaveBeenCalledWith("Home", {});
  });

  it("drills down from a card to its chart", async () => {
    const api = fakeApi();
    const storage = memory();
    render(App, { api, storage });
    await fireEvent.click(await screen.findByRole("button", { name: /Wind/ }));
    await waitFor(() =>
      expect(api.series).toHaveBeenLastCalledWith("Home", ["wind.speed", "wind.gust", "wind.direction"], "24h", {}),
    );
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
    expect(JSON.parse(storage.getItem("ecowitt-dashboard")!).view).toBe("wind");
  });

  it("asks again in the units chosen, and remembers them", async () => {
    const api = fakeApi();
    const storage = memory();
    render(App, { api, storage });
    await screen.findByText("18.0 °C");
    await fireEvent.change(screen.getByLabelText("Temperature"), { target: { value: "f" } });
    await waitFor(() => expect(api.now).toHaveBeenLastCalledWith("Home", { temperature: "f" }));
    expect(JSON.parse(storage.getItem("ecowitt-dashboard")!).units).toEqual({ temperature: "f" });
    await fireEvent.change(screen.getByLabelText("Temperature"), { target: { value: "" } });
    await waitFor(() => expect(api.now).toHaveBeenLastCalledWith("Home", {}));
  });

  it("offers a choice when there are several stations", async () => {
    const api = fakeApi();
    api.stations.mockResolvedValue([STATION, { ...STATION, id: "Cabin" }]);
    render(App, { api, storage: memory() });
    const picker = await screen.findByLabelText("Station");
    await fireEvent.change(picker, { target: { value: "Cabin" } });
    await waitFor(() => expect(api.now).toHaveBeenLastCalledWith("Cabin", {}));
  });

  it("says when no station has published anything", async () => {
    const api = fakeApi();
    api.stations.mockResolvedValue([]);
    render(App, { api, storage: memory() });
    expect(await screen.findByText(/No station has published/)).toBeInTheDocument();
    expect(api.now).not.toHaveBeenCalled();
  });

  it("explains a failure to load, and keeps the last answer on a later one", async () => {
    const broken = fakeApi();
    broken.meta.mockRejectedValue(new ApiError(503, "the database could not be read"));
    const first = render(App, { api: broken, storage: memory() });
    expect(await screen.findByRole("alert")).toHaveTextContent("the database could not be read");
    first.unmount();

    vi.useFakeTimers({ shouldAdvanceTime: true });
    const api = fakeApi();
    render(App, { api, storage: memory(), refreshMs: 1000 });
    await screen.findByText("18.0 °C");
    api.now.mockRejectedValue(new Error("boom"));
    await vi.advanceTimersByTimeAsync(1100);
    expect(await screen.findByRole("alert")).toHaveTextContent("Something went wrong");
    expect(screen.getByText("18.0 °C")).toBeInTheDocument();
    api.now.mockResolvedValue(now({ online: false, outdoor: null, wind: null, rain: null, pressure: null, sun: null, rooms: [], sensors: [] }));
    await vi.advanceTimersByTimeAsync(1100);
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    expect(screen.getByText(/Last report/)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Rooms" })).not.toBeInTheDocument();
  });

  it("fetches the charts and records again on each refresh", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const api = fakeApi();
    render(App, { api, storage: memory(), refreshMs: 1000 });
    await waitFor(() => expect(api.series).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(api.extremes).toHaveBeenCalledTimes(1));
    await vi.advanceTimersByTimeAsync(1100);
    await waitFor(() => expect(api.series).toHaveBeenCalledTimes(2));
    expect(api.extremes).toHaveBeenCalledTimes(2);
  });

  it("works without any storage", async () => {
    render(App, { api: fakeApi() });
    expect(await screen.findByText("18.0 °C")).toBeInTheDocument();
    const header = screen.getByRole("banner");
    expect(within(header).getByText(/Updated/)).toBeInTheDocument();
  });
});
