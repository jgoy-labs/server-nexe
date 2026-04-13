// CompletionView.swift — Pantalla final: API key + obrir Nexe + Dock + Login Items

import SwiftUI
import AppKit

struct CompletionView: View {
    @EnvironmentObject var engine: InstallerEngine
    @State private var copied = false
    @State private var addToDock = true
    @State private var addLoginItem = false
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

            // Temps total
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

            // Opcions post-instal·lació
            VStack(alignment: .leading, spacing: 8) {
                Toggle(isOn: $addToDock) {
                    HStack(spacing: 8) {
                        Image(systemName: "dock.rectangle")
                            .foregroundColor(.nexeRed)
                        Text(t("done_dock"))
                            .font(.subheadline)
                    }
                }
                .toggleStyle(.checkbox)

                Toggle(isOn: $addLoginItem) {
                    HStack(spacing: 8) {
                        Image(systemName: "power")
                            .foregroundColor(.nexeRed)
                        Text(t("done_login_item"))
                            .font(.subheadline)
                    }
                }
                .toggleStyle(.checkbox)
            }
            .padding(.horizontal, 60)

            // Missatge countdown (BUG #4: explicar que s'obre system tray)
            if isCountingDown {
                VStack(spacing: 4) {
                    Text(t("done_opening_tray"))
                        .font(.caption)
                        .foregroundColor(.secondary)
                    Text("\(countdown)")
                        .font(.system(size: 28, weight: .bold, design: .monospaced))
                        .foregroundColor(.nexeRed)
                }
                .padding(.top, 4)
            }

            Spacer()

            // Botons
            HStack(spacing: 16) {
                Button(t("btn_close")) {
                    isCountingDown = false  // cancel·la countdown pendent si n'hi ha
                    NSApp.setActivationPolicy(.prohibited)
                    NSApplication.shared.terminate(nil)
                }
                .controlSize(.large)

                Button(action: startCountdown) {
                    Text(
                        nexeOpened
                            ? t("btn_opened")
                            : isCountingDown
                                ? "\(countdown)s..."
                                : t("btn_open_nexe")
                    )
                    .frame(width: 200)
                }
                .controlSize(.large)
                .buttonStyle(.borderedProminent)
                .tint(.nexeRed)
                .disabled(nexeOpened || isCountingDown)
            }
            .padding(.bottom, 20)
        }
        .padding()
    }

    // MARK: - Accions

    private func copyKey() {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(engine.apiKey, forType: .string)
        copied = true
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) {
            copied = false
        }
    }

    private func startCountdown() {
        isCountingDown = true
        countdown = 10
        runCountdownStep()
    }

    private func runCountdownStep() {
        // Guard: si el countdown ha estat cancel·lat (Tancar o altre event), aturar
        guard isCountingDown else { return }
        if countdown <= 0 {
            isCountingDown = false
            openNexe()
            return
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 1) { [self] in
            // Re-check guard dins la closure (per si Tancar es va cridar entre steps)
            guard isCountingDown else { return }
            countdown -= 1
            runCountdownStep()
        }
    }

    private func openNexe() {
        nexeOpened = true

        let nexeAppPath = engine.installPath + "/Nexe.app"

        // Eliminar quarantena de Nexe.app (pot bloquejar el llançament)
        let xattr = Process()
        xattr.executableURL = URL(fileURLWithPath: "/usr/bin/xattr")
        xattr.arguments = ["-rd", "com.apple.quarantine", nexeAppPath]
        try? xattr.run()
        xattr.waitUntilExit()

        // Llançar tray amb --autostart (engega servidor i obre navegador).
        // Priority: NexeTray.app bundle (Gatekeeper-safe, correcte a macOS Sequoia).
        // Fallback: python -m installer.tray (entorn dev sense bundle present).
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
        // Passar idioma triat al tray
        tray.environment = env
        // Desacoblar stdout/stderr per evitar bloqueig de pipes i flash de focus
        tray.standardOutput = nil
        tray.standardError = nil
        // Nota: no cridar waitUntilExit — el tray és independent i no bloquejant
        try? tray.run()

        // B-dock / B-login: executar en background per no bloquejar el main thread.
        // El countdown ja ha garantit que la UI estava estable, el killall Dock
        // ara no causa el flash inicial (BUG #4).
        let snapAddToDock = addToDock
        let snapAddLoginItem = addLoginItem
        let snapNexeAppPath = nexeAppPath
        DispatchQueue.global(qos: .utility).async {
            if snapAddToDock { doAddToDock(nexeAppPath: snapNexeAppPath) }
            if snapAddLoginItem { doAddLoginItem(nexeAppPath: snapNexeAppPath) }
        }
    }

    private func doAddToDock(nexeAppPath: String) {
        let addDock = Process()
        addDock.executableURL = URL(fileURLWithPath: "/usr/bin/defaults")
        addDock.arguments = [
            "write", "com.apple.dock", "persistent-apps", "-array-add",
            "<dict><key>tile-data</key><dict><key>file-data</key><dict><key>_CFURLString</key><string>\(nexeAppPath)</string><key>_CFURLStringType</key><integer>0</integer></dict></dict></dict>"
        ]
        try? addDock.run()
        addDock.waitUntilExit()

        // Reiniciar Dock per aplicar els canvis al plist
        let killDock = Process()
        killDock.executableURL = URL(fileURLWithPath: "/usr/bin/killall")
        killDock.arguments = ["Dock"]
        try? killDock.run()
        killDock.waitUntilExit()
    }

    private func doAddLoginItem(nexeAppPath: String) {
        // Escapar cometes del path per evitar injection AppleScript
        let safePath = nexeAppPath.replacingOccurrences(of: "\"", with: "\\\"")
        let script = """
        tell application "System Events" to make login item at end \
        with properties {path:"\(safePath)", hidden:true}
        """
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
        process.arguments = ["-e", script]
        try? process.run()
        process.waitUntilExit()
    }

    private func t(_ key: String) -> String {
        T.get(key, lang: engine.lang)
    }
}
