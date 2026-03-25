// CompletionView.swift — Pantalla final: API key + obrir Nexe + Dock + Login Items

import SwiftUI
import AppKit

struct CompletionView: View {
    @EnvironmentObject var engine: InstallerEngine
    @State private var copied = false
    @State private var addToDock = true
    @State private var addLoginItem = false
    @State private var nexeOpened = false
    @State private var countdown = 0

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

            Spacer()

            // Botons
            HStack(spacing: 16) {
                Button(t("btn_close")) {
                    NSApplication.shared.terminate(nil)
                }
                .controlSize(.large)

                Button(action: openNexe) {
                    if countdown > 0 {
                        Text("\(t("btn_open_nexe")) (\(countdown)s)")
                            .frame(width: 200)
                    } else {
                        Text(nexeOpened ? t("btn_opened") : t("btn_open_nexe"))
                            .frame(width: 200)
                    }
                }
                .controlSize(.large)
                .buttonStyle(.borderedProminent)
                .tint(.nexeRed)
                .disabled(nexeOpened)
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

    private func openNexe() {
        nexeOpened = true
        countdown = 10
        // Compte enrere visual
        Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { timer in
            countdown -= 1
            if countdown <= 0 { timer.invalidate() }
        }

        // Aplicar opcions
        if addToDock { doAddToDock() }
        if addLoginItem { doAddLoginItem() }

        // Eliminar quarantena de Nexe.app (pot bloquejar el llançament)
        let xattr = Process()
        xattr.executableURL = URL(fileURLWithPath: "/usr/bin/xattr")
        xattr.arguments = ["-rd", "com.apple.quarantine", "/Applications/Nexe.app"]
        try? xattr.run()
        xattr.waitUntilExit()

        // Llançar tray amb --autostart (engega servidor i obre navegador)
        let venvPython = engine.installPath + "/venv/bin/python3"
        let tray = Process()
        tray.executableURL = URL(fileURLWithPath: venvPython)
        tray.arguments = ["-m", "installer.tray", "--autostart"]
        tray.currentDirectoryURL = URL(fileURLWithPath: engine.installPath)
        // Passar idioma triat al tray
        var env = ProcessInfo.processInfo.environment
        env["NEXE_LANG"] = engine.lang.rawValue
        tray.environment = env
        try? tray.run()
    }

    private func doAddToDock() {
        let addDock = Process()
        addDock.executableURL = URL(fileURLWithPath: "/usr/bin/defaults")
        addDock.arguments = [
            "write", "com.apple.dock", "persistent-apps", "-array-add",
            "<dict><key>tile-data</key><dict><key>file-data</key><dict><key>_CFURLString</key><string>/Applications/Nexe.app</string><key>_CFURLStringType</key><integer>0</integer></dict></dict></dict>"
        ]
        try? addDock.run()
        addDock.waitUntilExit()

        // Reiniciar Dock per aplicar
        let killDock = Process()
        killDock.executableURL = URL(fileURLWithPath: "/usr/bin/killall")
        killDock.arguments = ["Dock"]
        try? killDock.run()
    }

    private func doAddLoginItem() {
        let script = """
        tell application "System Events" to make login item at end \
        with properties {path:"/Applications/Nexe.app", hidden:true}
        """
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
        process.arguments = ["-e", script]
        try? process.run()
    }

    private func t(_ key: String) -> String {
        T.get(key, lang: engine.lang)
    }
}
