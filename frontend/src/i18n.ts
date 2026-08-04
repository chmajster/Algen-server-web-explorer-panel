import enUS from "./locales/en-US.json";
import plPL from "./locales/pl-PL.json";

export type Language = "pl-PL" | "en-US";
export const supportedLanguages: Language[] = ["pl-PL", "en-US"];

const dockerActionOverrides: Record<Language, Record<string, string>> = {
  "pl-PL": {
    "docker.kill": "Zatrzymaj force",
    "docker.stopTimeout": "Łagodne zatrzymanie bez limitu czasu",
  },
  "en-US": {
    "docker.kill": "Force stop",
    "docker.stopTimeout": "Graceful stop without a time limit",
  },
};

const dictionaries: Record<Language, Record<string, string>> = {
  "pl-PL": { ...plPL, ...dockerActionOverrides["pl-PL"] },
  "en-US": { ...enUS, ...dockerActionOverrides["en-US"] },
};

export function detectLanguage(language?: string | null): Language {
  if (language && supportedLanguages.includes(language as Language)) return language as Language;
  const browser = navigator.language.toLowerCase();
  if (browser.startsWith("en")) return "en-US";
  if (browser.startsWith("pl")) return "pl-PL";
  return "pl-PL";
}

export function translate(language: Language, key: string) {
  return dictionaries[language][key] || dictionaries["pl-PL"][key] || key;
}
