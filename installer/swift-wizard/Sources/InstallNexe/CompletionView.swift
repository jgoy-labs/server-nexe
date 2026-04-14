// CompletionView.swift — Pantalla final: API key + obrir Nexe + Dock + Login Items

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

            // Countdown standalone — número gran, sense caption duplicat
            // (done_menubar_info dalt ja explica que apareix tray a la dreta)
            if isCountingDown {
                Text("\(countdown)")
                    .font(.system(size: 32, weight: .bold, design: .monospaced))
                    .foregroundColor(.nexeRed)
                    .padding(.top, 4)
            }

            Spacer()

            // Botons
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
                            ? (isCountingDown ? t("btn_starting") : t("btn_opened"))
                            : t("btn_open_nexe")
                    )
                    .frame(width: 200)
                }
                .nexePrimaryButton()
                .disabled(nexeOpened)
            }
            .padding(.bottom, 20)
        }
        .padding()
        .onAppear { applyDockIcon() }
    }

    // MARK: - Accions

    private func applyDockIcon() {
        // Nexe.app es copia a /Applications/Nexe.app per install_headless.py.
        // És un .app normal (LSUIElement=false) amb icona pròpia i executable
        // NexeTray: el target correcte pel Dock.
        guard engine.addToDock else { return }
        let nexeAppPath = "/Applications/Nexe.app"
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

    /// Click "Obrir Nexe": llança el servidor IMMEDIATAMENT i inicia el
    /// countdown en paral·lel (visual only — quan arriba a 0 no fa res extra,
    /// simplement oculta el número, el servidor ja porta X segons arrencant).
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
            return  // visual only — el servidor ja corre de fa 10s
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 1) { [self] in
            guard isCountingDown else { return }
            countdown -= 1
            runCountdownStep()
        }
    }

    private func openNexe() {
        nexeOpened = true

        // Llançament via /Applications/Nexe.app (el mateix bundle que hi ha al Dock).
        // Així macOS registra que l'app està corrent i apareix el triangle sota la
        // icona del Dock (abans es llançava NexeTray.app — bundle diferent, sense
        // triangle). El bash launcher de Nexe.app gestiona port-check + tray spawn.
        let dockAppPath = "/Applications/Nexe.app"

        // Eliminar quarantena per evitar bloqueig Gatekeeper
        let xattr = Process()
        xattr.executableURL = URL(fileURLWithPath: "/usr/bin/xattr")
        xattr.arguments = ["-rd", "com.apple.quarantine", dockAppPath]
        try? xattr.run()
        xattr.waitUntilExit()

        if FileManager.default.fileExists(atPath: dockAppPath) {
            // Via `open -a`: macOS tracta el bundle com a app pròpia, aplica
            // LSUIElement=false (dock presence), enganxa el triangle sota la icona
            // del Dock, i evita dobles instàncies si ja corre.
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

        // Fallback: entorn dev o /Applications/Nexe.app missing → llançar tray directe
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
        // Verificar que Nexe.app existeix abans d'afegir al Dock
        guard FileManager.default.fileExists(atPath: nexeAppPath) else { return }

        // Idempotent: si ja hi ha una entrada que apunta a nexeAppPath, no afegir.
        // Evita duplicats en reinstal·lacions successives.
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

        // Reiniciar Dock per aplicar els canvis al plist
        let killDock = Process()
        killDock.executableURL = URL(fileURLWithPath: "/usr/bin/killall")
        killDock.arguments = ["Dock"]
        try? killDock.run()
        killDock.waitUntilExit()
    }

    /// Retorna true si el Dock ja té una entrada persistent-apps apuntant a appPath.
    /// Check via `defaults read`: busquem el path (amb i sense prefix file://).
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
        // `defaults read` serialitza com `file:///Applications/Nexe.app/` o path cru
        return output.contains("file://\(appPath)") || output.contains("\"\(appPath)\"")
    }

    private func t(_ key: String) -> String {
        T.get(key, lang: engine.lang)
    }
}
