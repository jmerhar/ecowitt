/**
 * Writes the page's compiled messages into src/paraglide, which is generated and not committed.
 * Vite's plugin does the same at the start of every build, dev server and test run; svelte-check
 * runs no Vite, so bin/test-web.sh runs this first.
 *
 *     node build/compile-messages.ts
 */
import { compile } from "@inlang/paraglide-js";
import { paraglideOptions } from "./paraglide.ts";

await compile(paraglideOptions);
