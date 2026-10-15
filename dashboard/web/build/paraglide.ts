/**
 * How Paraglide compiles the page's messages, shared by the Vite plugin (builds, the dev server
 * and Vitest) and by compile-messages.ts, which writes them for svelte-check.
 *
 * The language is the visitor's own choice, made in the settings menu, else the first of the
 * browser's languages the page has, else English: the first two are the page's own strategies,
 * defined in src/lib/language.ts.
 */
export const paraglideOptions = {
  project: "./project.inlang",
  outdir: "./src/paraglide",
  strategy: ["custom-choice", "custom-browser", "baseLocale"] as ("custom-choice" | "custom-browser" | "baseLocale")[],
};
