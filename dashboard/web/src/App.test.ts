import { fireEvent, render, screen, waitFor, within } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App.svelte";
import { ApiError } from "./lib/api";
import { fakeApi, now, speaking, STATION } from "./testing";
import { LANGUAGE_KEY } from "./lib/language";

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
    // index.html's tag, which names the page on an iOS home screen.
    const title = Object.assign(document.createElement("meta"), { name: "apple-mobile-web-app-title", content: "Weather" });
    document.head.append(title);
    render(App, { api, storage: memory() });
    expect(await screen.findByText("18.0 °C")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Test weather" })).toBeInTheDocument();
    expect(screen.getByText("Home")).toBeInTheDocument();
    expect(screen.getByText("Gentle breeze from the SE")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Rooms" })).toBeInTheDocument();
    expect(screen.getByText("Good time to air")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Highs and lows" })).toBeInTheDocument();
    expect(screen.getByText(/1 needs attention/)).toBeInTheDocument();
    expect(document.title).toBe("Home · Test weather");
    expect(title).toHaveAttribute("content", "Test weather");
    title.remove();
    expect(api.now).toHaveBeenCalledWith("Home", {});
  });

  it("keeps the language chosen in the settings, and reloads into it", async () => {
    const storage = memory();
    const reload = vi.fn();
    render(App, { api: fakeApi(), storage, reload });
    await fireEvent.change(await screen.findByLabelText("Language"), { target: { value: "pt-PT" } });
    expect(storage.getItem(LANGUAGE_KEY)).toBe("pt-PT");
    expect(reload).toHaveBeenCalledTimes(1);
    expect((screen.getByLabelText("Language") as HTMLSelectElement).value).toBe("pt-PT");
  });

  it("asks the API for its words in the page's language", async () => {
    speaking("pt-PT");
    const fetcher = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("[]"));
    render(App, { storage: memory() });
    await waitFor(() => expect(fetcher).toHaveBeenCalledWith("/api/v1/meta?lang=pt-PT", expect.anything()));
    fetcher.mockRestore();
  });

  it("drills down from a card to its chart", async () => {
    const api = fakeApi();
    const storage = memory();
    render(App, { api, storage });
    await fireEvent.click(await screen.findByRole("button", { name: /Wind/ }));
    await waitFor(() =>
      expect(api.series).toHaveBeenLastCalledWith("Home", ["wind.speed", "wind.gust", "wind.direction", "wind.measured_speed"], "24h", {}, false),
    );
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
    expect(JSON.parse(storage.getItem("ecowitt-dashboard")!).view).toBe("wind");
  });

  it("leads with the measured wind when the visitor chooses it, and remembers that", async () => {
    const api = fakeApi();
    api.stations.mockResolvedValue([{ ...STATION, wind_factor: 2 }]);
    const base = now().wind!;
    api.now.mockResolvedValue(now({ wind: { ...base, speed: 30, gust: 50, source: "sensor", height_factor: 2 } }));
    const storage = memory();
    render(App, { api, storage });
    expect(await screen.findByText("30.0 km/h")).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: /Wind/ }));
    await fireEvent.change(screen.getByLabelText("Wind at"), { target: { value: "sensor" } });
    expect(await screen.findByText("at the sensor")).toBeInTheDocument();
    await waitFor(() =>
      expect(api.series).toHaveBeenLastCalledWith(
        "Home", ["wind.measured_speed", "wind.measured_gust", "wind.direction", "wind.speed"], "24h", {}, false,
      ),
    );
    expect(JSON.parse(storage.getItem("ecowitt-dashboard")!).wind).toBe("sensor");
    expect(await screen.findByText("Wind gust, measured", { selector: ".label" })).toBeInTheDocument();
  });

  it("offers no choice of the wind's height for a station that measures it as it is", async () => {
    const api = fakeApi();
    const storage = memory();
    // A choice saved on another station leaves this one's chart as it is.
    storage.setItem("ecowitt-dashboard", JSON.stringify({ wind: "sensor", view: "wind" }));
    render(App, { api, storage });
    await screen.findByText("18.0 °C");
    expect(screen.queryByLabelText("Wind at")).not.toBeInTheDocument();
    await waitFor(() =>
      expect(api.series).toHaveBeenLastCalledWith("Home", ["wind.speed", "wind.gust", "wind.direction", "wind.measured_speed"], "24h", {}, false),
    );
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

  it("shows the time at the station, and keeps it moving", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date("2026-10-10T13:20:00Z"));
    render(App, { api: fakeApi(), storage: memory(), clockMs: 1000 });
    expect(await screen.findByText("Sat 10 Oct, 14:20 Lisbon time")).toHaveAttribute("title", "Europe/Lisbon");
    vi.setSystemTime(new Date("2026-10-10T13:21:00Z"));
    await vi.advanceTimersByTimeAsync(1100);
    expect(await screen.findByText("Sat 10 Oct, 14:21 Lisbon time")).toBeInTheDocument();
  });

  it("turns dark at sunset when following the sun, and remembers the choice", async () => {
    // The fixture's sun sets at 18:07 UTC.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(new Date("2026-10-10T18:06:00Z"));
    const storage = memory();
    const shown = render(App, { api: fakeApi(), storage, clockMs: 1000 });
    const root = document.documentElement;
    await fireEvent.change(await screen.findByLabelText("Theme"), { target: { value: "sun" } });
    await waitFor(() => expect(root.dataset.theme).toBe("light"));
    vi.setSystemTime(new Date("2026-10-10T18:07:30Z"));
    await vi.advanceTimersByTimeAsync(1100);
    await waitFor(() => expect(root.dataset.theme).toBe("dark"));
    expect(JSON.parse(storage.getItem("ecowitt-dashboard")!)).toMatchObject({ theme: "sun", sunTheme: "dark" });
    await fireEvent.change(screen.getByLabelText("Theme"), { target: { value: "system" } });
    await waitFor(() => expect(root.dataset.theme).toBeUndefined());
    shown.unmount();
  });

  it("fills the screen when asked, and points the home screen at a full-screen app", async () => {
    // jsdom has no full screen: a stand-in for the browser's, which reports its changes.
    const root = document.documentElement as HTMLElement & { requestFullscreen: () => Promise<void> };
    const set = (element: Element | null) => {
      Object.defineProperty(document, "fullscreenElement", { value: element, configurable: true });
      document.dispatchEvent(new Event("fullscreenchange"));
    };
    Object.defineProperty(document, "fullscreenEnabled", { value: true, configurable: true });
    root.requestFullscreen = vi.fn(async () => set(root));
    document.exitFullscreen = vi.fn(async () => set(null));
    const link = Object.assign(document.createElement("link"), { rel: "manifest", href: "/manifest.webmanifest" });
    document.head.append(link);
    const storage = memory();
    const shown = render(App, { api: fakeApi(), storage });
    try {
      const box = (await screen.findByLabelText("Full screen")) as HTMLInputElement;
      expect(box.checked).toBe(false);
      await fireEvent.click(box);
      expect(root.requestFullscreen).toHaveBeenCalled();
      await waitFor(() => expect(box.checked).toBe(true));
      expect(link.getAttribute("href")).toBe("/manifest.webmanifest?display=fullscreen");
      expect(JSON.parse(storage.getItem("ecowitt-dashboard")!).fullscreen).toBe(true);

      // Left by the browser's own means, as a back gesture does: the home screen's choice stays.
      set(null);
      await waitFor(() => expect(box.checked).toBe(false));
      expect(link.getAttribute("href")).toBe("/manifest.webmanifest?display=fullscreen");

      await fireEvent.click(box);
      await fireEvent.click(box);
      expect(document.exitFullscreen).toHaveBeenCalled();
      await waitFor(() => expect(link.getAttribute("href")).toBe("/manifest.webmanifest"));
      expect(JSON.parse(storage.getItem("ecowitt-dashboard")!).fullscreen).toBe(false);
    } finally {
      shown.unmount();
      link.remove();
      set(null);
      for (const name of ["fullscreenEnabled", "fullscreenElement"]) delete (document as unknown as Record<string, unknown>)[name];
      delete (root as Partial<typeof root>).requestFullscreen;
      delete (document as Partial<Document>).exitFullscreen;
    }
  });

  it("offers no full screen where the browser has none", async () => {
    render(App, { api: fakeApi(), storage: memory() });
    await screen.findByLabelText("Theme");
    expect(screen.queryByLabelText("Full screen")).not.toBeInTheDocument();
  });

  it("opens in the sun's last theme before the station's sun times arrive", async () => {
    const api = fakeApi();
    api.now.mockReturnValue(new Promise(() => {}));
    const storage = memory();
    storage.setItem("ecowitt-dashboard", JSON.stringify({ theme: "sun", sunTheme: "dark" }));
    const shown = render(App, { api, storage });
    await waitFor(() => expect(api.now).toHaveBeenCalled());
    expect(document.documentElement.dataset.theme).toBe("dark");
    shown.unmount();
    delete document.documentElement.dataset.theme;
  });

  it("remembers how the rooms are sorted", async () => {
    const storage = memory();
    render(App, { api: fakeApi(), storage });
    await fireEvent.click(await screen.findByRole("button", { name: "Humidity" }));
    expect(JSON.parse(storage.getItem("ecowitt-dashboard")!).rooms).toEqual({ column: "humidity", descending: false });
  });

  it("works without any storage", async () => {
    render(App, { api: fakeApi() });
    expect(await screen.findByText("18.0 °C")).toBeInTheDocument();
    const header = screen.getByRole("banner");
    expect(within(header).getByText(/Updated/)).toBeInTheDocument();
  });

  it("credits the weather model's data where it is shown, and links the licences", async () => {
    const api = fakeApi();
    api.stations.mockResolvedValue([{ ...STATION, weather_model: { id: "best_match", label: "Best for this location" } }]);
    const first = render(App, { api });
    const footer = await screen.findByRole("contentinfo");
    await waitFor(() => expect(within(footer).getByRole("link", { name: "Open-Meteo.com" })).toBeInTheDocument());
    expect(within(footer).getByRole("link", { name: "Licences" })).toHaveAttribute("href", "/licenses.md");
    expect(footer).toHaveTextContent("Ecowitt Server 2.8.0");
    first.unmount();
    render(App, { api: fakeApi() });
    const plain = await screen.findByRole("contentinfo");
    await screen.findByText("18.0 °C");
    expect(within(plain).queryByText(/Open-Meteo/)).not.toBeInTheDocument();
    expect(within(plain).getByRole("link", { name: "Licences" })).toBeInTheDocument();
  });
});
