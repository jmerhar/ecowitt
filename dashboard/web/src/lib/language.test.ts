import { afterEach, describe, expect, it, onTestFinished, vi } from "vitest";
import { chooseLanguage, chosenLanguage, intlLocale, LANGUAGE_KEY, match, settleLanguage, useLanguageStrategies } from "./language";
import { browserStorage, load, save, DEFAULTS } from "./prefs";
import { getLocale, overwriteGetLocale } from "../paraglide/runtime.js";
import { m } from "../paraglide/messages.js";

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

  it("follows the browser's own languages when given none", () => {
    const languages = vi.spyOn(navigator, "languages", "get").mockReturnValue(["pt", "en"]);
    useLanguageStrategies();
    expect(getLocale()).toBe("pt-PT");
    languages.mockRestore();
  });

  it("stays settled for as long as the page is open", () => {
    const pageLocale = getLocale;
    onTestFinished(() => overwriteGetLocale(pageLocale));
    useLanguageStrategies(() => ["en"]);
    expect(settleLanguage()).toBe("en");
    localStorage.setItem(LANGUAGE_KEY, "pt-PT");
    expect([getLocale(), m.settings()]).toEqual(["en", "Settings"]);
  });

  it("starts, in the browser's language, where the browser refuses its storage", () => {
    const original = Object.getOwnPropertyDescriptor(window, "localStorage")!;
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      get: () => {
        throw new DOMException("denied", "SecurityError");
      },
    });
    try {
      const reload = vi.fn();
      expect(browserStorage()).toBeUndefined();
      useLanguageStrategies(() => ["pt"]);
      expect([getLocale(), m.settings()]).toEqual(["pt-PT", "Definições"]);
      expect(chosenLanguage()).toBeNull();
      chooseLanguage("pt-PT", undefined, reload);
      expect(reload).toHaveBeenCalled();
      expect(load()).toEqual(DEFAULTS);
      expect(() => save(DEFAULTS)).not.toThrow();
    } finally {
      // Before afterEach, which clears the stored choice.
      Object.defineProperty(window, "localStorage", original);
    }
  });

  it("writes dates and numbers with the day first in English, and the Portuguese way in Portuguese", () => {
    expect(intlLocale("en")).toBe("en-GB");
    expect(intlLocale("pt-PT")).toBe("pt-PT");
    expect(intlLocale()).toBe("en-GB");
  });
});
