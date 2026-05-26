// Post-build: calculate SHA-384 of each JS/CSS asset in dist/assets/ and add
// integrity="sha384-..." crossorigin="anonymous" to the corresponding <script>
// and <link> tags in dist/index.html.
//
// Run via: node scripts/add-sri-to-dist.js
// Integrated in package.json "build" script: vite build && node scripts/add-sri-to-dist.js
//
// C65: SRI for dist/assets/*.{js,css} — defense in depth against CDN/proxy tampering.
// Note: SRI on same-origin assets is defense-in-depth (not strictly required), but
// ensures that a compromised build artifact is detectable by the browser.

import { readFileSync, writeFileSync, readdirSync } from "node:fs";
import { createHash } from "node:crypto";
import { resolve, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = fileURLToPath(new URL(".", import.meta.url));
const projectRoot = resolve(__dirname, "..");
const distDir = join(projectRoot, "dist");
const distHtml = join(distDir, "index.html");
const assetsDir = join(distDir, "assets");

// Check dist exists (skip gracefully if called before build)
let html;
try {
  html = readFileSync(distHtml, "utf-8");
} catch {
  console.warn("[sri] dist/index.html not found — run vite build first");
  process.exit(0);
}

// Find JS and CSS assets
let assets;
try {
  assets = readdirSync(assetsDir)
    .filter((f) => f.endsWith(".js") || f.endsWith(".css"))
    .map((f) => join(assetsDir, f));
} catch {
  console.warn("[sri] dist/assets/ not found — skipping SRI");
  process.exit(0);
}

if (assets.length === 0) {
  console.info("[sri] no assets found in dist/assets/ — nothing to do");
  process.exit(0);
}

// B19: Vite already emits `crossorigin` (empty = anonymous-implicit) on <script type="module">
// tags. If we add crossorigin="anonymous" on top, the element ends up with two crossorigin
// attributes. HTML parsers silently ignore the second one (first-wins), so it's semantically
// equivalent, but it's invalid HTML and confusing in audits.
// Fix: strip any existing crossorigin attribute before we inject our own.
function stripExistingCrossorigin(src) {
  // Matches: crossorigin, crossorigin="", crossorigin="anonymous", crossorigin="use-credentials"
  return src.replace(/\s+crossorigin(="[^"]*")?/g, "");
}

let modified = 0;
for (const assetPath of assets) {
  const content = readFileSync(assetPath);
  const hash = createHash("sha384").update(content).digest("base64");
  const sri = `integrity="sha384-${hash}" crossorigin="anonymous"`;

  // Relative URL as it appears in index.html: /assets/filename.js
  const relPath = "/assets/" + assetPath.split("/assets/").pop();

  // Escape special regex chars in the path
  const escapedPath = relPath.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

  // Match <script src="..."> and <link href="..."> that don't already have integrity=
  const scriptRe = new RegExp(
    `(<script[^>]+src="${escapedPath}"(?![^>]*integrity)[^>]*)(>)`,
    "g"
  );
  const linkRe = new RegExp(
    `(<link[^>]+href="${escapedPath}"(?![^>]*integrity)[^>]*)(>)`,
    "g"
  );

  const before = html;
  // B19: strip existing crossorigin before injecting ours (avoids duplicate attribute)
  html = html.replace(scriptRe, (_, tag, close) => `${stripExistingCrossorigin(tag)} ${sri}${close}`);
  html = html.replace(linkRe, (_, tag, close) => `${stripExistingCrossorigin(tag)} ${sri}${close}`);

  if (html !== before) {
    console.info(`[sri] added integrity to ${relPath}`);
    modified++;
  }
}

writeFileSync(distHtml, html);

if (modified > 0) {
  console.info(`[sri] SRI added to ${modified} asset(s) in dist/index.html`);
} else {
  console.info("[sri] no tags updated (assets may already have integrity or use different paths)");
}
