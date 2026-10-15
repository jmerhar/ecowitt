import { afterEach, beforeEach, describe, expect, it } from "vitest";
import page from "../index.html?raw";

/** index.html's inline script that reports a page failing to start. */
const reporter = [...page.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]).find((s) => s.includes("page-error"))!;

describe("index.html's error report", () => {
  let app: HTMLElement;
  const added: [string, EventListener][] = [];
  const listen = window.addEventListener.bind(window);

  beforeEach(() => {
    app = Object.assign(document.createElement("div"), { id: "app" });
    document.body.append(app);
    window.addEventListener = ((type: string, fn: EventListener) => {
      added.push([type, fn]);
      listen(type, fn);
    }) as typeof window.addEventListener;
    new Function(reporter)();
    window.addEventListener = listen;
  });

  afterEach(() => {
    for (const [type, fn] of added.splice(0)) window.removeEventListener(type, fn);
    app.remove();
  });

  it("says why a page that failed to start is blank", () => {
    window.dispatchEvent(new ErrorEvent("error", { message: "ReferenceError: x is not defined", filename: "/a.js", lineno: 3 }));
    expect(app.querySelector(".page-error")?.textContent).toBe(
      "The page could not start: ReferenceError: x is not defined (/a.js:3)",
    );
  });

  it("reports a rejected promise nobody handled", () => {
    const event = Object.assign(new Event("unhandledrejection"), { reason: new Error("no module") });
    window.dispatchEvent(event);
    expect(app.querySelector(".page-error")?.textContent).toContain("The page could not start: Error: no module");
  });

  it("leaves a page that has drawn alone", () => {
    app.append(document.createElement("header"));
    window.dispatchEvent(new ErrorEvent("error", { message: "ResizeObserver loop limit exceeded" }));
    expect(app.querySelector(".page-error")).toBeNull();
  });
});
