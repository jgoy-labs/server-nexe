// InstallerEngine.swift — Core logic: unpack payload, call Python, parse progress

import Foundation
import SwiftUI

enum StepStatus: String {
    case pending, running, done, error
}

struct InstallStep: Identifiable {
    let id: Int
    let key: String
    var status: StepStatus = .pending
    var message: String = ""
    var startTime: Date?
    var endTime: Date?

    var elapsed: String? {
        guard let start = startTime else { return nil }
        let end = endTime ?? Date()
        let secs = Int(end.timeIntervalSince(start))
        if secs < 60 { return "\(secs)s" }
        return "\(secs / 60)m \(secs % 60)s"
    }
}

@MainActor
class InstallerEngine: ObservableObject {
    // Configuration chosen by the user
    @Published var lang: Lang = .fromSystem()
    @Published var darkMode: Bool = {
        let hour = Calendar.current.component(.hour, from: Date())
        return hour < 7 || hour >= 20  // dark from 8pm to 7am
    }()
    @Published var installPath: String = "/Applications/server-nexe"
    @Published var selectedModel: AIModel?
    @Published var selectedEngine: String = "auto"
    @Published var addToDock: Bool = true

    // Installation state
    @Published var steps: [InstallStep] = [
        InstallStep(id: 1, key: "progress_step_venv"),
        InstallStep(id: 2, key: "progress_step_deps"),
        InstallStep(id: 3, key: "progress_step_model"),
        InstallStep(id: 4, key: "progress_step_config"),
        InstallStep(id: 5, key: "progress_step_qdrant"),
        InstallStep(id: 6, key: "progress_step_embeddings"),
        InstallStep(id: 7, key: "progress_step_knowledge"),
    ]
    @Published var currentStep: Int = 0
    @Published var progress: Double = 0
    @Published var logLines: [String] = []
    @Published var apiKey: String = ""
    @Published var installFinished: Bool = false
    @Published var installPartial: Bool = false
    @Published var installError: String?
    @Published var logFilePath: String = ""
    @Published var totalTime: String = ""

    // Existing-installation detection
    @Published var showExistingInstallAlert: Bool = false
    @Published var showBackupDoneAlert: Bool = false
    @Published var lastBackupPath: String = ""
    private var pendingInstallContinuation: (() -> Void)?

    /// Proposed path for the backup copy (sibling with timestamp).
    /// If installPath is /Applications/server-nexe and the time is 16:35:00 on
    /// 14/04/2026, returns /Applications/server-nexe-backup-20260414-163500
    var proposedBackupPath: String {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyyMMdd-HHmmss"
        let stamp = formatter.string(from: Date())
        return installPath + "-backup-" + stamp
    }

    private var installStartTime: Date?

    // Hardware
    @Published var hardware: HardwareInfo = HardwareInfo(
        ramGB: 0, isAppleSilicon: false, hasMetal: false,
        chipModel: "Detecting...", diskFreeGB: 0, diskTotalGB: 0
    )

    // Catalog
    @Published var catalog: ModelCatalog = ModelCatalog(tier8: [], tier16: [], tier24: [], tier32: [], tier48: [], tier64: [])

    private var process: Process?
    /// PID of the headless Python process, to be able to kill the process group (B191)
    private var installerPGID: pid_t = 0

    func detectHardware() {
        Task.detached {
            let hw = HardwareInfo.detect()
            await MainActor.run {
                self.hardware = hw
            }
        }
    }

    func loadCatalog() {
        catalog = ModelCatalog.load()
    }

    // MARK: - Installation

    func startInstall() {
        // Detect existing installation
        let markers = ["core", "venv", ".env"]
        let hasExisting = markers.contains { name in
            FileManager.default.fileExists(atPath: installPath + "/" + name)
        }

        if hasExisting {
            pendingInstallContinuation = { [weak self] in
                self?.doStartInstall()
            }
            showExistingInstallAlert = true
            return
        }

        doStartInstall()
    }

    func confirmOverwrite() {
        showExistingInstallAlert = false
        pendingInstallContinuation?()
        pendingInstallContinuation = nil
    }

    /// The user chose "Back up and continue".
    /// Renames installPath → installPath-backup-TIMESTAMP and then installs fresh.
    /// Mv is atomic and instant (it doesn't copy bytes). If it fails (permissions, etc.),
    /// it stores the error and doesn't start the installation.
    func confirmBackupAndOverwrite() {
        showExistingInstallAlert = false
        let backup = proposedBackupPath
        do {
            try FileManager.default.moveItem(atPath: installPath, toPath: backup)
            lastBackupPath = backup
            showBackupDoneAlert = true
            // The real continuation runs when the user dismisses the backup alert.
            // We leave the callback intact — dismissBackupDoneAlert() will fire it.
        } catch {
            appendLog("[ERROR] Could not move existing install to backup: \(error.localizedDescription)")
            installError = "Backup failed: \(error.localizedDescription)"
            pendingInstallContinuation = nil
        }
    }

    func dismissBackupDoneAlert() {
        showBackupDoneAlert = false
        pendingInstallContinuation?()
        pendingInstallContinuation = nil
    }

    func cancelOverwrite() {
        showExistingInstallAlert = false
        pendingInstallContinuation = nil
    }

    private func doStartInstall() {
        let model = selectedModel  // nil = "Continue without a model"

        // Determine engine
        let engine: String
        if let model = model, selectedEngine == "auto" {
            engine = model.recommendedEngine(isAppleSilicon: hardware.isAppleSilicon)
        } else if selectedEngine != "auto" {
            engine = selectedEngine
        } else {
            engine = "ollama"  // default when no model is selected
        }

        // Find the bundled Python in the app Resources
        let bundle = Bundle.main
        let pythonPath: String
        if let bundledPython = bundle.path(forResource: "python/bin/python3", ofType: nil) {
            pythonPath = bundledPython
        } else {
            // Fallback: look relative to the binary (development)
            let binaryDir = URL(fileURLWithPath: CommandLine.arguments[0]).deletingLastPathComponent()
            let devPython = binaryDir
                .deletingLastPathComponent() // MacOS
                .appendingPathComponent("Resources/python/bin/python3")
            if FileManager.default.fileExists(atPath: devPython.path) {
                pythonPath = devPython.path
            } else {
                appendLog("[ERROR] Python bundled not found")
                installError = "Python bundled not found in app bundle"
                return
            }
        }

        // Start timer
        installStartTime = Date()

        // First: unpack payload.tar.gz to installPath
        extractPayloadAndRun(pythonPath: pythonPath, model: model, engine: engine)
    }

    private func extractPayloadAndRun(pythonPath: String, model: AIModel?, engine: String) {
        Task.detached { [weak self] in
            guard let self = self else { return }

            // Find payload.tar.gz
            let bundle = Bundle.main
            let payloadPath: String
            if let bundled = bundle.path(forResource: "payload", ofType: "tar.gz") {
                payloadPath = bundled
            } else {
                let binaryDir = URL(fileURLWithPath: CommandLine.arguments[0]).deletingLastPathComponent()
                let devPayload = binaryDir
                    .deletingLastPathComponent()
                    .appendingPathComponent("Resources/payload.tar.gz")
                if FileManager.default.fileExists(atPath: devPayload.path) {
                    payloadPath = devPayload.path
                } else {
                    await MainActor.run {
                        self.appendLog("[ERROR] payload.tar.gz not found")
                        self.installError = "payload.tar.gz not found in app bundle"
                    }
                    return
                }
            }

            let installPath = await self.installPath

            // Create destination directory
            try? FileManager.default.createDirectory(
                atPath: installPath,
                withIntermediateDirectories: true
            )

            // Unpack payload
            await MainActor.run {
                self.appendLog("Extracting payload to \(installPath)...")
            }

            let tar = Process()
            tar.executableURL = URL(fileURLWithPath: "/usr/bin/tar")
            tar.arguments = ["xzf", payloadPath, "-C", installPath]
            tar.currentDirectoryURL = URL(fileURLWithPath: installPath)
            let tarErrPipe = Pipe()
            tar.standardError = tarErrPipe

            do {
                try tar.run()
                tar.waitUntilExit()

                if tar.terminationStatus != 0 {
                    let errData = tarErrPipe.fileHandleForReading.readDataToEndOfFile()
                    let errMsg = String(data: errData, encoding: .utf8) ?? "unknown"
                    await MainActor.run {
                        self.appendLog("[ERROR] Failed to extract payload (exit \(tar.terminationStatus)): \(errMsg)")
                        self.installError = "Failed to extract payload"
                    }
                    return
                }
            } catch {
                await MainActor.run {
                    self.appendLog("[ERROR] \(error.localizedDescription)")
                    self.installError = error.localizedDescription
                }
                return
            }

            // Copy Nexe.app and NexeTray.app from the Bundle Resources to installPath.
            // Build_dmg.sh bundles them into InstallNexe.app/Contents/Resources/ (excluded from the payload).
            // - Nexe.app → installPath/Nexe.app  (install_headless.py will copy it to /Applications/Nexe.app)
            // - NexeTray.app → installPath/installer/NexeTray.app  (CompletionView.openNexe launches it)
            if let resDir = Bundle.main.resourcePath {
                let fm = FileManager.default
                let bundledNexe = resDir + "/Nexe.app"
                if fm.fileExists(atPath: bundledNexe) {
                    await MainActor.run { self.appendLog("Deploying Nexe.app...") }
                    let dest = installPath + "/Nexe.app"
                    try? fm.removeItem(atPath: dest)
                    try? fm.copyItem(atPath: bundledNexe, toPath: dest)
                }
                let bundledTray = resDir + "/NexeTray.app"
                if fm.fileExists(atPath: bundledTray) {
                    await MainActor.run { self.appendLog("Deploying NexeTray.app...") }
                    let installerDir = installPath + "/installer"
                    try? fm.createDirectory(atPath: installerDir, withIntermediateDirectories: true)
                    let dest = installerDir + "/NexeTray.app"
                    try? fm.removeItem(atPath: dest)
                    try? fm.copyItem(atPath: bundledTray, toPath: dest)
                }
            }

            // Remove quarantine from the whole directory (AirDrop/Safari add it)
            let xattr = Process()
            xattr.executableURL = URL(fileURLWithPath: "/usr/bin/xattr")
            xattr.arguments = ["-rd", "com.apple.quarantine", installPath]
            try? xattr.run()
            xattr.waitUntilExit()

            // Remove quarantine from the bundled Python (inside the DMG app)
            let xattrPy = Process()
            xattrPy.executableURL = URL(fileURLWithPath: "/usr/bin/xattr")
            xattrPy.arguments = ["-rd", "com.apple.quarantine", pythonPath]
            try? xattrPy.run()
            xattrPy.waitUntilExit()

            await MainActor.run {
                self.appendLog("Payload extracted. Starting installation...")
            }

            // Now launch the headless Python installer
            await self.runHeadlessInstaller(
                pythonPath: pythonPath,
                installPath: installPath,
                model: model,
                engine: engine
            )
        }
    }

    private func runHeadlessInstaller(
        pythonPath: String, installPath: String,
        model: AIModel?, engine: String
    ) async {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: pythonPath)
        // --no-login-item: the wizard handles Login Items via the CompletionView checkbox
        process.arguments = ["-m", "installer.install_headless", "--no-login-item"]
        process.currentDirectoryURL = URL(fileURLWithPath: installPath)

        // Environment variables
        var env = ProcessInfo.processInfo.environment
        env["NEXE_PROJECT_ROOT"] = installPath
        env["NEXE_LANG"] = lang.rawValue
        env["PYTHONPATH"] = installPath

        process.environment = env

        let inputPipe = Pipe()
        let outputPipe = Pipe()
        let errorPipe = Pipe()
        process.standardInput = inputPipe
        process.standardOutput = outputPipe
        process.standardError = errorPipe

        self.process = process

        do {
            try process.run()
            // B191: create a new process group for the headless Python,
            // so cancelInstall can kill all the children (pip, ollama pull…)
            // with a single killpg. setpgid(pid, 0) → the process becomes the group leader.
            let pid = process.processIdentifier
            setpgid(pid, pid)   // new group: pgid == pid
            self.installerPGID = pid
        } catch {
            appendLog("[ERROR] Failed to launch installer: \(error.localizedDescription)")
            installError = error.localizedDescription
            return
        }

        // Send config JSON via stdin
        let config: [String: String] = [
            "lang": lang.rawValue,
            "path": installPath,
            "model_key": model?.key ?? "",
            "engine": engine,
        ]

        if let jsonData = try? JSONSerialization.data(withJSONObject: config) {
            inputPipe.fileHandleForWriting.write(jsonData)
            inputPipe.fileHandleForWriting.write("\n".data(using: .utf8)!)
        }
        inputPipe.fileHandleForWriting.closeFile()

        // Read stdout on a background thread (blocking, no race conditions)
        let outputHandle = outputPipe.fileHandleForReading
        let errorHandle = errorPipe.fileHandleForReading

        // Capture weak self outside the Task to avoid Swift 6 warnings
        weak let weakSelf = self

        // Read stderr in the background (Python/dyld errors)
        Task.detached {
            while true {
                let data = errorHandle.availableData
                if data.isEmpty { break }
                guard let text = String(data: data, encoding: .utf8) else { continue }
                for line in text.components(separatedBy: "\n") where !line.isEmpty {
                    let trimmed = line.trimmingCharacters(in: .whitespaces)
                    // Progress bars (pip, downloads): show them clean
                    if trimmed.contains("%") && trimmed.contains("#") {
                        await MainActor.run {
                            weakSelf?.appendLog(trimmed)
                        }
                    } else if trimmed.allSatisfy({ $0 == "#" || $0 == " " }) {
                        // Partial progress-bar fragments: ignore
                    } else if !trimmed.isEmpty {
                        // Real errors
                        await MainActor.run {
                            weakSelf?.appendLog("[stderr] \(trimmed)")
                        }
                    }
                }
            }
        }

        Task.detached {
            var lineBuffer = ""

            // Read data until the pipe closes (the process finishes)
            while true {
                let data = outputHandle.availableData
                if data.isEmpty { break } // EOF — pipe closed

                guard let text = String(data: data, encoding: .utf8) else { continue }
                lineBuffer += text

                // Process complete lines (separated by \n)
                while let newlineRange = lineBuffer.range(of: "\n") {
                    let completeLine = String(lineBuffer[lineBuffer.startIndex..<newlineRange.lowerBound])
                    lineBuffer = String(lineBuffer[newlineRange.upperBound...])

                    if !completeLine.isEmpty {
                        await MainActor.run {
                            weakSelf?.parseLine(completeLine)
                        }
                    }
                }
            }

            // Process the last buffer fragment (if it didn't end in \n)
            let remaining = lineBuffer.trimmingCharacters(in: .whitespacesAndNewlines)
            if !remaining.isEmpty {
                await MainActor.run {
                    weakSelf?.parseLine(remaining)
                }
            }

            // Wait for the process to finish
            process.waitUntilExit()
            let exitCode = process.terminationStatus

            await MainActor.run {
                guard let engine = weakSelf else { return }
                if exitCode != 0 && engine.installError == nil {
                    engine.installError = "Installation process exited with code \(exitCode)"
                }
                if engine.installError == nil {
                    engine.installFinished = true
                }
            }
        }
    }

    // MARK: - Parser for the [PROGRESS]/[API_KEY]/[DONE]/[ERROR] protocol

    private func parseLine(_ line: String) {
        // INST-005 (security): capture the API key marker BEFORE logging and
        // return early. logLines is rendered in a selectable ScrollView, so
        // appending an "[API_KEY] <secret>" line would expose the key on screen.
        if line.hasPrefix("[API_KEY]") {
            apiKey = line
                .replacingOccurrences(of: "[API_KEY]", with: "")
                .trimmingCharacters(in: .whitespaces)
            return
        }

        appendLog(line)

        if line.hasPrefix("[PROGRESS]") {
            parseProgress(line)
        } else if line.hasPrefix("[LOG]") {
            let path = line
                .replacingOccurrences(of: "[LOG]", with: "")
                .trimmingCharacters(in: .whitespaces)
            logFilePath = path
        } else if line.hasPrefix("[DONE_PARTIAL]") {
            // Installation completed but with issues (e.g. model download failed)
            progress = 1.0
            if let start = installStartTime {
                let elapsed = Int(Date().timeIntervalSince(start))
                let min = elapsed / 60
                let sec = elapsed % 60
                totalTime = min > 0 ? "\(min)m \(sec)s" : "\(sec)s"
            }
            installFinished = true
            installPartial = true
        } else if line.hasPrefix("[DONE]") {
            progress = 1.0
            if let start = installStartTime {
                let elapsed = Int(Date().timeIntervalSince(start))
                let min = elapsed / 60
                let sec = elapsed % 60
                if min > 0 {
                    totalTime = "\(min)m \(sec)s"
                } else {
                    totalTime = "\(sec)s"
                }
            }
            // B187: don't mark as successfully finished if there's a prior error;
            // a step with status=error would have set installError in parseProgress,
            // and a later [DONE] must not hide it by showing the green exit screen.
            if installError == nil {
                installFinished = true
            }
        } else if line.hasPrefix("[ERROR]") {
            let msg = line
                .replacingOccurrences(of: "[ERROR]", with: "")
                .trimmingCharacters(in: .whitespaces)
            installError = msg
        }
    }

    private func parseProgress(_ line: String) {
        // Format: [PROGRESS] step=N status=running|done|error [msg=text with spaces...]
        var stepNum = 0
        var status = ""
        var msg = ""

        let content = line
            .replacingOccurrences(of: "[PROGRESS]", with: "")
            .trimmingCharacters(in: .whitespaces)

        // Extract msg= first (captures everything to the end of the line)
        if let msgRange = content.range(of: "msg=") {
            msg = String(content[msgRange.upperBound...]).trimmingCharacters(in: .whitespaces)
        }

        // Parse step= and status= (before msg= or in the whole line)
        let prefixContent = content.contains("msg=")
            ? String(content[content.startIndex..<content.range(of: "msg=")!.lowerBound])
            : content

        for part in prefixContent.components(separatedBy: " ") {
            if part.hasPrefix("step=") {
                stepNum = Int(part.replacingOccurrences(of: "step=", with: "")) ?? 0
            } else if part.hasPrefix("status=") {
                status = part.replacingOccurrences(of: "status=", with: "")
            }
        }

        if stepNum > 0, stepNum <= steps.count {
            let idx = stepNum - 1
            let newStatus = StepStatus(rawValue: status) ?? .running
            // Record start and end times
            if newStatus == .running && steps[idx].startTime == nil {
                steps[idx].startTime = Date()
            }
            if newStatus == .done || newStatus == .error {
                steps[idx].endTime = Date()
            }
            steps[idx].status = newStatus
            if !msg.isEmpty {
                steps[idx].message = msg
            }
            currentStep = stepNum
            // running = half a step, done = full step. Never 100% until [DONE]
            let completedSteps = Double(stepNum - 1)
            let currentFraction = (status == "done") ? 1.0 : 0.5
            progress = min((completedSteps + currentFraction) / Double(steps.count), 0.95)

            if status == "error" {
                installError = msg.isEmpty ? "Error at step \(stepNum)" : msg
            }
        }
    }

    func appendLog(_ line: String) {
        logLines.append(line)
        // Limit to 500 lines
        if logLines.count > 500 {
            logLines.removeFirst(logLines.count - 500)
        }
    }

    func cancelInstall() {
        // B191: kill the entire process group (pip, ollama pull children, etc.)
        // killpg(pgid, SIGTERM) is equivalent to kill(-pgid, SIGTERM).
        if installerPGID > 0 {
            killpg(installerPGID, SIGTERM)
            installerPGID = 0
        } else {
            // Fallback if the pgid wasn't captured (e.g. cancel during extraction)
            process?.terminate()
        }
        process = nil
    }
}
