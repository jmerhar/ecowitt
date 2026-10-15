/**
 * Copy buttons: each copies the text of the field it names, for pasting into Grafana.
 *
 * Browsers give the clipboard only to pages served over HTTPS or from localhost; elsewhere the
 * button selects the text instead and says how to copy it.
 *
 * Each button names its field with data-copy and where it reports with data-status.
 */
"use strict";

/**
 * Copies one field's text, or selects it where the clipboard is out of reach.
 * @param {HTMLButtonElement} button the clicked button
 * @param {{writeText: function(string): Promise<void>} | undefined} clipboard the browser's
 * @param {Document} doc the page
 * @returns {Promise<void>}
 */
async function copy(button, clipboard, doc) {
  const field = doc.getElementById(button.dataset.copy);
  const status = doc.getElementById(button.dataset.status);
  try {
    await clipboard.writeText(field.value);
    status.textContent = "Copied.";
  } catch {
    field.select();
    status.textContent = "Selected: press Ctrl+C, or ⌘C on a Mac, to copy it.";
  }
}

/**
 * Connects every copy button on the page.
 * @param {Document} doc the page
 * @param {Navigator} nav the browser
 */
function wire(doc, nav) {
  for (const button of doc.querySelectorAll("button[data-copy]")) {
    button.addEventListener("click", () => copy(button, nav.clipboard, doc));
  }
}

if (typeof module !== "undefined") {
  module.exports = { copy, wire };
} else {
  wire(document, navigator);
}
