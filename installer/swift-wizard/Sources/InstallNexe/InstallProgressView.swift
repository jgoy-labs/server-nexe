// InstallProgressView.swift — Pantalla 4: Progrés amb 7 passos, temps estimats i log visible

import SwiftUI

struct InstallProgressView: View {
    @EnvironmentObject var engine: InstallerEngine

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

            // Llista de passos amb temps estimats
            VStack(alignment: .leading, spacing: 6) {
                ForEach(engine.steps) { step in
                    StepRow(step: step, lang: engine.lang)
                }
            }
            .padding(.horizontal, 40)

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
    }

    private func t(_ key: String) -> String {
        T.get(key, lang: engine.lang)
    }
}

struct StepRow: View {
    let step: InstallStep
    let lang: Lang

    // Temps estimats per cada pas
    private var timeEstimate: String {
        switch step.id {
        case 1: return "~5s"
        case 2: return "~30s"
        case 3: return "~1-5 min"
        case 4: return "~1s"
        case 5: return "~5s"
        case 6: return "~30s"
        case 7: return "~30s"
        default: return ""
        }
    }

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

            if step.status == .pending || step.status == .running {
                Text(timeEstimate)
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
