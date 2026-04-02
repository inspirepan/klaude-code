import { createContext, useContext } from "react";
import en, { type Translations } from "./en";
import zh from "./zh";

export type Locale = "en" | "zh";

const locales: Record<Locale, Translations> = { en, zh };

function detectLocale(): Locale {
  const stored = localStorage.getItem("klaude:locale");
  if (stored === "en" || stored === "zh") return stored;

  const nav = navigator.language;
  if (nav.startsWith("zh")) return "zh";
  return "en";
}

let currentLocale: Locale = detectLocale();
let currentTranslations: Translations = locales[currentLocale];

export function getLocale(): Locale {
  return currentLocale;
}

export function setLocale(locale: Locale): void {
  currentLocale = locale;
  currentTranslations = locales[locale];
  localStorage.setItem("klaude:locale", locale);
}

export function t<K extends keyof Translations>(key: K): Translations[K] {
  return currentTranslations[key];
}

export const I18nContext = createContext<Locale>(currentLocale);

export function useT(): typeof t {
  // Re-read from context to trigger re-render on locale change
  useContext(I18nContext);
  return t;
}

export { type Translations } from "./en";
