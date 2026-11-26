import { readFileSync } from "node:fs";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The repo-root VERSION file is the one place the version lives; it is baked in at build time.
const appVersion = readFileSync(new URL("../VERSION", import.meta.url), "utf-8").trim();

export default defineConfig({
  plugins: [react()],
  define: {
    __APP_VERSION__: JSON.stringify(appVersion),
  },
  server: {
    port: 5173,
    // Listen on the LAN too, so a phone on the same Wi-Fi can open the dev server.
    host: true,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/media": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/static": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/api/render/ws": {
        target: "ws://localhost:8000",
        ws: true,
      },
    },
  },
});
