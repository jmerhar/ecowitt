// What check.mjs makes of a page's measurements, kept apart so it can be tested without a browser.

/** The failures in a page's measurements and the errors it reported, as sentences. */
export function failures(measured, errors) {
  const out = [...errors];
  if (!measured.legacy) out.push("the page did not mark itself as running the legacy build");
  if (measured.error) out.push(`the page could not start: ${measured.error}`);
  if (!measured.text.includes("Outdoors")) out.push("the cards were not drawn");
  if (measured.canvases < 1) out.push("no chart was drawn");
  if (measured.bar <= 0) out.push("a level bar has no height: the :where() fallbacks are missing");
  if (measured.cardGap <= 0) out.push("the cards touch: the grid-gap fallback is missing");
  if (measured.iconGap < 3) out.push("a card title's icon touches its text: the icon's flex-gap fallback is missing");
  return out;
}
