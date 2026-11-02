/**
 * The page's language: the visitor's own choice, made in the settings menu, or else the first of
 * the browser's languages the page has, matched as the API matches them, or else English.
 *
 * jigkit's i18n module runs the choice over this page's Paraglide runtime, as two strategies of
 * the page's own (build/paraglide.ts) that ignore Paraglide writing back what it resolved: only
 * `chooseLanguage` keeps a choice, so the page goes on following the browser until one is made.
 */

import { createLanguage } from "@jmerhar/jigkit/i18n";
import { browserStorage } from "@jmerhar/jigkit/storage";
import * as runtime from "../paraglide/runtime.js";
import type { Locale } from "../paraglide/runtime.js";

/** Where the visitor's choice of language is kept. */
export const LANGUAGE_KEY = "ecowitt-dashboard-language";

/** Each language's name, in that language, as the settings menu offers it. */
export const LANGUAGE_NAMES: Record<Locale, string> = { en: "English", "pt-PT": "Português" };

/** English writes dates and numbers with the day first and a 24-hour clock. */
const language = createLanguage(runtime, { storageKey: LANGUAGE_KEY, intl: { en: "en-GB" } });

export const useLanguageStrategies = language.useStrategies;
export const chosenLanguage = language.chosen;

/**
 * Keeps a choice of language, or forgets it when `language` is null, and reloads the page into
 * it: Paraglide's messages are read once per page.
 */
export function chooseLanguage(
  choice: Locale | null,
  storage: Storage | undefined = browserStorage(),
  reload: () => void,
): void {
  language.choose(choice, reload, storage);
}

/**
 * Settles the page's language for as long as it is open, and returns it, so that a choice made in
 * another tab cannot turn this page's words over while its API answers stay as they were.
 */
export const settleLanguage = (): Locale => language.settle();
export const intlLocale = language.intlLocale;
