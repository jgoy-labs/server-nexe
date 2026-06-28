// nexe_launcher.swift — Native launcher for Nexe.app (replaces the bash script)
//
// Why a Swift binary instead of bash:
// - Shows up correctly in "Force Quit" (NSApplication registered)
// - Clicking the Dock does NOT relaunch the app (applicationShouldHandleReopen handled)
// - Stable "app active" triangle (no flashing)
// - Cmd+Q from the Dock works and shuts the tray down cleanly
//
// Behavior:
// 1. If a server is already on :9119 → open UI and exit (case: orphaned tray alive)
// 2. Otherwise → launch the Python tray --autostart + stay alive waiting
// 3. Later click on the Dock → applicationShouldHandleReopen → open UI (tab)
// 4. Cmd+Q → terminate the tray and clean up
//
// Build:
//   swiftc -O -o NexeTray nexe_launcher.swift
//   (done automatically by installer/build_dmg.sh)

import Cocoa
import Darwin

// MARK: - Path helpers

func resolveProjectRoot() -> String? {
    let fm = FileManager.default
    let execPath = Bundle.main.executablePath ?? ""
    let appDir = (execPath as NSString).deletingLastPathComponent       // MacOS/
    let contentsDir = (appDir as NSString).deletingLastPathComponent    // Contents/
    let bundleDir = (contentsDir as NSString).deletingLastPathComponent // Nexe.app
    let parentDir = (bundleDir as NSString).deletingLastPathComponent   // parent

    // 1) Dev case: Nexe.app inside the project (parent contains venv/)
    if fm.isExecutableFile(atPath: parentDir + "/venv/bin/python") {
        return parentDir
    }

    // 2) Production case: marker OUTSIDE the bundle, at ~/Library/Application Support/Nexe/
    //    Outside the bundle because if it were inside Resources/ it would break the
    //    codesign seal and Gatekeeper would refuse to launch.
    let home = NSHomeDirectory()
    let extMarker = home + "/Library/Application Support/Nexe/project_root.txt"
    if let content = try? String(contentsOfFile: extMarker, encoding: .utf8) {
        let path = content.trimmingCharacters(in: .whitespacesAndNewlines)
        if fm.isExecutableFile(atPath: path + "/venv/bin/python") {
            return path
        }
    }

    // 3) Legacy fallback: marker inside Resources/ (installs prior to the fix).
    //    This path breaks the signature — if we find it, we move it to the
    //    new location to recover the signature.
    let legacyMarker = bundleDir + "/Contents/Resources/project_root.txt"
    if let content = try? String(contentsOfFile: legacyMarker, encoding: .utf8) {
        let path = content.trimmingCharacters(in: .whitespacesAndNewlines)
        if fm.isExecutableFile(atPath: path + "/venv/bin/python") {
            // Silently migrate to the correct location
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

// MARK: - Lock file anti-race (double-click on the Dock)

/// Path of the launcher lock file. Outside the bundle so it doesn't break codesign.
func launcherLockPath() -> String {
    let home = NSHomeDirectory()
    return home + "/Library/Application Support/Nexe/launcher.pid"
}

/// Returns true if the given PID is alive (kill(pid, 0) == 0).
func isPidAlive(_ pid: pid_t) -> Bool {
    if pid <= 0 { return false }
    // kill with signal 0 sends nothing — it only checks existence + permissions.
    let res = kill(pid, 0)
    if res == 0 { return true }
    // ESRCH = does not exist; EPERM = exists but we lack permissions (alive)
    return errno == EPERM
}

/// Returns true if a launcher is already alive (case: fast double-click on the Dock).
/// Otherwise, writes our PID to the lock and returns false (path clear).
func acquireLauncherLock() -> Bool {
    let lockPath = launcherLockPath()
    let fm = FileManager.default
    let dir = (lockPath as NSString).deletingLastPathComponent
    try? fm.createDirectory(atPath: dir, withIntermediateDirectories: true)

    if let content = try? String(contentsOfFile: lockPath, encoding: .utf8) {
        let trimmed = content.trimmingCharacters(in: .whitespacesAndNewlines)
        if let pid = Int32(trimmed), isPidAlive(pid), pid != getpid() {
            // A launcher is already alive — abort silently.
            return false
        }
    }
    // Write our PID (overwrites an orphaned lock)
    let myPid = String(getpid())
    try? myPid.write(toFile: lockPath, atomically: true, encoding: .utf8)
    return true
}

/// Removes the lock file if it is still ours.
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
        // Lock file against double-click race: if a launcher is already alive,
        // exit silently (the first one is already doing the work).
        if !acquireLauncherLock() {
            NSApp.terminate(nil)
            return
        }

        // If a server is already listening (orphaned tray from a previous session),
        // open UI and exit — don't duplicate the tray.
        if isServerListening(port: 9119) {
            openWebUI()
            NSApp.terminate(nil)
            return
        }

        // Resolve project root
        guard let projectRoot = resolveProjectRoot() else {
            showMissingVenvDialog()
            NSApp.terminate(nil)
            return
        }

        // B211: Kill ONLY the nexe-tray/installer.tray processes of the current
        // projectRoot; a generic pkill -f kills trays of other installations in parallel.
        // Strategy: pgrep -f <pattern> to get PIDs, filter by CWD matching
        // projectRoot (via lsof -p or /proc/PID/cwd), and kill them one by one.
        // Safe simplification: restrict the pattern to the specific venv executable.
        let trayExecutable = projectRoot + "/venv/bin/python"
        let killTask = Process()
        killTask.executableURL = URL(fileURLWithPath: "/usr/bin/pkill")
        // Kill processes that use exactly the python of this projectRoot
        killTask.arguments = ["-f", trayExecutable + ".*installer.tray|" + trayExecutable + ".*nexe-tray"]
        killTask.standardOutput = nil
        killTask.standardError = nil
        try? killTask.run()
        killTask.waitUntilExit()
        Thread.sleep(forTimeInterval: 0.3)

        // Launch the Python tray --autostart
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

            // Observer: if the tray dies, terminate the launcher as well
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

    // Click on the Dock when the app is already running → NO-OP (don't open tabs).
    // Reason: if the server is already running, the user may have the UI open in a tab;
    // opening a new tab on each click generates spam. The user accesses the UI via
    // the menubar icon (the "Open UI" menu). Return true to prevent macOS from
    // relaunching anything — we have already handled it (by ignoring it).
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        return true
    }

    // Cmd+Q / Force Quit / "Quit" from the menu → close the Python tray as well
    func applicationWillTerminate(_ notification: Notification) {
        if let tray = trayProcess, tray.isRunning {
            // SIGTERM first; give it 8s so uvicorn can do a graceful shutdown
            // (internal graceful timeout ~30s, 8s is a reasonable compromise).
            tray.terminate()
            let deadline = Date().addingTimeInterval(8.0)
            while tray.isRunning && Date() < deadline {
                Thread.sleep(forTimeInterval: 0.1)
            }
            if tray.isRunning {
                kill(tray.processIdentifier, SIGKILL)
            }
        }
        // Release the launcher lock file
        releaseLauncherLock()
    }

    // Don't quit the app when the last window closes (we have no windows of our own)
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        return false
    }
}

// MARK: - Main

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)  // Dock presence (NO LSUIElement — this is the visible launcher)
app.run()
