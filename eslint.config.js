import js from "@eslint/js";
import globals from "globals";

export default [
    js.configs.recommended,
    // Browser files: src/, isolation-frame/, plugins-dev/, public/ (non-test)
    {
        files: ["src/**/*.js", "isolation-frame/**/*.js", "plugins-dev/**/*.js", "public/**/*.js"],
        ignores: ["**/*.test.js"],
        languageOptions: {
            ecmaVersion: 2022,
            sourceType: "module",
            globals: { ...globals.browser },
        },
        rules: {
            "no-unused-vars": ["warn", { "argsIgnorePattern": "^_", "caughtErrorsIgnorePattern": "^_" }],
            // Security checks intentionally use control-char regexes (/[\x00-\x1F\x7F]/)
            "no-control-regex": "off",
            // catch (_) is intentional — rethrow new typed error, not the original
            "preserve-caught-error": "off",
        },
    },
    // Node.js files: scripts/, vite.config.js, test files (vitest runs in node)
    {
        files: ["scripts/**/*.js", "vite.config.js", "**/*.test.js"],
        languageOptions: {
            ecmaVersion: 2022,
            sourceType: "module",
            globals: { ...globals.node },
        },
        rules: {
            "no-unused-vars": ["warn", { "argsIgnorePattern": "^_" }],
        },
    },
    {
        ignores: [
            "dist/**",
            "node_modules/**",
            "src-tauri/target/**",
            "target/**",
            // Vendored web UI (audited at origin repo, not here — see pyproject.toml exclude_globs)
            "public/ui/static/**",
            // Minified libs (vendored)
            "**/*.min.js",
        ],
    },
];
