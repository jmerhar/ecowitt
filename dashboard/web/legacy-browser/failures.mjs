// What check.mjs makes of a page's measurements, kept apart so it can be tested without a browser.

/**
 * The languages the page is loaded in, each with the words that show its cards and its forecast
 * were drawn: the outdoor card's title and the forecast's.
 */
export const LANGUAGES = {
  en: { outdoors: "Outdoors", forecast: "Forecast" },
  "pt-PT": { outdoors: "Exterior", forecast: "Previsão" },
};

/** The failures in a page's measurements and the errors it reported, as sentences. */
export function failures(measured, errors, language = "en") {
  const words = LANGUAGES[language];
  const out = [...errors];
  if (!measured.legacy) out.push("the page did not mark itself as running the legacy build");
  if (measured.error) out.push(`the page could not start: ${measured.error}`);
  if (!measured.text.includes(words.outdoors)) out.push(`the cards were not drawn (no "${words.outdoors}")`);
  if (!measured.text.includes(words.forecast)) out.push(`the forecast was not drawn (no "${words.forecast}")`);
  if (measured.canvases < 1) out.push("no chart was drawn");
  if (measured.bar <= 0) out.push("a level bar has no height: the :where() fallbacks are missing");
  if (measured.cardGap <= 0) out.push("the cards touch: the grid-gap fallback is missing");
  if (measured.iconGap < 3) out.push("a card title's icon touches its text: the icon's flex-gap fallback is missing");
  return out.map((failure) => `${language}: ${failure}`);
}
