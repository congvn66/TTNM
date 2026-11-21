import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // The shared root .env owns deployment flags such as VITE_AUTH_REQUIRED.
  // Vite only exposes variables prefixed with VITE_, so backend secrets in
  // the same file are never injected into the browser bundle.
  envDir: "../..",
  server: {
    host: "127.0.0.1",
    port: 4173,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
      "/health": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  preview: { host: "127.0.0.1", port: 4173, strictPort: true },
});
