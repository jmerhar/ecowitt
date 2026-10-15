import "@testing-library/jest-dom/vitest";
import { useLanguageStrategies } from "./lib/language";

// The page's own start-up registers this too; the tests run in jsdom's English.
useLanguageStrategies();
