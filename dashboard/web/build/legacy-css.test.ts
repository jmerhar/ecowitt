import { describe, expect, it } from "vitest";
import { legacyCss, legacyCssPlugin } from "./legacy-css";

/** A flat rule with its declarations in order, since Lightning CSS chooses its own. */
const sorted = (rule: string) => rule.replace(/\{(.*)\}$/, (_, body: string) => `{${body.split(";").sort().join(";")}}`);

/** The rules of a flat stylesheet, as it comes out with the fallbacks. */
const rules = (css: string) =>
  legacyCss(css)
    .split("}")
    .filter(Boolean)
    .map((r) => sorted(`${r}}`));

/** Expected rules, in the same form. */
const as = (...expected: string[]) => expected.map(sorted);

describe("legacyCss", () => {
  it("copies a rule Svelte scoped with :where() under .legacy, without it", () => {
    expect(rules(".bar.svelte-x span:where(.svelte-x){display:block;height:100%}")).toEqual(as(
      ".bar.svelte-x span:where(.svelte-x){height:100%;display:block}",
      ".legacy .bar.svelte-x span.svelte-x{--legacy:1;height:100%;display:block}",
    ));
  });

  it("copies the whole selector list when one of them needs it", () => {
    expect(rules(".a,.b:where(.svelte-x){color:red}")).toEqual(as(
      ".a,.b:where(.svelte-x){color:red}",
      ".legacy .a,.legacy .b.svelte-x{--legacy:1;color:red}",
    ));
  });

  it("keeps each copy apart from the rule it copies, though their declarations match", () => {
    expect(legacyCss(".a:where(.svelte-x){color:red}.b{color:red}")).not.toMatch(/:where\([^)]*\),\.legacy|\.legacy[^{]*:where/);
  });

  it("leaves other :where() selectors, and rules that need nothing, as they were", () => {
    const css = "a:where(.b,.c){color:red}p:where(.other){margin:0}.plain{color:blue}";
    expect(legacyCss(css)).toBe("a:where(.b,.c){color:red}p:where(.other){margin:0}.plain{color:#00f}");
  });

  it("gives every gap its grid- spelling", () => {
    expect(rules(".g{display:grid;gap:1rem 2px}")).toEqual(as(".g{grid-gap:1rem 2px;gap:1rem 2px;display:grid}"));
    expect(rules(".g{row-gap:1rem;column-gap:0}")).toEqual(as(".g{grid-row-gap:1rem;grid-column-gap:0px;gap:1rem 0}"));
    expect(rules(".g{gap:normal 1rem}")).toEqual(as(".g{grid-gap:0px 1rem;gap:normal 1rem}"));
    expect(rules(".g{gap:5%}")).toEqual(as(".g{gap:5%}"));
  });

  it("spaces a flex row's children with a leading margin on all but the first", () => {
    expect(rules(".f{display:flex;gap:.5rem 1rem}")).toEqual(as(
      ".f{grid-gap:.5rem 1rem;gap:.5rem 1rem;display:flex}",
      ".legacy .f>*+*{--legacy:1;margin-left:1rem}",
    ));
    expect(rules(".f{display:inline-flex;column-gap:3px}")).toContainEqual(sorted(".legacy .f>*+*{--legacy:1;margin-left:3px}"));
  });

  it("spaces a flex column's children with a margin above", () => {
    expect(rules(".f{display:flex;flex-direction:column;gap:.5rem 1rem}")).toContainEqual(sorted(".legacy .f>*+*{--legacy:1;margin-top:.5rem}"));
    expect(rules(".f{display:flex;flex-flow:column;row-gap:2px}")).toContainEqual(sorted(".legacy .f>*+*{--legacy:1;margin-top:2px}"));
  });

  it("gives every child of a wrapping flex container the gap after it, both ways", () => {
    expect(rules(".f{display:flex;flex-wrap:wrap;gap:.5rem 1rem}")).toContainEqual(sorted(
      ".legacy .f>*{--legacy:1;margin-bottom:.5rem;margin-right:1rem}",
    ));
    expect(rules(".f{display:flex;flex-flow:row wrap;column-gap:1rem}")).toContainEqual(sorted(".legacy .f>*{--legacy:1;margin-right:1rem}"));
  });

  it("spaces nothing without a gap, or outside a flex container", () => {
    expect(rules(".f{display:flex}")).toEqual(as(".f{display:flex}"));
    expect(rules(".f{display:flex;gap:normal}")).toEqual(as(".f{grid-gap:0px 0px;gap:normal;display:flex}"));
    expect(rules(".f{display:block;gap:1rem}")).toEqual(as(".f{grid-gap:1rem 1rem;gap:1rem;display:block}"));
  });

  it("spaces a scoped flex container's children by a selector a legacy browser can read", () => {
    expect(rules(".f.svelte-x{display:flex;gap:1rem}")).toContainEqual(sorted(".legacy .f.svelte-x>*+*{--legacy:1;margin-left:1rem}"));
    expect(rules("p:where(.svelte-x){display:flex;gap:1rem}")).toEqual(as(
      "p:where(.svelte-x){grid-gap:1rem 1rem;gap:1rem;display:flex}",
      ".legacy p.svelte-x{--legacy:1;grid-gap:1rem 1rem;gap:1rem;display:flex}",
      ".legacy p.svelte-x>*+*{--legacy:1;margin-left:1rem}",
    ));
  });

  it("keeps a copy inside the media query of the rule it copies", () => {
    // Vite's own minifier prints the query for the build's targets afterwards.
    expect(legacyCss("@media (min-width:40rem){.f{display:flex;gap:1rem}}")).toMatch(
      /^@media [^{]+\{\.f\{[^}]+\}\.legacy \.f>\*\+\*\{[^}]+\}\}$/,
    );
  });

  it("carries custom properties and var() through unchanged", () => {
    const css = ":root{--bg:#fff}.a:where(.svelte-x){background:var(--bg);color:var(--fg,red)}";
    expect(rules(css)).toEqual(as(
      ":root{--bg:#fff}",
      ".a:where(.svelte-x){background:var(--bg);color:var(--fg,red)}",
      ".legacy .a.svelte-x{--legacy:1;background:var(--bg);color:var(--fg,red)}",
    ));
  });
});

describe("legacyCssPlugin", () => {
  const transform = legacyCssPlugin().transform as (code: string, id: string) => { code: string } | undefined;

  it("rewrites the page's stylesheet and each component's as Vite compiles them", () => {
    expect(transform(".a:where(.svelte-x){color:red}", "/src/app.css")?.code).toContain(".legacy .a.svelte-x");
    expect(transform(".a{color:red}", "/src/Chart.svelte?svelte&type=style&lang.css")?.code).toBe(".a{color:red}");
  });

  it("leaves everything else alone", () => {
    expect(transform("export default 1", "/src/main.ts")).toBeUndefined();
    expect(transform(".a{}", "/src/app.css?inline")).toBeUndefined();
  });

  it("runs only in a build", () => {
    expect(legacyCssPlugin().apply).toBe("build");
  });
});
