/**
 * The Grafana page's copy buttons, against stand-ins for the DOM and the clipboard.
 * Run with `bin/test-js.sh`; needs nothing beyond Node itself.
 */
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");
const { copy, wire } = require("../../src/ecowitt/collector/admin/static/clipboard.js");

const SCRIPT = path.join(__dirname, "../../src/ecowitt/collector/admin/static/clipboard.js");

/** A page with one field and its copy button. */
function page() {
  const field = { value: '{"title": "Weather"}', selected: false, select() { this.selected = true; } };
  const status = { textContent: "" };
  const listeners = [];
  const button = {
    dataset: { copy: "dashboard-json", status: "dashboard-status" },
    addEventListener: (event, handler) => listeners.push([event, handler]),
  };
  const doc = {
    getElementById: (id) => ({ "dashboard-json": field, "dashboard-status": status })[id],
    querySelectorAll: (selector) => (selector === "button[data-copy]" ? [button] : []),
  };
  return { field, status, button, doc, listeners };
}

test("copies the field's text and says so", async () => {
  const { field, status, button, doc } = page();
  const written = [];
  await copy(button, { writeText: async (text) => written.push(text) }, doc);
  assert.deepEqual(written, [field.value]);
  assert.equal(status.textContent, "Copied.");
  assert.equal(field.selected, false);
});

test("selects the text where the clipboard refuses", async () => {
  const { field, status, button, doc } = page();
  await copy(button, { writeText: async () => { throw new Error("denied"); } }, doc);
  assert.equal(field.selected, true);
  assert.match(status.textContent, /^Selected: press Ctrl\+C/);
});

test("selects the text on a page the browser gives no clipboard", async () => {
  const { field, status, button, doc } = page();
  await copy(button, undefined, doc);
  assert.equal(field.selected, true);
  assert.match(status.textContent, /^Selected/);
});

test("wires every copy button to the clipboard", async () => {
  const { button, doc, listeners, status } = page();
  const written = [];
  wire(doc, { clipboard: { writeText: async (text) => written.push(text) } });
  assert.deepEqual(listeners.map(([event]) => event), ["click"]);
  await listeners[0][1]();
  assert.equal(written.length, 1);
  assert.equal(status.textContent, "Copied.");
  assert.equal(button.dataset.copy, "dashboard-json");
});

test("wires itself when a browser runs it as a plain script", () => {
  const { doc, listeners } = page();
  vm.runInNewContext(fs.readFileSync(SCRIPT, "utf8"), { document: doc, navigator: {} }, { filename: SCRIPT });
  assert.equal(listeners.length, 1);
});
