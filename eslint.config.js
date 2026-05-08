import js from "@eslint/js";

export default [
  {
    ignores: [
      "node_modules/**",
      ".test_venv/**",
      "venv/**",
      "InstallNexe.app/**",
      "Nexe.app/**",
      "**/marked.min.js",
      "**/lucide.min.js"
    ]
  },
  js.configs.recommended,
  {
    files: ["plugins/**/ui/**/*.js"],
    languageOptions: {
      ecmaVersion: "latest",
      globals: {
        window: "readonly",
        document: "readonly",
        console: "readonly",
        fetch: "readonly",
        setTimeout: "readonly",
        clearTimeout: "readonly",
        setInterval: "readonly",
        clearInterval: "readonly",
        navigator: "readonly",
        location: "readonly",
        history: "readonly",
        localStorage: "readonly",
        sessionStorage: "readonly",
        Event: "readonly",
        EventSource: "readonly",
        FormData: "readonly",
        URLSearchParams: "readonly",
        URL: "readonly",
        MutationObserver: "readonly",
        ResizeObserver: "readonly",
        Node: "readonly",
        marked: "readonly",
        lucide: "readonly"
      }
    }
  }
];
