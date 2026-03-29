// InstallerEngine.swift — Lògica central: descomprimir payload, cridar Python, parsejar progrés

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
    // Configuració triada per l'usuari
    @Published var lang: Lang = .fromSystem()
    @Published var darkMode: Bool = {
        let hour = Calendar.current.component(.hour, from: Date())
        return hour < 7 || hour >= 20  // fosc de 20h a 7h
    }()
    @Published var installPath: String = NSHomeDirectory() + "/server-nexe"
    @Published var selectedModel: AIModel?
    @Published var selectedEngine: String = "auto"

    // Estat de la instal·lació
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

    // Detecció instal·lació existent
    @Published var showExistingInstallAlert: Bool = false
    private var pendingInstallContinuation: (() -> Void)?

    private var installStartTime: Date?

    // Hardware
    @Published var hardware: HardwareInfo = HardwareInfo(
        ramGB: 0, isAppleSilicon: false, hasMetal: false,
        chipModel: "Detecting...", diskFreeGB: 0, diskTotalGB: 0
    )

    // Catàleg
    @Published var catalog: ModelCatalog = ModelCatalog(small: [], medium: [], large: [])

    private var process: Process?

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

    // MARK: - Instal·lació

    func startInstall() {
        // Detectar instal·lació existent
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

    func cancelOverwrite() {
        showExistingInstallAlert = false
        pendingInstallContinuation = nil
    }

    private func doStartInstall() {
        guard let model = selectedModel else { return }

        // Determinar engine
        let engine: String
        if selectedEngine == "auto" {
            engine = model.recommendedEngine(isAppleSilicon: hardware.isAppleSilicon)
        } else {
            engine = selectedEngine
        }

        // Trobar Python bundled als Resources de l'app
        let bundle = Bundle.main
        let pythonPath: String
        if let bundledPython = bundle.path(forResource: "python/bin/python3", ofType: nil) {
            pythonPath = bundledPython
        } else {
            // Fallback: buscar relatiu al binary (desenvolupament)
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

        // Iniciar timer
        installStartTime = Date()

        // Primer: descomprimir payload.tar.gz a installPath
        extractPayloadAndRun(pythonPath: pythonPath, model: model, engine: engine)
    }

    private func extractPayloadAndRun(pythonPath: String, model: AIModel, engine: String) {
        Task.detached { [weak self] in
            guard let self = self else { return }

            // Trobar payload.tar.gz
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

            // Crear directori destí
            try? FileManager.default.createDirectory(
                atPath: installPath,
                withIntermediateDirectories: true
            )

            // Descomprimir payload
            await MainActor.run {
                self.appendLog("Extracting payload to \(installPath)...")
            }

            let tar = Process()
            tar.executableURL = URL(fileURLWithPath: "/usr/bin/tar")
            tar.arguments = ["xzf", payloadPath, "-C", installPath]
            tar.currentDirectoryURL = URL(fileURLWithPath: installPath)

            do {
                try tar.run()
                tar.waitUntilExit()

                if tar.terminationStatus != 0 {
                    await MainActor.run {
                        self.appendLog("[ERROR] Failed to extract payload (exit \(tar.terminationStatus))")
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

            // Descomprimir .nexe-app.tar.gz → Nexe.app (necessari per install_headless)
            let nexeTarPath = installPath + "/.nexe-app.tar.gz"
            if FileManager.default.fileExists(atPath: nexeTarPath) {
                await MainActor.run {
                    self.appendLog("Extracting Nexe.app...")
                }
                let nexeTar = Process()
                nexeTar.executableURL = URL(fileURLWithPath: "/usr/bin/tar")
                nexeTar.arguments = ["xzf", nexeTarPath, "-C", installPath]
                try? nexeTar.run()
                nexeTar.waitUntilExit()
            }

            // Treure quarantine de tot el directori (AirDrop/Safari l'afegeixen)
            let xattr = Process()
            xattr.executableURL = URL(fileURLWithPath: "/usr/bin/xattr")
            xattr.arguments = ["-rd", "com.apple.quarantine", installPath]
            try? xattr.run()
            xattr.waitUntilExit()

            // Treure quarantine del Python bundled (dins l'app del DMG)
            let xattrPy = Process()
            xattrPy.executableURL = URL(fileURLWithPath: "/usr/bin/xattr")
            xattrPy.arguments = ["-rd", "com.apple.quarantine", pythonPath]
            try? xattrPy.run()
            xattrPy.waitUntilExit()

            await MainActor.run {
                self.appendLog("Payload extracted. Starting installation...")
            }

            // Ara llançar Python headless installer
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
        model: AIModel, engine: String
    ) async {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: pythonPath)
        process.arguments = ["-m", "installer.install_headless"]
        process.currentDirectoryURL = URL(fileURLWithPath: installPath)

        // Variables d'entorn
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
        } catch {
            appendLog("[ERROR] Failed to launch installer: \(error.localizedDescription)")
            installError = error.localizedDescription
            return
        }

        // Enviar config JSON via stdin
        let config: [String: String] = [
            "lang": lang.rawValue,
            "path": installPath,
            "model_key": model.key,
            "engine": engine,
        ]

        if let jsonData = try? JSONSerialization.data(withJSONObject: config) {
            inputPipe.fileHandleForWriting.write(jsonData)
            inputPipe.fileHandleForWriting.write("\n".data(using: .utf8)!)
        }
        inputPipe.fileHandleForWriting.closeFile()

        // Llegir stdout en background thread (bloquejant, sense race conditions)
        let outputHandle = outputPipe.fileHandleForReading
        let errorHandle = errorPipe.fileHandleForReading

        // Capturar weak self fora del Task per evitar warnings Swift 6
        weak let weakSelf = self

        // Llegir stderr en background (errors de Python/dyld)
        Task.detached {
            while true {
                let data = errorHandle.availableData
                if data.isEmpty { break }
                guard let text = String(data: data, encoding: .utf8) else { continue }
                for line in text.components(separatedBy: "\n") where !line.isEmpty {
                    let trimmed = line.trimmingCharacters(in: .whitespaces)
                    // Barres de progres (pip, descàrregues): mostrar netes
                    if trimmed.contains("%") && trimmed.contains("#") {
                        await MainActor.run {
                            weakSelf?.appendLog(trimmed)
                        }
                    } else if trimmed.allSatisfy({ $0 == "#" || $0 == " " }) {
                        // Fragments de barra parcial: ignorar
                    } else if !trimmed.isEmpty {
                        // Errors reals
                        await MainActor.run {
                            weakSelf?.appendLog("[stderr] \(trimmed)")
                        }
                    }
                }
            }
        }

        Task.detached {
            var lineBuffer = ""

            // Llegir dades fins que el pipe es tanqui (el procés acabi)
            while true {
                let data = outputHandle.availableData
                if data.isEmpty { break } // EOF — pipe tancat

                guard let text = String(data: data, encoding: .utf8) else { continue }
                lineBuffer += text

                // Processar línies completes (separades per \n)
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

            // Processar últim fragment del buffer (si no acabava en \n)
            let remaining = lineBuffer.trimmingCharacters(in: .whitespacesAndNewlines)
            if !remaining.isEmpty {
                await MainActor.run {
                    weakSelf?.parseLine(remaining)
                }
            }

            // Esperar que el procés acabi
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

    // MARK: - Parser del protocol [PROGRESS]/[API_KEY]/[DONE]/[ERROR]

    private func parseLine(_ line: String) {
        appendLog(line)

        if line.hasPrefix("[PROGRESS]") {
            parseProgress(line)
        } else if line.hasPrefix("[API_KEY]") {
            let key = line
                .replacingOccurrences(of: "[API_KEY]", with: "")
                .trimmingCharacters(in: .whitespaces)
            apiKey = key
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
            installFinished = true
        } else if line.hasPrefix("[ERROR]") {
            let msg = line
                .replacingOccurrences(of: "[ERROR]", with: "")
                .trimmingCharacters(in: .whitespaces)
            installError = msg
        }
    }

    private func parseProgress(_ line: String) {
        // Format: [PROGRESS] step=N status=running|done|error [msg=text amb espais...]
        var stepNum = 0
        var status = ""
        var msg = ""

        let content = line
            .replacingOccurrences(of: "[PROGRESS]", with: "")
            .trimmingCharacters(in: .whitespaces)

        // Extreure msg= primer (captura tot fins al final de línia)
        if let msgRange = content.range(of: "msg=") {
            msg = String(content[msgRange.upperBound...]).trimmingCharacters(in: .whitespaces)
        }

        // Parsejar step= i status= (abans de msg= o en tota la línia)
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
            // Registrar temps d'inici i fi
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
            // running = mig pas, done = pas complet. Mai 100% fins [DONE]
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
        // Limitar a 500 línies
        if logLines.count > 500 {
            logLines.removeFirst(logLines.count - 500)
        }
    }

    func cancelInstall() {
        process?.terminate()
        process = nil
    }
}
