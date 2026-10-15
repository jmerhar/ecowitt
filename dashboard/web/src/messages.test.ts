import { describe, expect, it } from "vitest";
import en from "../messages/en.json";
import pt from "../messages/pt-PT.json";

/** Every text a message can give: a plain string, or each of its variants. */
function texts(message: unknown): string[] {
  if (typeof message === "string") return [message];
  return (message as { match: Record<string, string> }[]).flatMap((m) => Object.values(m.match));
}

/** The placeholders in a text. */
function placeholders(text: string): Set<string> {
  return new Set(text.match(/{\w+}/g) ?? []);
}

describe("the page's messages", () => {
  // Paraglide falls back to English for a message a language lacks, so a missing one would show
  // up only as an English word on a Portuguese page.
  it("are in every language", () => {
    expect(Object.keys(pt)).toEqual(Object.keys(en));
  });

  it("name nothing their English does not", () => {
    const english = en as Record<string, unknown>;
    const strays = Object.entries(pt as Record<string, unknown>).flatMap(([key, message]) => {
      if (key === "$schema") return [];
      const allowed = new Set(texts(english[key]).flatMap((text) => [...placeholders(text)]));
      return texts(message)
        .flatMap((text) => [...placeholders(text)])
        .filter((name) => !allowed.has(name))
        .map((name) => `${key}: ${name}`);
    });
    expect(strays).toEqual([]);
  });
});
