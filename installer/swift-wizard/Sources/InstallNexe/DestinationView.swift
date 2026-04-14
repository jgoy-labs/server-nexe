// DestinationView.swift — Pantalla 2: Selecció de carpeta amb NSOpenPanel

import SwiftUI
import AppKit

struct DestinationView: View {
    @EnvironmentObject var engine: InstallerEngine
    let onNext: () -> Void
    let onBack: () -> Void

    @State private var freeSpaceGB: Int = 0
    @State private var hasEnoughSpace: Bool = true

    var body: some View {
        VStack(spacing: 20) {
            Spacer()

            Image(systemName: "folder.badge.plus")
                .resizable()
                .aspectRatio(contentMode: .fit)
                .frame(width: 60, height: 60)
                .foregroundColor(.nexeRed)

            Text(t("dest_title"))
                .font(.system(size: 24, weight: .bold))

            Text(t("dest_desc"))
                .font(.body)
                .foregroundColor(.secondary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 500)

            // Path actual
            HStack {
                Image(systemName: "folder.fill")
                    .foregroundColor(.nexeRed)
                Text(engine.installPath)
                    .font(.system(.body, design: .monospaced))
                    .lineLimit(1)
                    .truncationMode(.middle)

                Spacer()

                Button(t("dest_choose")) {
                    chooseFolder()
                }
                .controlSize(.regular)
            }
            .padding()
            .background(Color(nsColor: .controlBackgroundColor))
            .cornerRadius(10)
            .padding(.horizontal, 40)

            // Info d'espai
            VStack(spacing: 8) {
                HStack {
                    Text(t("dest_free_space"))
                        .foregroundColor(.secondary)
                    Spacer()
                    Text("\(freeSpaceGB) GB")
                        .font(.system(.body, design: .monospaced))
                        .foregroundColor(hasEnoughSpace ? .primary : .red)
                }
                HStack {
                    Text(t("dest_required"))
                        .foregroundColor(.secondary)
                    Spacer()
                    Text("~5 GB")
                        .font(.system(.body, design: .monospaced))
                }
            }
            .padding(.horizontal, 60)

            if !hasEnoughSpace {
                HStack {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .foregroundColor(.red)
                    Text(t("dest_warning_space"))
                        .foregroundColor(.red)
                        .font(.subheadline)
                }
            }

            // Opcions Dock / Login
            VStack(alignment: .leading, spacing: 8) {
                Toggle(isOn: $engine.addToDock) {
                    HStack(spacing: 8) {
                        Image(systemName: "dock.rectangle")
                            .foregroundColor(.nexeRed)
                        Text(t("done_dock"))
                            .font(.subheadline)
                    }
                }
                .toggleStyle(.checkbox)

                Toggle(isOn: $engine.addLoginItem) {
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
            .padding(.top, 8)

            Spacer()

            // Botons
            HStack {
                Button(t("btn_back")) { onBack() }
                    .controlSize(.large)

                Spacer()

                Button(action: onNext) {
                    Text(t("btn_next"))
                        .frame(width: 120, height: 22)
                        .foregroundColor(.white)
                        .padding(.horizontal, 4)
                        .background(
                            RoundedRectangle(cornerRadius: 6)
                                .fill(hasEnoughSpace ? Color.nexeRed : Color.nexeRed.opacity(0.4))
                        )
                }
                .buttonStyle(.plain)
                .controlSize(.large)
                .disabled(!hasEnoughSpace)
            }
            .padding(.horizontal, 40)
            .padding(.bottom, 24)
        }
        .padding()
        .onAppear { updateDiskSpace() }
    }

    private func chooseFolder() {
        let panel = NSOpenPanel()
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.canCreateDirectories = true
        panel.allowsMultipleSelection = false
        panel.prompt = t("dest_choose")
        panel.directoryURL = URL(fileURLWithPath: "/Applications")

        if panel.runModal() == .OK, let url = panel.url {
            engine.installPath = url.appendingPathComponent("server-nexe").path
            updateDiskSpace()
        }
    }

    private func updateDiskSpace() {
        let parentPath = (engine.installPath as NSString).deletingLastPathComponent
        let url = URL(fileURLWithPath: parentPath)
        if let values = try? url.resourceValues(forKeys: [.volumeAvailableCapacityForImportantUsageKey]),
           let free = values.volumeAvailableCapacityForImportantUsage {
            freeSpaceGB = Int(free / (1024 * 1024 * 1024))
            hasEnoughSpace = freeSpaceGB >= 5
        }
    }

    private func t(_ key: String) -> String {
        T.get(key, lang: engine.lang)
    }
}
