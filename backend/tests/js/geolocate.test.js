/**
 * The setup page's location button, against stand-ins for the DOM and the geolocation API.
 * Run with `node --test backend/tests/js`; needs nothing beyond Node itself.
 */
"use strict";

const assert = require("node:assert/strict");
const { test } = require("node:test");
const { describeError, fillFromLocation, wire, OPTIONS } = require("../../src/ecowitt/static/geolocate.js");

/** A page holding one station form's inputs and one location button. */
function page() {
  const elements = {
    "lat-1": { value: "" },
    "lon-1": { value: "" },
    "geo-1": { textContent: "" },
  };
  const listeners = [];
  const button = {
    dataset: { lat: "lat-1", lon: "lon-1", status: "geo-1" },
    disabled: false,
    addEventListener: (event, handler) => listeners.push([event, handler]),
  };
  const doc = {
    getElementById: (id) => elements[id],
    querySelectorAll: (selector) => (selector === "button[data-geolocate]" ? [button] : []),
  };
  return { elements, button, doc, listeners };
}

/** A geolocation service that answers each request as told, recording the options it got. */
function geolocation(answer) {
  const asked = [];
  return {
    asked,
    getCurrentPosition(success, failure, options) {
      asked.push(options);
      answer(success, failure);
    },
  };
}

test("a fix fills both coordinates to six places and states its accuracy", () => {
  const { elements, button, doc } = page();
  const geo = geolocation((ok) => ok({ coords: { latitude: 52.3730796, longitude: 4.8924534, accuracy: 23.6 } }));

  fillFromLocation(button, geo, doc);

  assert.equal(elements["lat-1"].value, "52.373080");
  assert.equal(elements["lon-1"].value, "4.892453");
  assert.match(elements["geo-1"].textContent, /within about 24 m/);
  assert.match(elements["geo-1"].textContent, /Check it is where the station is/);
  assert.equal(button.disabled, false);
});

test("a precise, fresh fix is asked for, with a time limit", () => {
  const { button, doc } = page();
  const geo = geolocation(() => {});

  fillFromLocation(button, geo, doc);

  assert.deepEqual(geo.asked, [{ enableHighAccuracy: true, timeout: 15000, maximumAge: 0 }]);
  assert.deepEqual(OPTIONS, geo.asked[0]);
});

test("while waiting the button is disabled and says so", () => {
  const { elements, button, doc } = page();

  fillFromLocation(button, geolocation(() => {}), doc);

  assert.equal(button.disabled, true);
  assert.match(elements["geo-1"].textContent, /Finding this device's location/);
});

test("a refusal leaves the coordinates alone and explains", () => {
  const { elements, button, doc } = page();
  elements["lat-1"].value = "1.5";

  fillFromLocation(button, geolocation((_, fail) => fail({ code: 1 })), doc);

  assert.equal(elements["lat-1"].value, "1.5");
  assert.match(elements["geo-1"].textContent, /permission was refused/);
  assert.equal(button.disabled, false);
});

test("each failure is explained differently", () => {
  const messages = [1, 2, 3, 99].map((code) => describeError({ code }));

  assert.equal(new Set(messages).size, 4);
  assert.match(describeError({ code: 3 }), /too long/);
  assert.match(describeError(undefined), /could not be read/);
});

test("on a secure page the button is connected to a click", () => {
  const { button, doc, listeners } = page();

  wire(doc, { geolocation: geolocation(() => {}) }, { isSecureContext: true });

  assert.equal(listeners.length, 1);
  assert.equal(listeners[0][0], "click");
  assert.equal(button.disabled, false);
});

test("clicking a connected button looks the location up", () => {
  const { elements, doc, listeners } = page();
  const geo = geolocation((ok) => ok({ coords: { latitude: 1, longitude: 2, accuracy: 5 } }));

  wire(doc, { geolocation: geo }, { isSecureContext: true });
  listeners[0][1]();

  assert.equal(elements["lat-1"].value, "1.000000");
  assert.equal(geo.asked.length, 1);
});

for (const [why, nav, win] of [
  ["over plain HTTP", { geolocation: {} }, { isSecureContext: false }],
  ["without a geolocation API", {}, { isSecureContext: true }],
]) {
  test(`${why} the button is disabled and explains`, () => {
    const { elements, button, doc, listeners } = page();

    wire(doc, nav, win);

    assert.equal(button.disabled, true);
    assert.equal(listeners.length, 0);
    assert.match(elements["geo-1"].textContent, /needs the page to be opened over HTTPS/);
  });
}
