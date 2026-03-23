import { useState } from "react";
import { I18nContext, getLocale, setLocale, type Locale } from "./index";
import { useMountEffect } from "@/hooks/useMountEffect";

export function I18nProvider({ children }: { children: React.ReactNode }): JSX.Element {
  const [locale, setLocaleState] = useState<Locale>(getLocale);

  useMountEffect(() => {
    const handler = (e: StorageEvent) => {
      if (e.key === "klaude:locale" && (e.newValue === "en" || e.newValue === "zh")) {
        setLocale(e.newValue);
        setLocaleState(e.newValue);
      }
    };
    window.addEventListener("storage", handler);
    return () => {
      window.removeEventListener("storage", handler);
    };
  });

  // Expose a global function for switching locale programmatically
  useMountEffect(() => {
    (window as unknown as Record<string, unknown>).__klaudeSetLocale = (l: Locale) => {
      setLocale(l);
      setLocaleState(l);
    };
  });

  return <I18nContext.Provider value={locale}>{children}</I18nContext.Provider>;
}
