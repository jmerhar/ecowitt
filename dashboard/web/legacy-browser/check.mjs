// Load the dashboard in a remote browser over the DevTools protocol, once in each of its languages,
// and check that its legacy build ran: nothing thrown, the cards and a chart drawn, and the
// stylesheet's fallbacks applied. Exits 1 with each failure listed.
//
//   node check.mjs DEVTOOLS_URL PAGE_URL
//
// bin/test-legacy-browser.sh runs it against Chromium 59 (legacy-browser/Dockerfile).

import { failures, LANGUAGES } from "./failures.mjs";

const [devtools, page] = process.argv.slice(2);

/** How long the page gets to fetch its answers and draw, in milliseconds. */
const SETTLE_MS = 20_000;

/** Where the page keeps the visitor's language (src/lib/language.ts, LANGUAGE_KEY). */
const LANGUAGE_KEY = "ecowitt-dashboard-language";

/**
 * What the page shows when it works, measured in the browser. A level bar, the space between two
 * cards and the space between a card title's icon and its text have no size without the
 * stylesheet's fallbacks.
 */
const MEASURE = `(function () {
  var app = document.getElementById("app");
  var bar = document.querySelector(".bar span");
  var cards = document.querySelectorAll(".glance > *");
  // The narrowest space between a card title's icon and the text after it.
  var iconGap = Infinity;
  Array.prototype.forEach.call(document.querySelectorAll("h2 > svg"), function (icon) {
    var label = icon.nextSibling;
    while (label && label.nodeType !== 3) label = label.nextSibling;
    if (!label) return;
    var text = document.createRange();
    text.selectNodeContents(label);
    iconGap = Math.min(iconGap, text.getBoundingClientRect().left - icon.getBoundingClientRect().right);
  });
  return {
    legacy: document.documentElement.className.indexOf("legacy") !== -1,
    text: app.innerText,
    error: app.querySelector(".page-error") ? app.querySelector(".page-error").textContent : null,
    canvases: document.querySelectorAll("canvas").length,
    bar: bar ? bar.getBoundingClientRect().height : 0,
    cardGap: cards.length > 1 ? cards[1].getBoundingClientRect().left - cards[0].getBoundingClientRect().right : 0,
    iconGap: iconGap === Infinity ? 0 : iconGap,
    // Summaries styled without their list marker whose WebKit triangle still shows: their first
    // content starts right of their content edge, where the triangle sits.
    markers: Array.prototype.filter.call(document.querySelectorAll("summary"), function (summary) {
      var style = getComputedStyle(summary);
      if (style.listStyleType !== "none") return false;
      var first = summary.firstChild;
      while (first && first.nodeType === 3 && !first.textContent.trim()) first = first.nextSibling;
      while (first && first.nodeType === 8) first = first.nextSibling;
      if (!first) return false;
      var range = document.createRange();
      range.selectNodeContents(first);
      var start = (first.nodeType === 1 ? first.getBoundingClientRect() : range.getBoundingClientRect()).left;
      var edge = summary.getBoundingClientRect().left + parseFloat(style.borderLeftWidth) + parseFloat(style.paddingLeft);
      return start - edge > 2;
    }).length,
    userAgent: navigator.userAgent
  };
})()`;

/** Open the browser's first page target and return a function that sends it commands. */
async function connect(onEvent) {
  const targets = await (await fetch(`${devtools}/json/list`)).json();
  const socket = new WebSocket(targets.find((t) => t.type === "page").webSocketDebuggerUrl);
  const pending = new Map();
  let id = 0;
  socket.onmessage = (message) => {
    const data = JSON.parse(message.data);
    if (pending.has(data.id)) {
      pending.get(data.id)(data.result);
      pending.delete(data.id);
    } else if (data.method) onEvent(data);
  };
  await new Promise((resolve, reject) => {
    socket.onopen = resolve;
    socket.onerror = reject;
  });
  const send = (method, params = {}) =>
    new Promise((resolve) => {
      pending.set(++id, resolve);
      socket.send(JSON.stringify({ id, method, params }));
    });
  return { send, close: () => socket.close() };
}

/** Load the page in a language, chosen as a visitor would, and list what is wrong with it. */
async function load(browser, errors, language) {
  errors.length = 0;
  // The choice is kept per site, so it is set on the page itself, then the page loaded again.
  await browser.send("Page.navigate", { url: page });
  await new Promise((resolve) => setTimeout(resolve, 2_000));
  const choose = `localStorage.setItem(${JSON.stringify(LANGUAGE_KEY)}, ${JSON.stringify(language)})`;
  await browser.send("Runtime.evaluate", { expression: choose });
  errors.length = 0;
  await browser.send("Page.navigate", { url: page });
  await new Promise((resolve) => setTimeout(resolve, SETTLE_MS));
  const { result } = await browser.send("Runtime.evaluate", { expression: MEASURE, returnByValue: true });
  return { measured: result.value, found: failures(result.value, errors, language) };
}

async function main() {
  const errors = [];
  const browser = await connect(({ method, params }) => {
    if (method === "Runtime.exceptionThrown") {
      const details = params.exceptionDetails;
      errors.push(`uncaught: ${details.exception?.description ?? details.text}`);
    } else if (method === "Runtime.consoleAPICalled" && params.type === "error") {
      errors.push(`console.error: ${params.args.map((a) => a.value ?? a.description).join(" ")}`);
    }
  });
  await browser.send("Runtime.enable");
  await browser.send("Page.enable");
  const found = [];
  for (const language of Object.keys(LANGUAGES)) {
    const run = await load(browser, errors, language);
    if (language === "en") console.log(`Loaded in ${run.measured.userAgent}`);
    found.push(...run.found);
  }
  browser.close();

  for (const failure of found) console.error(`FAIL ${failure}`);
  if (found.length) process.exit(1);
  console.log(`The legacy build ran in ${Object.keys(LANGUAGES).join(" and ")}: cards, a chart and the stylesheet's fallbacks are all there.`);
}

await main();
