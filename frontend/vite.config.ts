import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test/setup.ts",
    exclude: ["**/node_modules/**", "**/dist/**", "**/e2e/**", "**/e2e-real/**"]
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:5000"
    }
  }
});
