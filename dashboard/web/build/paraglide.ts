/**
 * How Paraglide compiles the page's messages, shared by the Vite plugin (builds, the dev server
 * and Vitest) and by compile-messages.ts, which writes them for svelte-check.
 *
 * The language is the visitor's own choice, made in the settings menu, else the first of the
 * browser's languages the page has, else English: the first two are the strategies
 * src/lib/language.ts defines.
 */
import { paraglideOptions as options } from "@jmerhar/jigkit/i18n/build";

export const paraglideOptions = options({ project: "./project.inlang", outdir: "./src/paraglide" });
