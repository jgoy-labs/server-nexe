// nexe_launcher.swift — Launcher natiu de Nexe.app (substitueix bash script)
//
// Per què un binari Swift en lloc de bash:
// - Apareix correctament a "Força la sortida" (NSApplication registrada)
// - Click al Dock NO relaunxa l'app (applicationShouldHandleReopen gestionat)
// - Triangle "app activa" estable (no flashing)
// - Cmd+Q del Dock funciona i tanca tray net
//
// Comportament:
// 1. Si ja hi ha servidor a :9119 → obrir UI i sortir (cas: tray orfe viu)
// 2. Si no → llançar Python tray --autostart + quedar-se viu esperant
// 3. Click posterior al Dock → applicationShouldHandleReopen → obrir UI (tab)
// 4. Cmd+Q → terminar tray i netejar
//
// Build:
//   swiftc -O -o NexeTray nexe_launcher.swift
//   (fet automàticament per installer/build_dmg.sh)

import Cocoa

// MARK: - Helpers de paths

func resolveProjectRoot() -> String? {
    // Nexe.app/Contents/MacOS/NexeTray → project root = parent de Nexe.app
    let execPath = Bundle.main.executablePath ?? ""
    let appDir = (execPath as NSString).deletingLastPathComponent  // MacOS/
    let contentsDir = (appDir as NSString).deletingLastPathComponent  // Contents/
    let bundleDir = (contentsDir as NSString).deletingLastPathComponent  // Nexe.app
    let candidate1 = (bundleDir as NSString).deletingLastPathComponent  // parent

    // Cas dev: Nexe.app dins el projecte
    if FileManager.default.isExecutableFile(atPath: candidate1 + "/venv/bin/python") {
        return candidate1
    }

    // Cas producció: llegir marker project_root.txt dins Resources/
    let markerPath = bundleDir + "/Contents/Resources/project_root.txt"
    if let content = try? String(contentsOfFile: markerPath, encoding: .utf8) {
        let path = content.trimmingCharacters(in: .whitespacesAndNewlines)
        if FileManager.default.isExecutableFile(atPath: path + "/venv/bin/python") {
            return path
        }
    }
    return nil
}

func isServerListening(port: Int) -> Bool {
    let task = Process()
    task.executableURL = URL(fileURLWithPath: "/usr/sbin/lsof")
    task.arguments = ["-nP", "-iTCP:\(port)", "-sTCP:LISTEN"]
    task.standardOutput = nil
    task.standardError = nil
    try? task.run()
    task.waitUntilExit()
    return task.terminationStatus == 0
}

func openWebUI() {
    let task = Process()
    task.executableURL = URL(fileURLWithPath: "/usr/bin/open")
    task.arguments = ["http://127.0.0.1:9119/ui"]
    try? task.run()
}

func showMissingVenvDialog() {
    let alert = NSAlert()
    alert.messageText = "Nexe"
    alert.informativeText = "Python venv not found.\nRun the installer first."
    alert.alertStyle = .critical
    alert.addButton(withTitle: "OK")
    alert.runModal()
}

// MARK: - AppDelegate

class AppDelegate: NSObject, NSApplicationDelegate {
    var trayProcess: Process?

    func applicationDidFinishLaunching(_ notification: Notification) {
        // Si ja hi ha servidor escoltant (tray orfe d'una sessió anterior),
        // obrir UI i sortir — no duplicar tray.
        if isServerListening(port: 9119) {
            openWebUI()
            NSApp.terminate(nil)
            return
        }

        // Resoldre project root
        guard let projectRoot = resolveProjectRoot() else {
            showMissingVenvDialog()
            NSApp.terminate(nil)
            return
        }

        // Matar processos nexe-tray/installer.tray orfes (no escolten port)
        let killTask = Process()
        killTask.executableURL = URL(fileURLWithPath: "/usr/bin/pkill")
        killTask.arguments = ["-f", "nexe-tray|installer.tray"]
        killTask.standardOutput = nil
        killTask.standardError = nil
        try? killTask.run()
        killTask.waitUntilExit()
        Thread.sleep(forTimeInterval: 0.3)

        // Llançar tray Python --autostart
        let python = projectRoot + "/venv/bin/python"
        let tray = Process()
        tray.executableURL = URL(fileURLWithPath: python)
        tray.arguments = ["-m", "installer.tray", "--autostart"]
        tray.currentDirectoryURL = URL(fileURLWithPath: projectRoot)
        tray.standardOutput = nil
        tray.standardError = nil
        do {
            try tray.run()
            self.trayProcess = tray

            // Observer: si el tray mor, terminar la launcher també
            tray.terminationHandler = { _ in
                DispatchQueue.main.async {
                    NSApp.terminate(nil)
                }
            }
        } catch {
            showMissingVenvDialog()
            NSApp.terminate(nil)
        }
    }

    // Click al Dock quan l'app ja corre → NO-OP (no obrir tabs).
    // Motiu: si el servidor ja corre, l'usuari pot tenir la UI oberta en un tab;
    // obrir un tab nou a cada click genera spam. L'usuari accedeix a la UI via
    // el menubar icon (menu "Obrir UI"). Retornar true per evitar que macOS
    // relancxi res — nosaltres ja ho hem gestionat (ignorant).
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        return true
    }

    // Cmd+Q / Force Quit / "Quit" del menú → tancar el tray Python també
    func applicationWillTerminate(_ notification: Notification) {
        if let tray = trayProcess, tray.isRunning {
            tray.terminate()
            // Donar 2s perquè el tray es tanqui net abans de matar dur
            let deadline = Date().addingTimeInterval(2.0)
            while tray.isRunning && Date() < deadline {
                Thread.sleep(forTimeInterval: 0.1)
            }
            if tray.isRunning {
                kill(tray.processIdentifier, SIGKILL)
            }
        }
    }

    // No tancar l'app quan l'última finestra es tanca (no tenim finestres propies)
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        return false
    }
}

// MARK: - Main

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)  // Dock presence (NO LSUIElement — és el launcher visible)
app.run()
