# Localisation

Show the dashboard in the visitor's language. Any later client of the same API, such as a native
Android dashboard, must support the same languages without repeating the work.

## Why

The page and the API are English throughout. A station's dashboard is often shared with family
and neighbours who read another language better, and a weather page is mostly short phrases
and numbers, so it translates well.

## Where the English is

- **The API writes prose.** It does not only send values.
  - `weather.py`: the 13 Beaufort names, the 16 compass points and the pressure tendency
    (`"rising slowly"`).
  - `core/weathermodel.py`: the WMO weather-code descriptions and the model labels
    (`"Best for this location"`).
  - `catalogue.py`: about 20 metric labels, served by `/meta` and used as chart tab and series
    names.
  - `service.py`:
    - the notices (`"Cold: frost is possible on clear nights."`,
      `"Rain likely from tomorrow 06:00."`, `"Damp: Kitchen, Bedroom."`);
    - the one-line `summary` (`"Gentle breeze from the NW. Pressure falling."`);
    - `SENSOR_NAMES` (`"Rain gauge"`, `"Light sensor"`).
  - `app.py`: the web app manifest's `description`, and the default site title.
- **The page depends on that English.**
  - `NowCard.svelte` splits `summary` on `". "` and compares its first part with
    `sky.description`.
  - `PressureCard.svelte` compares `tendency` with `"steady"` and capitalises its first letter.
  - `service.py` removes one notice's sentence from another with `str.replace`.
- **The page's own strings.** About 120 strings are spread over the components, `format.ts`
  (`"just now"`, `"Today"`, the UV words), `levels.ts` (`"Muggy"`) and `prefs.ts`. Some are built
  by concatenation (`` `tomorrow ${time}` ``, `` `${minutes} min ago` ``), which cannot be
  translated as it stands.
- **Already language-neutral.**
  - `format.ts` formats dates and numbers through `Intl`, and most functions take a `locale`.
  - The API already sends codes beside its words: `weather_code`, `beaufort`, `airing.advice`
    and room `flags`.
  - Station and room names are the operator's own and are not translated.

## Design

Two layers. The API sends structure that any client can act on, plus text in the requested
language for display. Each client translates only its own interface.

### 1. The API sends codes

Each piece of prose gets a code that carries its meaning, so that no client ever parses text.
`models.py` declares the codes as enums, so the OpenAPI document publishes them and a generated
client (TypeScript, Kotlin) gets typed values.

- **Notices** become a list of `{code, params, level}`, and a card may have several. Codes
  include:
  - `cold`, `heat`, `humid_air`, `dry_air`;
  - `strong_gusts`, `heavy_rain`, `pressure_falling_fast`, `uv_very_high`;
  - `rain_soon`, `rain_from {time}`, `frost_forecast {value, time}`, `heat_forecast {value, time}`,
    `gusts_forecast {value, time}`;
  - `room_flag {flag, rooms}`.

  When the forecast's frost replaces the present reading's hint of it, the `cold` entry is
  dropped from the list instead of a sentence being edited.
- **The summary** becomes a list of parts, such as `{code: "wind", beaufort, compass_deg}` or
  `{code: "raining", rate}`. Deciding what goes into it stays on the server: which parts, and
  feels-like only when it differs by 1° or more. Clients do not repeat that logic.
- **The tendency** becomes a code (`steady`, `rising_slowly`, …, `falling_very_rapidly`).
- **Wind direction** is sent in degrees beside `compass`. The compass letters are themselves
  language-specific: east is O (Ost) in German, and west is O (Ouest) in French.
- **Metric labels** are keyed by the metric `id` that `/meta` already sends.

This step is worth doing on its own, in English only, because it removes the places where the
page depends on the API's exact wording.

### 2. The API renders text in the requested language

- **Language negotiation:** `Accept-Language`, overridden by `?lang=`, matched against the
  catalogues there are and falling back to English. The answer states the language it used.
- **Every coded item also carries `text`** in that language: notices, summary parts, Beaufort
  names, weather descriptions, tendency, metric and model labels, and sensor names. Clients take
  their logic (icons, colours, badges, sorting) from the code and display the `text`.
- **Why the server and not each client:**
  - The wording and how sentences are assembled exist once, not once per client.
  - An older Android app that gets a code it does not know still shows its `text`.
  - A new language or a corrected translation ships with a server deploy, not an app release.
- **Catalogue:** gettext `.po` files managed with Babel, Python's standard i18n toolchain,
  in `dashboard/api`. `messages.py` holds the English source strings each code is worded
  with. Babel also formats what goes into them by the language's rules: `format_list` for the
  rooms (`"Kitchen and Bedroom"`), and times and numbers.
- **Cache:** the service caches what it reads in stored units and converts each answer per
  request. Text is rendered at the same stage, after the cache, so the cache does not grow per
  language.
- **Times inside text** (`"from tomorrow 06:00"`) are formatted in the station's time zone with
  the language's own conventions. The params also carry the ISO time, so a client can format
  it itself.

### 3. Each client translates its own interface

Tab names, button labels, the units menu, `"Feels like"`, `"just now"` and `"Today"` stay in
the client: they are needed before any answer arrives, and each client has screens of its own.

- **Web page:** Paraglide JS, the i18n library Svelte's own CLI sets up (`sv add paraglide`).
  Its messages compile to typed functions, so a missing key fails `svelte-check`. Adding it
  means regenerating the lockfile with `bin/lockfile.sh`, and the legacy build must still pass
  `make test-legacy-browser`.
  - The language comes from `navigator.languages` by default. The menu offers an override,
    kept under a key of its own (`language.ts`).
  - `LOCALE` in `format.ts` becomes the chosen language's locale, with day-first dates and a
    24-hour clock forced for English (`en-GB`).
  - `<html lang>` follows the chosen language.
- **Android:** `strings.xml` with its plural resources, and `java.time` with the chosen locale.
  Android 13's per-app language setting replaces the web page's menu override.
- **One source for both** (optional): once both clients exist and share most of their
  interface, generate Paraglide's messages and `strings.xml` from one source file. This
  is easiest if the Android app lives in this repository.

### Not translated

- The dashboard's `/setup` page, which only the operator sees.
- The collector's admin pages.
- The Grafana dashboard and alert rules.

## Testing

- **Catalogue completeness:** a test that every key and every enum code has a message in every
  catalogue, and that no catalogue has keys nothing uses, in the spirit of `known_keys.txt`.
- **Placeholders:** each translation uses exactly the placeholders of its English source.
- **Existing tests** keep asserting English. One answer per card, rendered in a second
  language, pins the negotiation and the fallback.
- **Mutation-check the codes:** drop a notice code from the page's handling or from a
  catalogue, and confirm a test fails.
- **Review each language** by a native speaker for naturalness and consistency, not word for
  word. Beaufort names, WMO weather descriptions and tendency terms have established
  translations in most languages; look those up rather than translating them.

## Order

1. Codes in the API, English only, beside the English fields. *Done.*
2. The page uses the codes and stops parsing prose. *Done.*
3. Server-side catalogue, language negotiation and `text`. *Done, with European Portuguese.*
4. The page's own catalogue and language preference. *Done, with Paraglide.*
5. First additional language. *Done: European Portuguese.*

Effort: about 2–3 days for steps 1–2, 1–2 days for step 3 and 1–2 days for step 4. Each
language after that takes a few hours plus review.

## Open questions

- Which languages first.
- Whether the operator sets a default language in `dashboard.yaml`, for visitors whose browser
  asks for a language there is no catalogue for.
- Whether `/series` and `/extremes` also take `lang`, for their metric labels, or whether
  clients look those up from `/meta`.
- How long to keep the English-only fields once the codes ship.

## Done when

A visitor whose browser prefers a supported language sees every word of the dashboard in it,
the page no longer parses any API text, and a second client can show the same notices and
summary in the same languages from the API alone.
