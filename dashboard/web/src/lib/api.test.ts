import { describe, expect, it, vi } from "vitest";
import { Api, ApiError } from "./api";

function answering(status: number, body: unknown, text = false) {
  return vi.fn(async (..._: unknown[]) =>
    new Response(text ? String(body) : JSON.stringify(body), { status }),
  );
}

describe("Api", () => {
  it("asks for each answer at its path, with units and options as query parameters", async () => {
    const fetcher = answering(200, {});
    const api = new Api("/api/v1", fetcher as unknown as typeof fetch);
    await api.meta();
    await api.stations();
    await api.now("My station", { temperature: "f", wind: undefined });
    await api.series("Home", ["a.b", "c.d"], "7d", { wind: "mph" });
    await api.extremes("Home", "year");
    expect(fetcher.mock.calls.map((c) => c[0])).toEqual([
      "/api/v1/meta",
      "/api/v1/stations",
      "/api/v1/stations/My%20station/now?temperature=f",
      "/api/v1/stations/Home/series?wind=mph&metrics=a.b%2Cc.d&range=7d",
      "/api/v1/stations/Home/extremes?period=year",
    ]);
  });

  it("passes on the API's own explanation of a refusal", async () => {
    const api = new Api("/api/v1", answering(404, { detail: "no station named x" }) as never);
    await expect(api.now("x")).rejects.toEqual(new ApiError(404, "no station named x"));
  });

  it("falls back to the status when the refusal is not the API's", async () => {
    const api = new Api("/api/v1", answering(502, "<html>Bad gateway</html>", true) as never);
    await expect(api.meta()).rejects.toMatchObject({ status: 502, message: "The weather service answered 502." });
    const odd = new Api("/api/v1", answering(500, { detail: 7 }) as never);
    await expect(odd.meta()).rejects.toMatchObject({ message: "The weather service answered 500." });
  });

  it("says so when the service cannot be reached", async () => {
    const api = new Api("/api/v1", vi.fn(async () => { throw new TypeError("offline"); }) as never);
    await expect(api.stations()).rejects.toMatchObject({ status: 0 });
  });

  it("uses the page's own fetch by default", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("[]"));
    await new Api().stations();
    expect(spy).toHaveBeenCalledWith("/api/v1/stations", expect.anything());
    spy.mockRestore();
  });
});
