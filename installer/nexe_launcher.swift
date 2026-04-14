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
import Darwin

// MARK: - Helpers de paths

func resolveProjectRoot() -> String? {
    let fm = FileManager.default
    let execPath = Bundle.main.executablePath ?? ""
    let appDir = (execPath as NSString).deletingLastPathComponent       // MacOS/
    let contentsDir = (appDir as NSString).deletingLastPathComponent    // Contents/
    let bundleDir = (contentsDir as NSString).deletingLastPathComponent // Nexe.app
    let parentDir = (bundleDir as NSString).deletingLastPathComponent   // parent

    // 1) Cas dev: Nexe.app dins el projecte (parent conté venv/)
    if fm.isExecutableFile(atPath: parentDir + "/venv/bin/python") {
        return parentDir
    }

    // 2) Cas producció: marker FORA del bundle, a ~/Library/Application Support/Nexe/
    //    Fora del bundle perquè si fos dins Resources/ trencaria el seal
    //    de codesign i Gatekeeper refusaria el llançament.
    let home = NSHomeDirectory()
    let extMarker = home + "/Library/Application Support/Nexe/project_root.txt"
    if let content = try? String(contentsOfFile: extMarker, encoding: .utf8) {
        let path = content.trimmingCharacters(in: .whitespacesAndNewlines)
        if fm.isExecutableFile(atPath: path + "/venv/bin/python") {
            return path
        }
    }

    // 3) Fallback legacy: marker dins Resources/ (installs anteriors al fix).
    //    Aquest path trenca la signatura — si el trobem, el moure'm a la
    //    ubicació nova per recuperar la signatura.
    let legacyMarker = bundleDir + "/Contents/Resources/project_root.txt"
    if let content = try? String(contentsOfFile: legacyMarker, encoding: .utf8) {
        let path = content.trimmingCharacters(in: .whitespacesAndNewlines)
        if fm.isExecutableFile(atPath: path + "/venv/bin/python") {
            // Migrar silenciosament a la ubicació bona
            let newDir = home + "/Library/Application Support/Nexe"
            try? fm.createDirectory(atPath: newDir, withIntermediateDirectories: true)
            try? content.write(toFile: newDir + "/project_root.txt", atomically: true, encoding: .utf8)
            try? fm.removeItem(atPath: legacyMarker)
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

// MARK: - Lock file anti-race (doble-click al Dock)

/// Path del lock file del launcher. Fora del bundle per no trencar codesign.
func launcherLockPath() -> String {
    let home = NSHomeDirectory()
    return home + "/Library/Application Support/Nexe/launcher.pid"
}

/// Retorna true si el PID donat està viu (kill(pid, 0) == 0).
func isPidAlive(_ pid: pid_t) -> Bool {
    if pid <= 0 { return false }
    // kill amb signal 0 no envia res — només comprova existència + permisos.
    let res = kill(pid, 0)
    if res == 0 { return true }
    // ESRCH = no existeix; EPERM = existeix però no tenim permisos (viu)
    return errno == EPERM
}

/// Retorna true si ja hi ha un launcher viu (cas: doble-click ràpid al Dock).
/// Si no, escriu el nostre PID al lock i retorna false (via lliure).
func acquireLauncherLock() -> Bool {
    let lockPath = launcherLockPath()
    let fm = FileManager.default
    let dir = (lockPath as NSString).deletingLastPathComponent
    try? fm.createDirectory(atPath: dir, withIntermediateDirectories: true)

    if let content = try? String(contentsOfFile: lockPath, encoding: .utf8) {
        let trimmed = content.trimmingCharacters(in: .whitespacesAndNewlines)
        if let pid = Int32(trimmed), isPidAlive(pid), pid != getpid() {
            // Ja hi ha un launcher viu — avortar silenciosament.
            return false
        }
    }
    // Escriure el nostre PID (sobrescriu lock orfe)
    let myPid = String(getpid())
    try? myPid.write(toFile: lockPath, atomically: true, encoding: .utf8)
    return true
}

/// Esborra el lock file si encara és el nostre.
func releaseLauncherLock() {
    let lockPath = launcherLockPath()
    if let content = try? String(contentsOfFile: lockPath, encoding: .utf8) {
        let trimmed = content.trimmingCharacters(in: .whitespacesAndNewlines)
        if Int32(trimmed) == getpid() {
            try? FileManager.default.removeItem(atPath: lockPath)
        }
    }
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
        // Lock file contra race de doble-click: si ja hi ha un launcher viu,
        // sortir silenciosament (el primer ja està fent la feina).
        if !acquireLauncherLock() {
            NSApp.terminate(nil)
            return
        }

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
            // SIGTERM primer; donar 8s perquè uvicorn faci graceful shutdown
            // (graceful timeout intern ~30s, 8s és un compromís raonable).
            tray.terminate()
            let deadline = Date().addingTimeInterval(8.0)
            while tray.isRunning && Date() < deadline {
                Thread.sleep(forTimeInterval: 0.1)
            }
            if tray.isRunning {
                kill(tray.processIdentifier, SIGKILL)
            }
        }
        // Alliberar lock file del launcher
        releaseLauncherLock()
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
