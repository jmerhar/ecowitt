/**
 * Fills a station form's coordinates from the location of the device viewing the page.
 *
 * The device is not necessarily at the station -- the page is often opened from somewhere
 * else -- so the result is only written into the form, with its accuracy, for the operator to
 * check before saving. Browsers offer location only to pages served over HTTPS or from
 * localhost; elsewhere the button says so instead of failing silently.
 *
 * Each button names the inputs it fills with data-lat, data-lon and data-status.
 */
"use strict";

/** How the browser is asked: a fresh, precise fix, given up on after 15 seconds. */
const OPTIONS = { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 };

/** Coordinates are written to six decimal places, about 0.1 m -- finer than any fix. */
const DECIMALS = 6;

/**
 * Explains a failed lookup in words the operator can act on.
 * @param {{code: number}} error a GeolocationPositionError
 * @returns {string}
 */
function describeError(error) {
  switch (error && error.code) {
    case 1:
      return "Location permission was refused. Allow it for this site, or enter the coordinates by hand.";
    case 2:
      return "This device could not work out its location.";
    case 3:
      return "Finding the location took too long. Try again, or enter the coordinates by hand.";
    default:
      return "The location could not be read.";
  }
}

/**
 * Looks up this device's location and writes it into the button's form.
 * @param {HTMLButtonElement} button the clicked button
 * @param {Geolocation} geolocation the browser's geolocation service
 * @param {Document} doc the page
 */
function fillFromLocation(button, geolocation, doc) {
  const latitude = doc.getElementById(button.dataset.lat);
  const longitude = doc.getElementById(button.dataset.lon);
  const status = doc.getElementById(button.dataset.status);
  button.disabled = true;
  status.textContent = "Finding this device's location…";
  geolocation.getCurrentPosition(
    (position) => {
      latitude.value = position.coords.latitude.toFixed(DECIMALS);
      longitude.value = position.coords.longitude.toFixed(DECIMALS);
      status.textContent =
        `Filled in from this device, to within about ${Math.round(position.coords.accuracy)} m. ` +
        "Check it is where the station is, then look up the altitude or save.";
      button.disabled = false;
    },
    (error) => {
      status.textContent = describeError(error);
      button.disabled = false;
    },
    OPTIONS,
  );
}

/**
 * Connects every location button on the page, or explains why it cannot work here.
 * @param {Document} doc the page
 * @param {Navigator} nav the browser
 * @param {{isSecureContext: boolean}} win the window
 */
function wire(doc, nav, win) {
  for (const button of doc.querySelectorAll("button[data-geolocate]")) {
    if (!win.isSecureContext || !nav.geolocation) {
      button.disabled = true;
      doc.getElementById(button.dataset.status).textContent =
        "Using this device's location needs the page to be opened over HTTPS.";
      continue;
    }
    button.addEventListener("click", () => fillFromLocation(button, nav.geolocation, doc));
  }
}

if (typeof module !== "undefined") {
  module.exports = { describeError, fillFromLocation, wire, OPTIONS };
} else {
  wire(document, navigator, window);
}
