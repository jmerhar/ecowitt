/**
 * The page's language: the visitor's own choice, made in the settings menu, or else the first of
 * the browser's languages the page has, matched as the API matches them, or else English.
 *
 * Both are Paraglide strategies of the page's own (build/paraglide.ts). Paraglide writes the
 * first language it resolves back into every strategy, so its built-in localStorage strategy
 * would keep a language read from the browser as though the visitor had chosen it, and the page
 * would stop following the browser after its first visit. These strategies ignore that write:
 * only `chooseLanguage` keeps a choice.
 */

import { browserStorage } from "./prefs";
import {
  baseLocale,
  defineCustomClientStrategy,
  getLocale,
  locales,
  overwriteGetLocale,
  type Locale,
} from "../paraglide/runtime.js";

/** Where the visitor's choice of language is kept. */
export const LANGUAGE_KEY = "ecowitt-dashboard-language";

/** Each language's name, in that language, as the settings menu offers it. */
export const LANGUAGE_NAMES: Record<Locale, string> = { en: "English", "pt-PT": "Português" };

/** How each language writes dates and numbers: English with the day first and a 24-hour clock. */
const INTL: Record<Locale, string> = { en: "en-GB", "pt-PT": "pt-PT" };

/**
 * The first language the page has among `wanted`: by its whole tag, or by its first part, so
 * "pt" and "pt-BR" find the Portuguese there is. Paraglide's own preferredLanguage strategy
 * matches the first part only against a locale's whole tag, so "pt" would not find "pt-PT".
 */
export function match(wanted: readonly string[], available: readonly string[] = locales): Locale | undefined {
  for (const tag of wanted) {
    const lower = tag.toLowerCase();
    const exact = available.find((locale) => locale.toLowerCase() === lower);
    if (exact) return exact as Locale;
    const first = lower.split("-")[0];
    const related = available.find((locale) => locale.toLowerCase().split("-")[0] === first);
    if (related) return related as Locale;
  }
  return undefined;
}

/**
 * Gives Paraglide the page's two strategies: the visitor's choice in `storage`, and the
 * browser's `languages` matched as `match` does.
 */
export function useLanguageStrategies(
  languages: () => readonly string[] = () => navigator.languages ?? [],
  storage: () => Storage | undefined = browserStorage,
): void {
  defineCustomClientStrategy("custom-choice", {
    getLocale: () => chosenLanguage(storage()) ?? undefined,
    setLocale: () => {},
  });
  defineCustomClientStrategy("custom-browser", {
    getLocale: () => match(languages()),
    setLocale: () => {},
  });
}

/** The visitor's own choice of language, or null when the page follows the browser. */
export function chosenLanguage(storage: Storage | undefined = browserStorage()): Locale | null {
  try {
    const saved = storage?.getItem(LANGUAGE_KEY);
    return saved && (locales as readonly string[]).includes(saved) ? (saved as Locale) : null;
  } catch {
    return null;
  }
}

/**
 * Keeps a choice of language, or forgets it when `language` is null, and reloads the page into
 * it: Paraglide's messages are read once per page.
 */
export function chooseLanguage(
  language: Locale | null,
  storage: Storage | undefined = browserStorage(),
  reload: () => void,
): void {
  try {
    if (language) storage?.setItem(LANGUAGE_KEY, language);
    else storage?.removeItem(LANGUAGE_KEY);
  } catch {
    // Storage refused: the page stays in the language it is in.
    return;
  }
  reload();
}

/**
 * Settles the page's language for as long as it is open, and returns it. Paraglide asks its
 * strategies again on every message, so without this a choice made in another tab would turn
 * this page's words over while its API answers and `<html lang>` stayed as they were, and each
 * message would read the browser's storage.
 */
export function settleLanguage(): Locale {
  const language = getLocale();
  overwriteGetLocale(() => language);
  return language;
}

/** The locale Intl formats dates and numbers in, for the page's language. */
export function intlLocale(language: Locale = getLocale()): string {
  return INTL[language] ?? INTL[baseLocale];
}
