// WelcomeView.swift — Pantalla 1: Benvinguda amb logo server.nexe i detecció d'idioma

import SwiftUI
import AppKit

struct WelcomeView: View {
    @EnvironmentObject var engine: InstallerEngine
    let onNext: () -> Void

    var body: some View {
        VStack(spacing: 24) {
            Spacer()

            // Logo server.nexe des de Resources
            NexeLogo()
                .frame(width: 200, height: 60)

            // Títol
            Text(t("welcome_title"))
                .font(.system(size: 28, weight: .bold))

            Text(t("welcome_subtitle"))
                .font(.title3)
                .foregroundColor(.secondary)

            // Descripció
            Text(t("welcome_desc"))
                .font(.body)
                .multilineTextAlignment(.center)
                .foregroundColor(.secondary)
                .frame(maxWidth: 500)
                .padding(.horizontal)

            // Features
            VStack(alignment: .leading, spacing: 10) {
                FeatureRow(icon: "cpu", text: t("welcome_features_1"))
                FeatureRow(icon: "brain", text: t("welcome_features_2"))
                FeatureRow(icon: "globe", text: t("welcome_features_3"))
            }
            .padding(.horizontal, 40)

            // Selector d'idioma + tema
            HStack(spacing: 16) {
                ForEach(Lang.allCases, id: \.rawValue) { lang in
                    Button(action: { engine.lang = lang }) {
                        Text(lang.displayName)
                            .font(.subheadline)
                            .padding(.horizontal, 16)
                            .padding(.vertical, 6)
                            .background(
                                engine.lang == lang
                                    ? Color.nexeRed.opacity(0.15)
                                    : Color.clear
                            )
                            .cornerRadius(8)
                            .overlay(
                                RoundedRectangle(cornerRadius: 8)
                                    .stroke(
                                        engine.lang == lang ? Color.nexeRed : Color.gray.opacity(0.3),
                                        lineWidth: 1
                                    )
                            )
                    }
                    .buttonStyle(.plain)
                }

                Spacer().frame(width: 8)

                // Toggle dark/light
                Button(action: { engine.darkMode.toggle() }) {
                    Image(systemName: engine.darkMode ? "moon.fill" : "sun.max.fill")
                        .font(.system(size: 16))
                        .foregroundColor(engine.darkMode ? .yellow : .orange)
                        .padding(8)
                        .background(Color.gray.opacity(0.15))
                        .cornerRadius(8)
                }
                .buttonStyle(.plain)
            }

            Spacer()

            // Botó
            Button(action: {
                engine.detectHardware()
                engine.loadCatalog()
                onNext()
            }) {
                Text(t("btn_start"))
                    .font(.headline)
                    .frame(width: 200)
            }
            .nexePrimaryButton()
            .padding(.bottom, 24)
        }
        .padding()
    }

    private func t(_ key: String) -> String {
        T.get(key, lang: engine.lang)
    }
}

// MARK: - Logo carregat des de Resources/logo.png

struct NexeLogo: View {
    var body: some View {
        if let logoURL = Bundle.main.url(forResource: "logo", withExtension: "png"),
           let nsImage = NSImage(contentsOf: logoURL) {
            Image(nsImage: nsImage)
                .resizable()
                .aspectRatio(contentMode: .fit)
        } else {
            // Fallback: buscar al costat del binary (dev)
            let binaryDir = URL(fileURLWithPath: CommandLine.arguments[0]).deletingLastPathComponent()
            let devLogo = binaryDir
                .deletingLastPathComponent()
                .appendingPathComponent("Resources/logo.png")
            if let nsImage = NSImage(contentsOf: devLogo) {
                Image(nsImage: nsImage)
                    .resizable()
                    .aspectRatio(contentMode: .fit)
            } else {
                // Últim fallback: text estilitzat
                Text("> server.nexe")
                    .font(.system(size: 32, weight: .bold))
                    .foregroundColor(.nexeRed)
            }
        }
    }
}

struct FeatureRow: View {
    let icon: String
    let text: String

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: icon)
                .foregroundColor(.nexeRed)
                .frame(width: 24)
            Text(text)
                .font(.subheadline)
        }
    }
}

// MARK: - Color de marca server.nexe

extension Color {
    static let nexeRed = Color(red: 0.88, green: 0.22, blue: 0.21) // #E03835
}
