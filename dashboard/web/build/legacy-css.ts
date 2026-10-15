/**
 * Fallbacks in the built stylesheet for the browsers the legacy build serves (Chrome 59 and the
 * like), which lack three things the page's CSS relies on:
 *
 *  - `:where()`, in every selector Svelte scopes. A browser that cannot parse a selector drops its
 *    whole rule, so each such rule gains a copy without it, under `.legacy`.
 *  - `gap` on a grid, which they know only as `grid-gap`: every gap gains that spelling beside it.
 *  - `gap` on a flex container, which they have no spelling for at all: each flex rule with one
 *    gains a `.legacy` rule that spaces its children with margins instead.
 *
 * index.html sets the `legacy` class only in browsers that ignore ES modules, so everything under
 * it stays out of a modern browser's cascade, and `grid-gap` is an alias of `gap` there.
 */

import { transform, type Declaration, type GapValue as Gap, type Rule, type Selector, type TokenOrValue } from "lightningcss";
import type { Plugin } from "vite";

type StyleRule = Extract<Rule, { type: "style" }>["value"];

const LEGACY: Selector = [{ type: "class", name: "legacy" }, { type: "combinator", value: "descendant" }];

/**
 * A declaration every copy carries and no original does. Lightning CSS merges adjacent rules
 * with the same declarations into one selector list, which would put each copy back beside the
 * `:where()` it exists to avoid -- and a browser that cannot parse one selector drops the list.
 */
const MARK: Declaration = { property: "custom", value: { name: "--legacy", value: [{ type: "token", value: { type: "number", value: 1 } }] } } as Declaration;

/** The stylesheet with the fallbacks added. */
export function legacyCss(code: string): string {
  const result = transform({
    filename: "index.css",
    code: new TextEncoder().encode(code),
    minify: true,
    visitor: { Rule: { style: (rule) => readable(withFallbacks(rule.value)) } },
  });
  return new TextDecoder().decode(result.code);
}

/**
 * Rules as Lightning CSS reads them back. It hands out an absent optional value as null (a
 * `var()`'s `from` and `fallback`, say) but reads one back only as a missing key.
 */
function readable<T>(value: T): T {
  if (Array.isArray(value)) return value.map(readable) as T;
  if (value === null || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.entries(value).filter(([, v]) => v !== null).map(([key, v]) => [key, readable(v)]),
  ) as T;
}

/**
 * Adds the fallbacks to each stylesheet as Vite compiles it -- the page's own and every
 * component's -- rather than to the bundle it writes: the file's name is a hash of its content
 * as it stands then, and the pages are served to be cached for a year under that name.
 */
export function legacyCssPlugin(): Plugin {
  return {
    name: "legacy-css",
    apply: "build",
    transform(code, id) {
      if (!/[.&]css($|\?)/.test(id) || id.includes("?inline")) return undefined;
      return { code: legacyCss(code), map: null };
    },
  };
}

/** A rule followed by the rules it needs in a legacy browser, or undefined to leave it alone. */
function withFallbacks(rule: StyleRule): Rule[] | undefined {
  const declarations = rule.declarations?.declarations ?? [];
  const spelled = declarations.flatMap((d) => [...gridGap(d), d]);
  const scoped = rule.selectors.some((s) => s.some(isScopeWhere));
  const spacing = flexSpacing(declarations);
  if (spelled.length === declarations.length && !scoped && !spacing.length) return undefined;

  const plain = rule.selectors.map((s) => s.map((c) => (isScopeWhere(c) ? c.selectors[0][0] : c)));
  const own = { ...rule, declarations: { importantDeclarations: rule.declarations?.importantDeclarations ?? [], declarations: spelled } };
  const out: Rule[] = [{ type: "style", value: own }];
  if (scoped) {
    const declarations = { ...own.declarations, declarations: [...spelled, MARK] };
    out.push({ type: "style", value: { ...own, selectors: plain.map((s) => [...LEGACY, ...s]), declarations } });
  }
  for (const { children, margins } of spacing) {
    out.push({
      type: "style",
      value: {
        ...own,
        selectors: plain.map((s) => [...LEGACY, ...s, ...children]),
        declarations: { importantDeclarations: [], declarations: [...margins, MARK] },
        rules: [],
      },
    });
  }
  return out;
}

/** Whether a selector component is Svelte's scoping `:where(.svelte-…)`. */
function isScopeWhere(component: Selector[number]): component is Extract<Selector[number], { kind: "where" }> {
  if (component.type !== "pseudo-class" || component.kind !== "where") return false;
  const [only, ...rest] = component.selectors;
  return rest.length === 0 && only.length === 1 && only[0].type === "class" && only[0].name.startsWith("svelte-");
}

/** A gap's `grid-` spelling, to put before it; nothing for other declarations. */
function gridGap(d: Declaration): Declaration[] {
  const tokens = (gap: Gap): TokenOrValue[] | null => {
    if (gap.type === "normal") return [{ type: "length", value: { unit: "px", value: 0 } }];
    return gap.value.type === "dimension" ? [{ type: "length", value: gap.value.value }] : null;
  };
  const custom = (name: string, value: (TokenOrValue[] | null)[]): Declaration[] => {
    if (value.some((v) => v === null)) return [];
    const space: TokenOrValue = { type: "token", value: { type: "white-space", value: " " } };
    return [{ property: "custom", value: { name, value: value.flatMap((v, i) => (i ? [space, ...v!] : v!)) } }];
  };
  if (d.property === "gap") return custom("grid-gap", [tokens(d.value.row), tokens(d.value.column)]);
  if (d.property === "row-gap") return custom("grid-row-gap", [tokens(d.value)]);
  if (d.property === "column-gap") return custom("grid-column-gap", [tokens(d.value)]);
  return [];
}

/**
 * For a flex container with a gap, the rules whose margins stand in for it: a leading margin on
 * every child but the first in a single line, or a trailing one on every child of a container
 * that wraps. A selector cannot reach text, so in a row an icon that is the only element, as in
 * `<h2><svg/> Wind</h2>`, also gets the gap after it: every icon on the page leads its text.
 */
function flexSpacing(declarations: Declaration[]): { children: Selector; margins: Declaration[] }[] {
  let flex = false;
  let column = false;
  let wrap = false;
  let row: Gap = { type: "normal" };
  let col: Gap = { type: "normal" };
  for (const d of declarations) {
    if (d.property === "display") flex = d.value.type === "pair" && d.value.inside.type === "flex";
    else if (d.property === "flex-direction") column = d.value.startsWith("column");
    else if (d.property === "flex-wrap") wrap = d.value !== "nowrap";
    else if (d.property === "flex-flow") {
      column = d.value.direction.startsWith("column");
      wrap = d.value.wrap !== "nowrap";
    } else if (d.property === "gap") [row, col] = [d.value.row, d.value.column];
    else if (d.property === "row-gap") row = d.value;
    else if (d.property === "column-gap") col = d.value;
  }
  if (!flex) return [];
  const margin = (property: "margin-left" | "margin-top" | "margin-right" | "margin-bottom", gap: Gap): Declaration[] =>
    gap.type === "length-percentage" ? [{ property, value: { type: "length-percentage", value: gap.value } } as Declaration] : [];
  const child: Selector = [{ type: "combinator", value: "child" }, { type: "universal" }];
  const next: Selector = [...child, { type: "combinator", value: "next-sibling" }, { type: "universal" }];
  const icon: Selector = [
    { type: "combinator", value: "child" },
    { type: "type", name: "svg" },
    { type: "pseudo-class", kind: "only-child" },
  ];
  const rules = wrap
    ? [{ children: child, margins: [...margin("margin-right", col), ...margin("margin-bottom", row)] }]
    : column
      ? [{ children: next, margins: margin("margin-top", row) }]
      : [
          { children: next, margins: margin("margin-left", col) },
          { children: icon, margins: margin("margin-right", col) },
        ];
  return rules.filter((r) => r.margins.length);
}
