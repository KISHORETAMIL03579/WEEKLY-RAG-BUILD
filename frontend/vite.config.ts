import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// Paths the backend serves; the dev server forwards them to the API.
const API_PATHS = [
  "/api",
  "/ask",
  "/upload",
  "/upload-cancel",
  "/status",
  "/load-url",
  "/remove",
  "/clear",
  "/traces",
  "/replay",
  "/file",
  "/eval/run",
  "/eval/parse-qa-pdf",
  "/orphans",
  "/healthz",
  "/readyz",
];

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  // Point the dev proxy at the backend with VITE_API_TARGET, e.g. in frontend/.env.local:
  //   VITE_API_TARGET=http://127.0.0.1:7201
  const env = loadEnv(mode, ".", "");
  const target = env.VITE_API_TARGET || "http://127.0.0.1:5000";
  const proxy: Record<string, string> = {};
  for (const path of API_PATHS) proxy[path] = target;
  return {
    plugins: [react()],
    server: {
      port: 3000,
      proxy,
    },
    build: {
      outDir: "dist",
      emptyOutDir: true,
    },
  };
});
