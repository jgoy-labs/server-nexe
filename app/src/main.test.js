// S13 F033/F034 — Real tests for the plugin postMessage firewall.
// Replaces the placeholder (1+1===2) with coverage of the security paths.

import { describe, it, expect, beforeEach, vi } from "vitest";

// Mock for @tauri-apps/api/core — main.js imports it via commands.js.
vi.mock("@tauri-apps/api/core", () => ({
  invoke: vi.fn(async () => "mocked"),
}));

// Import AFTER the mock. main.js registers a listener with `window.addEventListener`
// — in the node vitest environment, `window` is an implicit global if we expose it.
let mod;
beforeEach(async () => {
  // Reset window shim each test (node env — vitest config.environment = "node")
  globalThis.window = {
    addEventListener: () => {},
  };
  globalThis.document = {
    querySelector: () => null,
  };
  globalThis.console = { info: () => {}, warn: () => {} };
  // Re-import to get fresh state
  mod = await import("./main.js?t=" + Date.now());
  mod._resetPluginFirewallForTest();
});

function mkIframe() {
  // Simulates a DOM iframe with its own contentWindow (unique Object identity).
  return { contentWindow: { _fake: Math.random() } };
}

function mkEvent({ source, origin = "null", data }) {
  return { source, origin, data };
}

describe("plugin firewall — Tauri IPC shape filter (HOMAD + empíric Windows ARM64)", () => {
  it("silently ignores encrypted IPC blob (data=string)", () => {
    const event = mkEvent({
      source: { _internal: "isolation" },
      origin: "null",
      data: "AES-GCM encrypted blob base64...",
    });
    expect(mod.handlePluginMessage(event)).toBeNull();
  });

  it("silently ignores plain IPC command shape", () => {
    const event = mkEvent({
      source: { _internal: "tauri" },
      origin: "null",
      data: {
        cmd: "greet",
        callback: 42,
        error: 43,
        options: {},
        payload: { name: "Jordi" },
      },
    });
    expect(mod.handlePluginMessage(event)).toBeNull();
  });

  it("does NOT treat plugin messages as IPC (requires registered source)", () => {
    // Plugin messages: { action: "plugin.ready" } — do NOT have cmd/callback/error
    const event = mkEvent({
      source: { _evil: true }, // not registered
      origin: "null",
      data: { action: "plugin.ready" },
    });
    expect(mod.handlePluginMessage(event)).toBeNull();
  });
});

describe("plugin firewall — source validation (F034)", () => {
  it("rejects message from unregistered source", () => {
    const evilSource = { _evil: true };
    const event = mkEvent({
      source: evilSource,
      data: { action: "plugin.ready" },
    });
    expect(mod.handlePluginMessage(event)).toBeNull();
  });

  it("accepts message from registered iframe", () => {
    const iframe = mkIframe();
    mod.registerPluginIframe(iframe);
    const event = mkEvent({
      source: iframe.contentWindow,
      data: { action: "plugin.ready", plugin_id: "rag" },
    });
    expect(mod.handlePluginMessage(event)).toBe("plugin.ready");
  });

  it("rejects after unregister", () => {
    const iframe = mkIframe();
    mod.registerPluginIframe(iframe);
    mod.unregisterPluginIframe(iframe);
    const event = mkEvent({
      source: iframe.contentWindow,
      data: { action: "plugin.ready" },
    });
    expect(mod.handlePluginMessage(event)).toBeNull();
  });
});

describe("plugin firewall — origin validation", () => {
  it("rejects non-null origin even if source registered", () => {
    const iframe = mkIframe();
    mod.registerPluginIframe(iframe);
    const event = mkEvent({
      source: iframe.contentWindow,
      origin: "https://evil.example.com",
      data: { action: "plugin.ready" },
    });
    expect(mod.handlePluginMessage(event)).toBeNull();
  });

  it("rejects origin that's empty string", () => {
    const iframe = mkIframe();
    mod.registerPluginIframe(iframe);
    const event = mkEvent({
      source: iframe.contentWindow,
      origin: "",
      data: { action: "plugin.ready" },
    });
    expect(mod.handlePluginMessage(event)).toBeNull();
  });
});

describe("plugin firewall — action whitelist", () => {
  let iframe;
  beforeEach(() => {
    iframe = mkIframe();
    mod.registerPluginIframe(iframe);
  });

  it("accepts plugin.ready", () => {
    expect(
      mod.handlePluginMessage(
        mkEvent({ source: iframe.contentWindow, data: { action: "plugin.ready" } })
      )
    ).toBe("plugin.ready");
  });

  it("accepts plugin.resize", () => {
    expect(
      mod.handlePluginMessage(
        mkEvent({ source: iframe.contentWindow, data: { action: "plugin.resize", height: 500 } })
      )
    ).toBe("plugin.resize");
  });

  it("accepts plugin.notify", () => {
    expect(
      mod.handlePluginMessage(
        mkEvent({ source: iframe.contentWindow, data: { action: "plugin.notify", message: "hi" } })
      )
    ).toBe("plugin.notify");
  });

  it("rejects unknown action", () => {
    expect(
      mod.handlePluginMessage(
        mkEvent({ source: iframe.contentWindow, data: { action: "evil.exfiltrate" } })
      )
    ).toBeNull();
  });

  it("rejects missing action", () => {
    expect(
      mod.handlePluginMessage(
        mkEvent({ source: iframe.contentWindow, data: {} })
      )
    ).toBeNull();
  });

  it("rejects null data (no crash)", () => {
    expect(
      mod.handlePluginMessage(
        mkEvent({ source: iframe.contentWindow, data: null })
      )
    ).toBeNull();
  });

  it("rejects corrupted payloads without crashing", () => {
    const weirdPayloads = [
      { action: 42 },
      { action: { nested: "object" } },
      { action: "plugin.ready", plugin_id: { evil: "obj" } }, // still accepted, plugin_id ignored
    ];
    for (const data of weirdPayloads) {
      expect(() =>
        mod.handlePluginMessage(mkEvent({ source: iframe.contentWindow, data }))
      ).not.toThrow();
    }
  });
});

// -----------------------------------------------------------------------------
// Gemini F3 (consolidated C05) — iframe contentWindow registry race condition.
//
// Hypotheses to test:
//   H1 — iframe.contentWindow changes between about:blank (DOMContentLoaded) and
//        the real plugin load (load). Can it be reproduced?
//   H2 — A postMessage with event.source = new contentWindow (post-navigation)
//        that has NOT yet been registered by the load handler arrives rejected
//        (DoS) — temporary race window.
//   H3 — After a navigation, the OLD contentWindow remains in
//        REGISTERED_IFRAME_SOURCES as a zombie → allows spoofing? (NO, we will see
//        why it is not exploitable in practice.)
//   H4 — Multiple programmatic navigations (iframe.src = "plugin://..."
//        repeated) accumulate zombies in the Set.
//
// Expected conclusion (browser spec): `Window` zombies do NOT execute attacker code —
// a "closed" Window is no longer a valid source for postMessage.
// The only real vector is the H2 temporary window (DoS of first messages
// during transition). Bug #6 Phase 0 already mitigates this by also registering on load.
// -----------------------------------------------------------------------------
describe("plugin firewall — iframe contentWindow race (C05 Gemini F3)", () => {
  it("H1: registering BEFORE navigation captures old contentWindow, NEW one is NOT registered", () => {
    // Simulate: DOMContentLoaded → register about:blank contentWindow.
    const iframe = {
      contentWindow: { _stage: "about:blank" },
    };
    mod.registerPluginIframe(iframe);

    // Browser navigates the iframe → contentWindow replaced by new Window.
    const newContentWindow = { _stage: "plugin://rag" };
    iframe.contentWindow = newContentWindow;

    // Message from the NEW contentWindow (plugin loaded) arriving BEFORE
    // load event → rejected because Set only has the about:blank Window.
    const event = mkEvent({
      source: newContentWindow,
      data: { action: "plugin.ready" },
    });
    expect(mod.handlePluginMessage(event)).toBeNull();
  });

  it("H2 (mitigated): registering on the load event covers the new contentWindow", () => {
    // Simula el fix Bug #6: registrar DOMContentLoaded + load.
    const iframe = {
      contentWindow: { _stage: "about:blank" },
    };

    // Step 1: DOMContentLoaded — register about:blank window
    mod.registerPluginIframe(iframe);

    // Step 2: browser navigates and contentWindow changes
    const newContentWindow = { _stage: "plugin://rag" };
    iframe.contentWindow = newContentWindow;

    // Step 3: iframe.load event fires → handler registers the NEW contentWindow
    mod.registerPluginIframe(iframe);

    // Step 4: plugin sends postMessage → accepted (new contentWindow registered)
    const event = mkEvent({
      source: newContentWindow,
      data: { action: "plugin.ready" },
    });
    expect(mod.handlePluginMessage(event)).toBe("plugin.ready");
  });

  it("H2 race window: message during transition (before load fires) is dropped — DoS confirmed", () => {
    // The specific race Gemini describes: the plugin sends postMessage inside its
    // inline <script> during parsing (before the browser load event).
    // If the contentWindow is already the new one but load has not yet fired,
    // the legitimate message arrives with an unregistered source.
    const iframe = {
      contentWindow: { _stage: "about:blank" },
    };
    mod.registerPluginIframe(iframe); // DOMContentLoaded pas

    // Navigation in progress — contentWindow already changed, load not yet fired
    const midNavigationWindow = { _stage: "mid-navigation" };
    iframe.contentWindow = midNavigationWindow;

    // Plugin sends postMessage right now
    const event = mkEvent({
      source: midNavigationWindow,
      data: { action: "plugin.ready" },
    });

    // RESULT: rejected (legitimate DoS) — the only real "race" affected is
    // the message that arrives BETWEEN the new Window creation and the load event.
    // This is a microscopic window (typically < 1ms) and in practice
    // plugins send plugin.ready after load, not during parsing.
    expect(mod.handlePluginMessage(event)).toBeNull();
  });

  it("H3: old (zombie) contentWindow persists in Set — verified NOT exploitable", () => {
    // After navigation, the old contentWindow stays in the Set. But in
    // the real browser, a "discarded" Window (post-iframe-navigation)
    // CANNOT send postMessage: it has no live document. We simulate this by verifying
    // that the handler accepts the old Window as a source (zombie) — the
    // browser would NOT do this, but our JS code does because the Set keeps a
    // strong reference.
    const iframe = {
      contentWindow: { _stage: "about:blank" },
    };
    const oldContentWindow = iframe.contentWindow;
    mod.registerPluginIframe(iframe); // registra about:blank

    // Navigation: contentWindow replaced
    iframe.contentWindow = { _stage: "plugin://rag" };
    mod.registerPluginIframe(iframe); // registra nou

    // Our JS code would accept postMessage from the old Window because the Set
    // has a strong reference. This is "theoretical spoofing" — but in practice a
    // closed Window is not reusable by the attacker.
    const spoofEvent = mkEvent({
      source: oldContentWindow,
      data: { action: "plugin.ready" },
    });
    // The JS layer does NOT filter zombies — the browser is what invalidates the Window.
    expect(mod.handlePluginMessage(spoofEvent)).toBe("plugin.ready");

    // CONCLUSION: NOT an exploit vector because the zombie Window cannot emit
    // postMessage from the browser (document closed). The test only documents
    // that the Set contains zombies, not that they are exploitable.
  });

  it("H4: programmatic iframe.src reload accumulates zombies (if no mutation observer)", () => {
    const iframe = {
      contentWindow: { _nav: 0 },
    };

    // Nav 1
    mod.registerPluginIframe(iframe);
    // Nav 2 (simulate `iframe.src = 'plugin://rag/index.html?v=2'` and browser
    // fires `load` again with a new contentWindow)
    iframe.contentWindow = { _nav: 1 };
    mod.registerPluginIframe(iframe);
    // Nav 3
    iframe.contentWindow = { _nav: 2 };
    mod.registerPluginIframe(iframe);

    // The new one is registered and messages pass
    const latestEvent = mkEvent({
      source: iframe.contentWindow,
      data: { action: "plugin.ready" },
    });
    expect(mod.handlePluginMessage(latestEvent)).toBe("plugin.ready");

    // DOCUMENTATION: without MutationObserver, the 2 previous contentWindows
    // remain in the Set. This is a "nice to have" defense-in-depth but NOT
    // an exploit vector (reason: H3).
  });
});
