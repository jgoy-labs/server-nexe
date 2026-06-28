// CompletionView.swift — Final screen: API key + open Nexe + Dock + Login Items

import SwiftUI
import AppKit

struct CompletionView: View {
    @EnvironmentObject var engine: InstallerEngine
    @State private var copied = false
    @State private var nexeOpened = false
    @State private var countdown: Int = 0
    @State private var isCountingDown: Bool = false

    var body: some View {
        VStack(spacing: 16) {
            Spacer()

            Image(systemName: "checkmark.seal.fill")
                .resizable()
                .aspectRatio(contentMode: .fit)
                .frame(width: 50, height: 50)
                .foregroundStyle(.linearGradient(
                    colors: [.green, .mint],
                    startPoint: .topLeading,
                    endPoint: .bottomTrailing
                ))

            Text(t("done_title"))
                .font(.system(size: 24, weight: .bold))

            // Total time
            if !engine.totalTime.isEmpty {
                Text(engine.totalTime)
                    .font(.caption)
                    .foregroundColor(.secondary)
            }

            Text(t("done_desc"))
                .font(.subheadline)
                .foregroundColor(.secondary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 480)

            // Warning if model download failed
            if engine.installPartial {
                HStack(spacing: 8) {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .foregroundColor(.orange)
                    Text(t("done_partial_warning"))
                        .font(.caption)
                        .foregroundColor(.orange)
                }
                .padding(10)
                .background(Color.orange.opacity(0.1))
                .cornerRadius(8)
                .padding(.horizontal, 24)
            }

            // API Key
            if !engine.apiKey.isEmpty {
                VStack(spacing: 4) {
                    Text(t("done_api_key"))
                        .font(.caption)
                        .foregroundColor(.secondary)

                    HStack {
                        Text(engine.apiKey)
                            .font(.system(size: 13, design: .monospaced))
                            .textSelection(.enabled)
                            .padding(8)
                            .background(Color(nsColor: .textBackgroundColor))
                            .cornerRadius(8)

                        Button(action: copyKey) {
                            Image(systemName: copied ? "checkmark" : "doc.on.doc")
                                .frame(width: 32, height: 32)
                        }
                        .buttonStyle(.bordered)
                    }
                }
                .padding(.horizontal, 40)
            }

            // Info menu bar
            HStack(alignment: .top, spacing: 8) {
                Image(systemName: "menubar.arrow.up.rectangle")
                    .foregroundColor(.nexeRed)
                Text(t("done_menubar_info"))
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
            .padding(.horizontal, 50)

            Spacer()

            // Buttons
            HStack(spacing: 16) {
                Button(t("btn_close")) {
                    isCountingDown = false
                    NSApp.setActivationPolicy(.prohibited)
                    NSApplication.shared.terminate(nil)
                }
                .controlSize(.large)

                Button(action: launchAndCountdown) {
                    Text(
                        nexeOpened
                            ? (isCountingDown
                                ? "\(t("btn_starting"))  \(countdown)"
                                : t("btn_opened"))
                            : t("btn_open_nexe")
                    )
                    .frame(width: 220)
                }
                .nexePrimaryButton()
                .disabled(nexeOpened)
            }
            .padding(.bottom, 20)
        }
        .padding()
        .onAppear { applyDockIcon() }
    }

    // MARK: - Actions

    private func applyDockIcon() {
        // Bug #19d fix (v1.0): Nexe.app lives ONLY at <install_dir>/Nexe.app.
        // It used to copy a second instance to /Applications/Nexe.app
        // that ended up an orphan without the Python code alongside it.
        guard engine.addToDock else { return }
        let nexeAppPath = engine.installPath + "/Nexe.app"
        DispatchQueue.global(qos: .utility).async {
            doAddToDock(nexeAppPath: nexeAppPath)
        }
    }

    private func copyKey() {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(engine.apiKey, forType: .string)
        copied = true
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) {
            copied = false
        }
    }

    /// Click "Open Nexe": launches the server IMMEDIATELY and starts the
    /// countdown in parallel (visual only — when it reaches 0 it does nothing extra,
    /// it just hides the number; the server has already been starting for X seconds).
    private func launchAndCountdown() {
        openNexe()
        isCountingDown = true
        countdown = 10
        runCountdownStep()
    }

    private func runCountdownStep() {
        guard isCountingDown else { return }
        if countdown <= 0 {
            isCountingDown = false
            return  // visual only — the server has been running for 10s already
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 1) { [self] in
            guard isCountingDown else { return }
            countdown -= 1
            runCountdownStep()
        }
    }

    private func openNexe() {
        nexeOpened = true

        // Launch via <install_dir>/Nexe.app (the same bundle that's in the Dock).
        // This way macOS registers that the app is running and the triangle appears under
        // the Dock icon. Nexe.app's bash launcher handles port-check + tray spawn.
        let dockAppPath = engine.installPath + "/Nexe.app"

        // Remove quarantine to avoid a Gatekeeper block
        let xattr = Process()
        xattr.executableURL = URL(fileURLWithPath: "/usr/bin/xattr")
        xattr.arguments = ["-rd", "com.apple.quarantine", dockAppPath]
        try? xattr.run()
        xattr.waitUntilExit()

        if FileManager.default.fileExists(atPath: dockAppPath) {
            // Via `open -a`: macOS treats the bundle as its own app, applies
            // LSUIElement=false (dock presence), attaches the triangle under the Dock
            // icon, and avoids double instances if it's already running.
            let open = Process()
            open.executableURL = URL(fileURLWithPath: "/usr/bin/open")
            open.arguments = ["-a", dockAppPath]
            var env = ProcessInfo.processInfo.environment
            env["NEXE_LANG"] = engine.lang.rawValue
            open.environment = env
            open.standardOutput = nil
            open.standardError = nil
            try? open.run()
            return
        }

        // Fallback: dev environment or /Applications/Nexe.app missing → launch tray directly
        let trayBundlePath = engine.installPath + "/installer/NexeTray.app/Contents/MacOS/NexeTray"
        let tray = Process()
        var env = ProcessInfo.processInfo.environment
        env["NEXE_LANG"] = engine.lang.rawValue
        if FileManager.default.fileExists(atPath: trayBundlePath) {
            tray.executableURL = URL(fileURLWithPath: trayBundlePath)
            tray.arguments = ["--autostart"]
        } else {
            let venvPython = engine.installPath + "/venv/bin/python3"
            tray.executableURL = URL(fileURLWithPath: venvPython)
            tray.arguments = ["-m", "installer.tray", "--autostart"]
        }
        tray.currentDirectoryURL = URL(fileURLWithPath: engine.installPath)
        tray.environment = env
        tray.standardOutput = nil
        tray.standardError = nil
        try? tray.run()
    }

    private func doAddToDock(nexeAppPath: String) {
        // Verify Nexe.app exists before adding it to the Dock
        guard FileManager.default.fileExists(atPath: nexeAppPath) else { return }

        // Idempotent: if there's already an entry pointing to nexeAppPath, don't add.
        // Avoids duplicates across successive reinstalls.
        if dockHasEntry(for: nexeAppPath) { return }

        let entry = "<dict><key>tile-data</key><dict><key>file-data</key><dict>" +
            "<key>_CFURLString</key><string>\(nexeAppPath)</string>" +
            "<key>_CFURLStringType</key><integer>0</integer>" +
            "</dict></dict><key>tile-type</key><string>file-tile</string></dict>"

        let addDock = Process()
        addDock.executableURL = URL(fileURLWithPath: "/usr/bin/defaults")
        addDock.arguments = ["write", "com.apple.dock", "persistent-apps", "-array-add", entry]
        try? addDock.run()
        addDock.waitUntilExit()

        // Restart the Dock to apply the plist changes
        let killDock = Process()
        killDock.executableURL = URL(fileURLWithPath: "/usr/bin/killall")
        killDock.arguments = ["Dock"]
        try? killDock.run()
        killDock.waitUntilExit()
    }

    /// Returns true if the Dock already has a persistent-apps entry pointing to appPath.
    /// Check via `defaults read`: we look for the path (with and without the file:// prefix).
    private func dockHasEntry(for appPath: String) -> Bool {
        let read = Process()
        read.executableURL = URL(fileURLWithPath: "/usr/bin/defaults")
        read.arguments = ["read", "com.apple.dock", "persistent-apps"]
        let pipe = Pipe()
        read.standardOutput = pipe
        read.standardError = nil
        try? read.run()
        read.waitUntilExit()
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        guard let output = String(data: data, encoding: .utf8) else { return false }
        // `defaults read` serializes as `file:///Applications/Nexe.app/` or a raw path
        return output.contains("file://\(appPath)") || output.contains("\"\(appPath)\"")
    }

    private func t(_ key: String) -> String {
        T.get(key, lang: engine.lang)
    }
}
