// Load the dashboard in a remote browser over the DevTools protocol and check that its legacy
// build ran: nothing thrown, the cards and a chart drawn, and the stylesheet's fallbacks applied.
// Exits 1 with each failure listed.
//
//   node check.mjs DEVTOOLS_URL PAGE_URL
//
// bin/test-legacy-browser.sh runs it against Chromium 59 (legacy-browser/Dockerfile).

import { failures } from "./failures.mjs";

const [devtools, page] = process.argv.slice(2);

/** How long the page gets to fetch its answers and draw, in milliseconds. */
const SETTLE_MS = 20_000;

/**
 * What the page shows when it works, measured in the browser. A level bar, the space between two
 * cards and the space between a card title's icon and its text have no size without the
 * stylesheet's fallbacks.
 */
const MEASURE = `(function () {
  var app = document.getElementById("app");
  var bar = document.querySelector(".bar span");
  var cards = document.querySelectorAll(".glance > *");
  var icon = document.querySelector("h2 > svg");
  var label = icon && icon.nextSibling;
  while (label && label.nodeType !== 3) label = label.nextSibling;
  var text = document.createRange();
  if (label) text.selectNodeContents(label);
  return {
    legacy: document.documentElement.className.indexOf("legacy") !== -1,
    text: app.innerText,
    error: app.querySelector(".page-error") ? app.querySelector(".page-error").textContent : null,
    canvases: document.querySelectorAll("canvas").length,
    bar: bar ? bar.getBoundingClientRect().height : 0,
    cardGap: cards.length > 1 ? cards[1].getBoundingClientRect().left - cards[0].getBoundingClientRect().right : 0,
    iconGap: label ? text.getBoundingClientRect().left - icon.getBoundingClientRect().right : 0,
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
  await browser.send("Page.navigate", { url: page });
  await new Promise((resolve) => setTimeout(resolve, SETTLE_MS));
  const { result } = await browser.send("Runtime.evaluate", { expression: MEASURE, returnByValue: true });
  browser.close();

  const measured = result.value;
  console.log(`Loaded in ${measured.userAgent}`);
  const found = failures(measured, errors);
  for (const failure of found) console.error(`FAIL ${failure}`);
  if (found.length) process.exit(1);
  console.log("The legacy build ran: cards, a chart and the stylesheet's fallbacks are all there.");
}

await main();
