import { describe, expect, it, vi } from "vitest";
import { canFullscreen, enterFullscreen, exitFullscreen, isFullscreen, onFullscreenChange } from "./fullscreen";

/** A document with only the parts given, events included. */
function fake(parts: Record<string, unknown> = {}) {
  const target = new EventTarget();
  return {
    addEventListener: target.addEventListener.bind(target),
    removeEventListener: target.removeEventListener.bind(target),
    dispatchEvent: target.dispatchEvent.bind(target),
    documentElement: {},
    ...parts,
  } as never as Parameters<typeof isFullscreen>[0] & EventTarget;
}

describe("canFullscreen", () => {
  it("reads either spelling", () => {
    expect(canFullscreen(fake({ fullscreenEnabled: true }))).toBe(true);
    expect(canFullscreen(fake({ webkitFullscreenEnabled: true }))).toBe(true);
    expect(canFullscreen(fake())).toBe(false);
  });
});

describe("isFullscreen", () => {
  it("is full screen when an element fills it, under either spelling", () => {
    expect(isFullscreen(fake({ fullscreenElement: {} }))).toBe(true);
    expect(isFullscreen(fake({ webkitFullscreenElement: {} }))).toBe(true);
    expect(isFullscreen(fake({ fullscreenElement: null }))).toBe(false);
  });

  it("is full screen as a home-screen app that opened so", () => {
    const view = (matches: boolean) => ({ matchMedia: (q: string) => ({ matches: matches && q === "(display-mode: fullscreen)" }) });
    expect(isFullscreen(fake({ defaultView: view(true) }))).toBe(true);
    expect(isFullscreen(fake({ defaultView: view(false) }))).toBe(false);
  });
});

describe("enterFullscreen", () => {
  it("asks with the standard name where there is one", () => {
    const requestFullscreen = vi.fn(() => Promise.resolve());
    const webkitRequestFullscreen = vi.fn();
    enterFullscreen(fake({ documentElement: { requestFullscreen, webkitRequestFullscreen } }));
    expect(requestFullscreen).toHaveBeenCalled();
    expect(webkitRequestFullscreen).not.toHaveBeenCalled();
  });

  it("asks with the webkit name in a browser that knows only that", () => {
    const webkitRequestFullscreen = vi.fn();
    enterFullscreen(fake({ documentElement: { webkitRequestFullscreen } }));
    expect(webkitRequestFullscreen).toHaveBeenCalled();
  });

  it("takes a refusal quietly, however it comes", async () => {
    const rejected = vi.fn(() => Promise.reject(new Error("not allowed")));
    expect(() => enterFullscreen(fake({ documentElement: { requestFullscreen: rejected } }))).not.toThrow();
    await Promise.resolve();
    const thrown = vi.fn(() => {
      throw new Error("not allowed");
    });
    expect(() => enterFullscreen(fake({ documentElement: { webkitRequestFullscreen: thrown } }))).not.toThrow();
  });
});

describe("exitFullscreen", () => {
  it("leaves full screen under the name the browser knows", () => {
    const exit = vi.fn(() => Promise.resolve());
    exitFullscreen(fake({ fullscreenElement: {}, exitFullscreen: exit }));
    expect(exit).toHaveBeenCalled();
    const webkitExitFullscreen = vi.fn();
    exitFullscreen(fake({ webkitFullscreenElement: {}, webkitExitFullscreen }));
    expect(webkitExitFullscreen).toHaveBeenCalled();
  });

  it("does nothing when no element fills the screen, as in an app opened full screen", () => {
    const exit = vi.fn(() => Promise.resolve());
    exitFullscreen(fake({ fullscreenElement: null, exitFullscreen: exit }));
    expect(exit).not.toHaveBeenCalled();
  });

  it("takes a refusal quietly", async () => {
    const exit = vi.fn(() => Promise.reject(new Error("no")));
    expect(() => exitFullscreen(fake({ fullscreenElement: {}, exitFullscreen: exit }))).not.toThrow();
    await Promise.resolve();
  });
});

describe("onFullscreenChange", () => {
  it("hears either event until stopped", () => {
    const doc = fake();
    const changed = vi.fn();
    const stop = onFullscreenChange(changed, doc);
    doc.dispatchEvent(new Event("fullscreenchange"));
    doc.dispatchEvent(new Event("webkitfullscreenchange"));
    expect(changed).toHaveBeenCalledTimes(2);
    stop();
    doc.dispatchEvent(new Event("fullscreenchange"));
    expect(changed).toHaveBeenCalledTimes(2);
  });
});
