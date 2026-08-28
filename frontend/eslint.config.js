import js from "@eslint/js";
import tsPlugin from "@typescript-eslint/eslint-plugin";
import tsParser from "@typescript-eslint/parser";
import reactHooks from "eslint-plugin-react-hooks";

export default [
  { ignores: ["dist", "node_modules", "playwright-report", "test-results", "src/generated/**"] },
  js.configs.recommended,
  {
    files: ["src/**/*.{ts,tsx}"],
    languageOptions: {
      parser: tsParser,
      parserOptions: {
        ecmaVersion: "latest",
        sourceType: "module",
        ecmaFeatures: { jsx: true },
      },
    },
    plugins: {
      "@typescript-eslint": tsPlugin,
      "react-hooks": reactHooks,
    },
    rules: {
      ...tsPlugin.configs.recommended.rules,
      ...reactHooks.configs.recommended.rules,
      // TypeScript strict mode is the source of truth for symbol resolution.
      // ESLint's JS-only no-undef rule incorrectly flags DOM/React type names.
      "no-undef": "off",
      "react-hooks/set-state-in-effect": "off",
      // This compiler-oriented rule rejects existing hoisted local helpers even
      // though they do not mutate captured values. Keep the established hooks
      // correctness rules (rules-of-hooks/exhaustive-deps/refs) enabled.
      "react-hooks/immutability": "off",
      "@typescript-eslint/no-explicit-any": "off",
      "@typescript-eslint/no-unused-vars": ["warn", { argsIgnorePattern: "^_" }],
    },
  },
];
