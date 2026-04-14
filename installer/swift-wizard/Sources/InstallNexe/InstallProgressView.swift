// InstallProgressView.swift — Pantalla 4: Progrés amb 7 passos, temps estimats i log visible

import SwiftUI
import AppKit

struct InstallProgressView: View {
    @EnvironmentObject var engine: InstallerEngine
    @State private var tick = false
    private let timer = Timer.publish(every: 1, on: .main, in: .common).autoconnect()

    var body: some View {
        VStack(spacing: 12) {
            Text(t("progress_title"))
                .font(.system(size: 22, weight: .bold))
                .padding(.top, 12)

            // Barra de progrés global
            VStack(spacing: 4) {
                ProgressView(value: engine.progress)
                    .progressViewStyle(.linear)
                    .tint(.nexeRed)
                    .frame(height: 8)

                Text("\(Int(engine.progress * 100))%")
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
            .padding(.horizontal, 40)

            // Llista de passos amb temps real
            VStack(alignment: .leading, spacing: 6) {
                ForEach(engine.steps) { step in
                    StepRow(step: step, lang: engine.lang, tick: tick)
                }
            }
            .padding(.horizontal, 40)
            .onReceive(timer) { _ in
                tick.toggle()
                // Recuperar focus periodicament durant l'install (subprocessos
                // de tar/xattr/Python poden enviar la finestra al fons).
                if !engine.installFinished {
                    NSApp.windows.first?.orderFrontRegardless()
                }
            }

            // Error
            if let error = engine.installError {
                HStack {
                    Image(systemName: "xmark.circle.fill")
                        .foregroundColor(.red)
                    Text(error)
                        .font(.subheadline)
                        .foregroundColor(.red)
                        .lineLimit(3)
                }
                .padding(.horizontal, 40)
            }

            // Log sempre visible
            VStack(alignment: .leading, spacing: 4) {
                Text(t("progress_log"))
                    .font(.caption)
                    .foregroundColor(.secondary)

                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 2) {
                            ForEach(Array(engine.logLines.enumerated()), id: \.offset) { idx, line in
                                Text(line)
                                    .font(.system(size: 11, design: .monospaced))
                                    .foregroundColor(.secondary)
                                    .textSelection(.enabled)
                                    .id(idx)
                            }
                        }
                        .padding(8)
                    }
                    .frame(maxHeight: .infinity)
                    .background(Color(nsColor: .textBackgroundColor))
                    .cornerRadius(6)
                    .onChange(of: engine.logLines.count) { _ in
                        if let last = engine.logLines.indices.last {
                            proxy.scrollTo(last, anchor: .bottom)
                        }
                    }
                }
            }
            .padding(.horizontal, 40)
            .padding(.bottom, 16)
        }
        .onAppear {
            // Bring wizard window to front quan comença l'install.
            NSApp.activate(ignoringOtherApps: true)
            NSApp.windows.first?.makeKeyAndOrderFront(nil)
        }
    }

    private func t(_ key: String) -> String {
        T.get(key, lang: engine.lang)
    }
}

struct StepRow: View {
    let step: InstallStep
    let lang: Lang
    let tick: Bool  // força re-render cada segon

    var body: some View {
        HStack(spacing: 10) {
            // Icona d'estat
            Group {
                switch step.status {
                case .pending:
                    Image(systemName: "circle")
                        .foregroundColor(.gray.opacity(0.4))
                case .running:
                    ProgressView()
                        .controlSize(.small)
                case .done:
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundColor(.green)
                case .error:
                    Image(systemName: "xmark.circle.fill")
                        .foregroundColor(.red)
                }
            }
            .frame(width: 18)

            Text(T.get(step.key, lang: lang))
                .font(.subheadline)
                .foregroundColor(step.status == .pending ? .secondary : .primary)

            // Temps real (running: comptador viu, done: temps final)
            if let elapsed = step.elapsed {
                Text(elapsed)
                    .font(.caption2)
                    .foregroundColor(.secondary.opacity(0.6))
            }

            Spacer()

            if !step.message.isEmpty {
                Text(step.message)
                    .font(.caption)
                    .foregroundColor(.secondary)
                    .lineLimit(1)
            }
        }
        .padding(.vertical, 2)
    }
}
