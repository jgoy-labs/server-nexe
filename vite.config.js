import { defineConfig } from "vite";

const host = process.env.TAURI_DEV_HOST;

// F066: configurable port via VITE_PORT to prevent collision in multi-fork dev
const port = parseInt(process.env.VITE_PORT || "1420", 10);

// Vite config for nexe-app — scaffold with `src/` as root, `dist/` as output.
// Tauri integration: https://v2.tauri.app/start/frontend/vite/
export default defineConfig(() => ({
  root: "src",
  // Phase 1: public/ holds the server-nexe web UI (static assets copied as-is).
  // Vite copies publicDir into dist/ without processing — UI assets stay verbatim.
  publicDir: "../public",

  build: {
    outDir: "../dist",
    emptyOutDir: true,
    // Targets compatible with WKWebView (macOS Safari 15+) and WebKitGTK.
    // Tauri 2.10 requires macOS 13+ (Safari 16) and WebKitGTK 4.1 (~Safari 15).
    target: process.env.TAURI_ENV_PLATFORM === "windows" ? "chrome105" : "safari15",
    // F053: force esbuild to avoid @rolldown/* prerelease (unaudited CI binary).
    minify: process.env.TAURI_ENV_DEBUG ? false : "esbuild",
    sourcemap: !!process.env.TAURI_ENV_DEBUG,
    // C65: SRI via post-build script (scripts/add-sri-to-dist.js).
    // Integrated in package.json "build": "vite build && node scripts/add-sri-to-dist.js"
  },

  clearScreen: false,

  server: {
    // F066: port via env VITE_PORT (default 1420) — avoids collision in multi-fork
    port,
    strictPort: true,
    host: host || false,
    hmr: host
      ? { protocol: "ws", host, port: port + 1 }
      : undefined,
    watch: {
      // Do not rebuild when Rust changes.
      ignored: ["**/src-tauri/**"],
    },
  },

  // vitest config (JS unit tests) — absolute root to the project, not Vite's `root: "src"`
  test: {
    environment: "node",
    root: process.cwd(),
    include: ["src/**/*.test.js", "isolation-frame/**/*.test.js"],
  },
}));
