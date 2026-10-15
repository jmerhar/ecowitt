import { afterEach, describe, expect, it, vi } from "vitest";
import { chooseLanguage, chosenLanguage, intlLocale, LANGUAGE_KEY, match, useLanguageStrategies } from "./language";
import { getLocale } from "../paraglide/runtime.js";

function memory(entries: Record<string, string> = {}): Storage {
  const data = new Map(Object.entries(entries));
  return {
    get length() {
      return data.size;
    },
    clear: () => data.clear(),
    getItem: (key) => data.get(key) ?? null,
    key: (index) => [...data.keys()][index] ?? null,
    removeItem: (key) => void data.delete(key),
    setItem: (key, value) => void data.set(key, value),
  };
}

const refusing = {
  getItem: () => {
    throw new DOMException("denied");
  },
  setItem: () => {
    throw new DOMException("denied");
  },
  removeItem: () => {
    throw new DOMException("denied");
  },
} as unknown as Storage;

describe("match", () => {
  it.each([
    [["pt-PT"], "pt-PT"],
    [["PT-pt"], "pt-PT"],
    [["pt"], "pt-PT"],
    [["pt-BR", "en"], "pt-PT"],
    [["de", "en-US", "pt"], "en"],
    [["de", "fr"], undefined],
    [[], undefined],
  ])("finds the first language the page has among %j", (wanted, found) => {
    expect(match(wanted)).toBe(found);
  });
});

describe("the page's language", () => {
  afterEach(() => {
    localStorage.removeItem(LANGUAGE_KEY);
    useLanguageStrategies();
  });

  it("follows the browser's languages, matched by their first part", () => {
    useLanguageStrategies(() => ["pt", "en"]);
    expect(getLocale()).toBe("pt-PT");
    useLanguageStrategies(() => ["de"]);
    expect(getLocale()).toBe("en");
  });

  it("is the visitor's own choice before the browser's", () => {
    useLanguageStrategies(() => ["en"]);
    localStorage.setItem(LANGUAGE_KEY, "pt-PT");
    expect(getLocale()).toBe("pt-PT");
  });

  it("does not keep a language read from the browser as the visitor's choice", () => {
    useLanguageStrategies(() => ["pt"]);
    expect(getLocale()).toBe("pt-PT");
    expect(chosenLanguage()).toBeNull();
    expect(Object.keys(localStorage)).toEqual([]);
  });

  it("reads the visitor's choice, ignoring one the page does not have", () => {
    expect(chosenLanguage(memory({ [LANGUAGE_KEY]: "pt-PT" }))).toBe("pt-PT");
    expect(chosenLanguage(memory({ [LANGUAGE_KEY]: "xx" }))).toBeNull();
    expect(chosenLanguage(memory())).toBeNull();
    expect(chosenLanguage(refusing)).toBeNull();
  });

  it("keeps a choice, or forgets it, and reloads into it", () => {
    const storage = memory();
    const reload = vi.fn();
    chooseLanguage("pt-PT", storage, reload);
    expect(storage.getItem(LANGUAGE_KEY)).toBe("pt-PT");
    chooseLanguage(null, storage, reload);
    expect(storage.getItem(LANGUAGE_KEY)).toBeNull();
    expect(reload).toHaveBeenCalledTimes(2);
  });

  it("stays as it is when the choice cannot be kept", () => {
    const reload = vi.fn();
    chooseLanguage("pt-PT", refusing, reload);
    expect(reload).not.toHaveBeenCalled();
  });

  it("writes dates and numbers with the day first in English, and the Portuguese way in Portuguese", () => {
    expect(intlLocale("en")).toBe("en-GB");
    expect(intlLocale("pt-PT")).toBe("pt-PT");
    expect(intlLocale()).toBe("en-GB");
  });
});
