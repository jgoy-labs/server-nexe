// InstallerWizardView.swift — Navegació entre pantalles del wizard

import SwiftUI
import Combine

enum WizardStep: Int, CaseIterable {
    case welcome = 0
    case destination = 1
    case model = 2
    case confirm = 3
    case progress = 4
    case completion = 5
}

struct InstallerWizardView: View {
    @EnvironmentObject var engine: InstallerEngine
    @State private var currentStep: WizardStep = .welcome
    @State private var showCancelAlert = false
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(spacing: 0) {
            // Barra de progrés del wizard + botó cancel
            HStack {
                WizardProgressBar(currentStep: currentStep)

                if currentStep != .completion {
                    Spacer().frame(width: 16)
                    Button(action: { showCancelAlert = true }) {
                        Image(systemName: "xmark.circle.fill")
                            .font(.title3)
                            .foregroundColor(.secondary.opacity(0.6))
                    }
                    .buttonStyle(.plain)
                    .help(t("btn_cancel"))
                }
            }
            .padding(.top, 16)
            .padding(.horizontal, 24)

            Divider()
                .padding(.top, 12)

            // Contingut de la pantalla actual
            Group {
                switch currentStep {
                case .welcome:
                    WelcomeView(onNext: { currentStep = .destination })
                case .destination:
                    DestinationView(
                        onNext: { currentStep = .model },
                        onBack: { currentStep = .welcome }
                    )
                case .model:
                    ModelPickerView(
                        onNext: { currentStep = .confirm },
                        onBack: { currentStep = .destination }
                    )
                case .confirm:
                    ConfirmView(
                        onNext: {
                            currentStep = .progress
                            engine.startInstall()
                        },
                        onBack: { currentStep = .model }
                    )
                case .progress:
                    InstallProgressView()
                case .completion:
                    CompletionView()
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .background(Color(nsColor: .windowBackgroundColor))
        .onReceive(engine.$installFinished) { finished in
            if finished {
                currentStep = .completion
            }
        }
        .alert(t("btn_cancel"), isPresented: $showCancelAlert) {
            Button(t("btn_cancel"), role: .destructive) {
                NSApplication.shared.terminate(nil)
            }
            Button(t("btn_back"), role: .cancel) {}
        } message: {
            Text(t("cancel_confirm"))
        }
        .alert(t("existing_install_title"), isPresented: $engine.showExistingInstallAlert) {
            Button(t("existing_install_overwrite"), role: .destructive) {
                engine.confirmOverwrite()
            }
            Button(t("existing_install_change"), role: .cancel) {
                engine.cancelOverwrite()
                currentStep = .destination
            }
        } message: {
            Text(t("existing_install_msg"))
        }
    }

    private func t(_ key: String) -> String {
        T.get(key, lang: engine.lang)
    }
}

// MARK: - Pantalla de confirmació (resum descàrregues + avís quarantena)

struct ConfirmView: View {
    @EnvironmentObject var engine: InstallerEngine
    let onNext: () -> Void
    let onBack: () -> Void

    var body: some View {
        VStack(spacing: 20) {
            Spacer()

            Image(systemName: "arrow.down.circle")
                .resizable()
                .aspectRatio(contentMode: .fit)
                .frame(width: 50, height: 50)
                .foregroundColor(.nexeRed)

            Text(t("confirm_title"))
                .font(.system(size: 22, weight: .bold))

            Text(t("confirm_desc"))
                .font(.body)
                .foregroundColor(.secondary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 500)

            // Resum del que es descarregarà
            VStack(alignment: .leading, spacing: 10) {
                if let model = engine.selectedModel {
                    DownloadItem(
                        icon: "brain",
                        name: model.name,
                        size: "\(String(format: "%.1f", model.diskGB)) GB",
                        desc: t("confirm_model_desc")
                    )
                }
                DownloadItem(
                    icon: "shippingbox",
                    name: "Python dependencies",
                    size: "~200 MB",
                    desc: t("confirm_deps_desc")
                )
                DownloadItem(
                    icon: "cylinder",
                    name: "Vector DB",
                    size: "—",
                    desc: t("confirm_qdrant_desc")
                )
                DownloadItem(
                    icon: "text.magnifyingglass",
                    name: "Embeddings",
                    size: "~100 MB",
                    desc: t("confirm_embeddings_desc")
                )
            }
            .padding(16)
            .background(Color(nsColor: .controlBackgroundColor))
            .cornerRadius(10)
            .padding(.horizontal, 40)

            // Avís quarantena
            HStack(alignment: .top, spacing: 10) {
                Image(systemName: "shield.lefthalf.filled")
                    .foregroundColor(.orange)
                    .font(.title3)
                Text(t("confirm_quarantine"))
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
            .padding(.horizontal, 50)

            Spacer()

            // Botons
            HStack {
                Button(t("btn_back")) { onBack() }
                    .controlSize(.large)

                Spacer()

                Button(action: onNext) {
                    Text(t("btn_install"))
                        .frame(width: 160)
                }
                .controlSize(.large)
                .buttonStyle(.borderedProminent)
                .tint(.nexeRed)
            }
            .padding(.horizontal, 40)
            .padding(.bottom, 24)
        }
        .padding()
    }

    private func t(_ key: String) -> String {
        T.get(key, lang: engine.lang)
    }
}

struct DownloadItem: View {
    let icon: String
    let name: String
    let size: String
    let desc: String

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: icon)
                .foregroundColor(.nexeRed)
                .frame(width: 20)
            VStack(alignment: .leading, spacing: 2) {
                HStack {
                    Text(name).font(.subheadline).fontWeight(.medium)
                    Spacer()
                    Text(size).font(.caption).foregroundColor(.secondary)
                }
                Text(desc).font(.caption).foregroundColor(.secondary)
            }
        }
    }
}

// MARK: - Barra de progrés visual

struct WizardProgressBar: View {
    let currentStep: WizardStep
    private let steps = WizardStep.allCases

    var body: some View {
        HStack(spacing: 0) {
            ForEach(steps, id: \.rawValue) { step in
                HStack(spacing: 6) {
                    Circle()
                        .fill(step.rawValue <= currentStep.rawValue ? Color.nexeRed : Color.gray.opacity(0.3))
                        .frame(width: 10, height: 10)
                    if step != steps.last {
                        Rectangle()
                            .fill(step.rawValue < currentStep.rawValue ? Color.nexeRed : Color.gray.opacity(0.3))
                            .frame(height: 2)
                    }
                }
            }
        }
        .frame(height: 10)
    }
}
