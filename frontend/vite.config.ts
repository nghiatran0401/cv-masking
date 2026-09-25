import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export const LOOPBACK_HOST = "127.0.0.1";
export const DEV_PORT = 5173;
export const PREVIEW_PORT = 4173;
export const BACKEND_ORIGIN = "http://127.0.0.1:8765";

export default defineConfig({
  plugins: [react()],
  server: {
    host: LOOPBACK_HOST,
    port: DEV_PORT,
    strictPort: true,
    proxy: {
      "/api": { target: BACKEND_ORIGIN },
    },
  },
  preview: {
    host: LOOPBACK_HOST,
    port: PREVIEW_PORT,
    strictPort: true,
  },
  test: {
    environment: "jsdom",
    include: ["tests/**/*.test.{ts,tsx}"],
    setupFiles: ["./tests/setup.ts"],
  },
});
