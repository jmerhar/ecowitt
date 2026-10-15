# More languages for the dashboard

Translate the dashboard into the languages most people who run an Ecowitt station read, so that
someone who finds this project can share their station's page with a household or neighbours in
their own language. The dashboard is in English and European Portuguese; the mechanism for more
is in place (CLAUDE.md, *Adding a language touches both halves*), so each language is a
translation and a review, not new code.

## Why

Ecowitt's consoles (the HP2551 among them) sell across Europe and beyond, and the people a station's
page is for -- a household, a family elsewhere, neighbours -- read their own language best. A
visitor whose browser asks for a language the page lacks gets English.

## Which languages, and in what order

Latin-script languages written left to right, with at most one singular and one plural, need
nothing but their translations. Roughly by Ecowitt's European audience:

1. **German.** Probably its largest market in Europe. The DWD (Germany's weather service) has
   established terms for the Beaufort scale and the WMO weather codes.
2. **Spanish** and **French.** Large audiences; AEMET's and Météo-France's vocabulary to follow.
3. **Dutch.** A smaller but common market; KNMI's terms.
4. **Italian.**
5. **Brazilian Portuguese.** A Brazilian browser gets the European Portuguese now, which reads as
   foreign ("ecrã", "definições") and names the Beaufort forces differently. A `pt-BR` catalogue
   sits beside `pt-PT`; `language.ts` and the API's `_match` then send plain "pt" to whichever
   sorts first, which has to be decided.

Harder, each for a reason the page does not handle yet:

- **Slavic languages** (Polish, Czech, Slovene): three or four plural forms. The page matches
  counts exactly (`count=1`, because Paraglide's `plural` selector needs `Intl.PluralRules`,
  which Chrome 59 lacks), so "N sensors need attention" needs a variant per form, and the API's
  catalogue its language's gettext plural forms.
- **Right-to-left** (Arabic, Hebrew): every card's layout, the compass and the charts' axes
  mirror; Paraglide's runtime gives the direction, the page does not use it.
- **Chinese, Japanese, Korean:** fonts, line breaking in narrow cards, and Chrome 59's locale data
  for them on the wall tablet.

## For each language

- **Page:** its locale in `dashboard/web/project.inlang/settings.json`, a
  `dashboard/web/messages/<locale>.json` with all of the page's messages (159), and its name and
  Intl locale in `src/lib/language.ts` (`LANGUAGE_NAMES`, `INTL`).
- **API:** `bin/messages.py --add <locale>`, then translate the catalogue it starts (122
  messages): notices, the summary, the sky, Beaufort and compass names, metric, model and sensor
  labels, the home-screen description.
- **Times:** a message naming a time of day has a form chosen by its hour (on the page an exact
  `hour=1` match, in the API gettext's plural forms). A language whose words do not agree with
  the hour uses one form for all.
- **Review:** a native speaker, for naturalness rather than fidelity, as the Portuguese had; the
  national weather service's terms for Beaufort, the sky and the pressure tendency, looked up
  rather than translated.
- **Checks:** both test suites (the API's fails on an untranslated message; the page's only on a
  missing one, so read the file through), and `make test-legacy-browser` with the language added
  to `LANGUAGES` in `dashboard/web/legacy-browser/failures.mjs`, since Chrome 59 must format its
  dates and numbers.
- **Cost:** a few hours of translation and an hour of review per language.

## Open questions

- Whether to take translations from contributors, and how to review a language nobody on the
  project reads: a second native speaker, or a translation platform (Weblate, Crowdin) that
  reads `.po` and the inlang message format.
- Where "pt" goes once there are two Portuguese.
- Whether the README should list the languages, or the page's *Language* menu is enough.

## Done when

German, Spanish, French and Dutch each have a reviewed page and API catalogue, the Chromium 59
check loads the page in each, and a browser asking for any of them sees no English.
