// ModelPickerView.swift — Pantalla 3: Selecció de model amb tabs i targetes

import SwiftUI

struct ModelPickerView: View {
    @EnvironmentObject var engine: InstallerEngine
    let onNext: () -> Void
    let onBack: () -> Void

    @State private var selectedTab: String = "tier_16"
    @State private var selectedEngineOption: String = "auto"
    @State private var customOllamaName: String = ""
    @State private var customHFRepo: String = ""

    var body: some View {
        VStack(spacing: 16) {
            // Hardware info
            HardwareBar(hardware: engine.hardware, lang: engine.lang)
                .padding(.horizontal, 24)
                .padding(.top, 12)

            Text(t("model_title"))
                .font(.system(size: 22, weight: .bold))

            Text(t("model_desc"))
                .font(.subheadline)
                .foregroundColor(.secondary)

            // Tabs RAM (7 tiers + custom)
            ScrollView(.horizontal, showsIndicators: false) {
                Picker("", selection: $selectedTab) {
                    Text("8 GB").tag("tier_8")
                    Text("16 GB").tag("tier_16")
                    Text("24 GB").tag("tier_24")
                    Text("32 GB").tag("tier_32")
                    Text("48 GB").tag("tier_48")
                    Text("64 GB").tag("tier_64")
                    Text(t("model_tab_custom")).tag("custom")
                }
                .pickerStyle(.segmented)
                .frame(minWidth: 640)
            }
            .padding(.horizontal, 24)

            if selectedTab == "custom" {
                // Pestanya personalitzat
                CustomModelView(
                    ollamaName: $customOllamaName,
                    hfRepo: $customHFRepo,
                    lang: engine.lang,
                    onSelectOllama: { name in
                        engine.selectedModel = AIModel.customOllama(name)
                        engine.selectedEngine = "ollama"
                    },
                    onSelectHF: { repo in
                        engine.selectedModel = AIModel.customHuggingFace(repo)
                        engine.selectedEngine = "llama_cpp"
                    }
                )
            } else {
                // Llista de models del catàleg
                GeometryReader { geo in
                    ScrollView {
                        VStack {
                            Spacer(minLength: 0)
                            LazyVStack(spacing: 10) {
                                ForEach(engine.catalog.models(for: selectedTab)) { model in
                                    let tooLarge = model.ramGB > Double(engine.hardware.ramGB) * 0.75
                                    ModelCard(
                                        model: model,
                                        isSelected: engine.selectedModel?.key == model.key,
                                        isRecommended: isRecommended(model),
                                        isDisabled: tooLarge,
                                        lang: engine.lang
                                    ) {
                                        if !tooLarge {
                                            engine.selectedModel = model
                                            selectedEngineOption = "auto"
                                            engine.selectedEngine = "auto"
                                        }
                                    }
                                }
                            }
                            .padding(.horizontal, 24)
                            Spacer(minLength: 0)
                        }
                        .frame(minHeight: geo.size.height)
                    }
                }
            }

            // Engine selector (només si hi ha model seleccionat)
            if let model = engine.selectedModel {
                HStack {
                    Text(t("model_engine"))
                        .font(.subheadline)
                        .foregroundColor(.secondary)

                    Picker("", selection: $selectedEngineOption) {
                        Text(t("model_engine_auto")).tag("auto")
                        ForEach(model.availableEngines, id: \.self) { eng in
                            Text(eng.uppercased()).tag(eng)
                        }
                    }
                    .frame(width: 250)
                    .onChange(of: selectedEngineOption) { newValue in
                        engine.selectedEngine = newValue
                    }
                }
                .padding(.horizontal, 24)
            }

            // Botons
            HStack {
                Button(t("btn_back")) { onBack() }
                    .controlSize(.large)

                Spacer()

                Button(t("btn_skip_model")) {
                    engine.selectedModel = nil
                    onNext()
                }
                .controlSize(.large)
                .foregroundColor(.secondary)

                Button(action: onNext) {
                    Text(t("btn_next"))
                        .frame(width: 140)
                }
                .controlSize(.large)
                .buttonStyle(.borderedProminent)
                .tint(.nexeRed)
            }
            .padding(.horizontal, 24)
            .padding(.bottom, 16)
        }
        .onAppear {
            selectedTab = engine.hardware.ramTier
        }
    }

    private func isRecommended(_ model: AIModel) -> Bool {
        let tier = engine.hardware.ramTier
        return engine.catalog.models(for: tier).first?.key == model.key
    }

    private func t(_ key: String) -> String {
        T.get(key, lang: engine.lang)
    }
}

// MARK: - Hardware info bar

struct HardwareBar: View {
    let hardware: HardwareInfo
    let lang: Lang

    var body: some View {
        HStack(spacing: 20) {
            HWChip(icon: "memorychip", label: t("model_hw_ram"), value: "\(hardware.ramGB) GB")
            HWChip(icon: "cpu", label: t("model_hw_chip"), value: hardware.chipModel)
            if hardware.hasMetal {
                HWChip(icon: "bolt.fill", label: t("model_hw_metal"), value: "Yes")
            }
            HWChip(icon: "internaldrive", label: t("model_hw_disk"), value: "\(hardware.diskFreeGB) GB")
        }
        .padding(10)
        .background(Color(nsColor: .controlBackgroundColor))
        .cornerRadius(10)
    }

    private func t(_ key: String) -> String {
        T.get(key, lang: lang)
    }
}

struct HWChip: View {
    let icon: String
    let label: String
    let value: String

    var body: some View {
        VStack(spacing: 4) {
            Image(systemName: icon)
                .foregroundColor(.nexeRed)
                .font(.caption)
            Text(label)
                .font(.caption2)
                .foregroundColor(.secondary)
            Text(value)
                .font(.caption)
                .fontWeight(.medium)
                .lineLimit(1)
                .truncationMode(.tail)
        }
        .frame(maxWidth: .infinity)
    }
}

// MARK: - Model card

struct ModelCard: View {
    let model: AIModel
    let isSelected: Bool
    let isRecommended: Bool
    let isDisabled: Bool
    let lang: Lang
    let onSelect: () -> Void

    var body: some View {
        Button(action: onSelect) {
            HStack(spacing: 12) {
                VStack(alignment: .leading, spacing: 4) {
                    HStack {
                        Text(model.name)
                            .font(.headline)
                        if isRecommended && !isDisabled {
                            Text(T.get("model_recommended", lang: lang))
                                .font(.caption)
                                .padding(.horizontal, 6)
                                .padding(.vertical, 2)
                                .background(Color.green.opacity(0.2))
                                .foregroundColor(.green)
                                .cornerRadius(4)
                        }
                        if isDisabled {
                            Text(T.get("model_too_large", lang: lang))
                                .font(.caption)
                                .padding(.horizontal, 6)
                                .padding(.vertical, 2)
                                .background(Color.orange.opacity(0.15))
                                .foregroundColor(.orange)
                                .cornerRadius(4)
                        }
                    }

                    HStack(spacing: 4) {
                        Text(model.origin)
                        if let year = model.year {
                            Text("(\(String(year)))")
                        }
                    }
                    .font(.subheadline)
                    .foregroundColor(.secondary)

                    Text(model.localizedDescription(lang: lang))
                        .font(.caption)
                        .foregroundColor(.secondary)
                        .lineLimit(2)
                }

                Spacer()

                VStack(alignment: .trailing, spacing: 4) {
                    Text(model.params)
                        .font(.caption)
                        .foregroundColor(.secondary)
                    Text("\(String(format: "%.1f", model.diskGB)) GB")
                        .font(.caption)
                        .foregroundColor(.secondary)
                    HStack(spacing: 4) {
                        ForEach(model.availableEngines, id: \.self) { eng in
                            Text(eng)
                                .font(.system(size: 9))
                                .padding(.horizontal, 4)
                                .padding(.vertical, 1)
                                .background(Color.nexeRed.opacity(0.1))
                                .cornerRadius(3)
                        }
                    }
                }
            }
            .padding(12)
            .background(
                RoundedRectangle(cornerRadius: 10)
                    .fill(isSelected ? Color.nexeRed.opacity(0.1) : Color(nsColor: .controlBackgroundColor))
            )
            .overlay(
                RoundedRectangle(cornerRadius: 10)
                    .stroke(isSelected ? Color.nexeRed : Color.clear, lineWidth: 2)
            )
            .opacity(isDisabled ? 0.45 : 1.0)
        }
        .buttonStyle(.plain)
        .disabled(isDisabled)
    }
}

// MARK: - Custom model view

struct CustomModelView: View {
    @Binding var ollamaName: String
    @Binding var hfRepo: String
    let lang: Lang
    let onSelectOllama: (String) -> Void
    let onSelectHF: (String) -> Void

    @State private var selectedSource: String = "ollama"

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                Text(t("model_custom_desc"))
                    .font(.subheadline)
                    .foregroundColor(.secondary)

                // Selector Ollama / HuggingFace
                Picker("", selection: $selectedSource) {
                    Text("Ollama").tag("ollama")
                    Text("Hugging Face").tag("hf")
                }
                .pickerStyle(.segmented)
                .frame(width: 300)

                if selectedSource == "ollama" {
                    // Ollama
                    VStack(alignment: .leading, spacing: 8) {
                        Text(t("model_custom_ollama_label"))
                            .font(.headline)

                        TextField(t("model_custom_ollama_hint"), text: $ollamaName)
                            .textFieldStyle(.roundedBorder)
                            .frame(maxWidth: 400)
                            .onSubmit {
                                if !ollamaName.trimmingCharacters(in: .whitespaces).isEmpty {
                                    onSelectOllama(ollamaName.trimmingCharacters(in: .whitespaces))
                                }
                            }

                        if !ollamaName.trimmingCharacters(in: .whitespaces).isEmpty {
                            Button(action: {
                                onSelectOllama(ollamaName.trimmingCharacters(in: .whitespaces))
                            }) {
                                HStack {
                                    Image(systemName: "checkmark.circle.fill")
                                    Text(ollamaName.trimmingCharacters(in: .whitespaces))
                                        .fontWeight(.medium)
                                }
                                .padding(.horizontal, 16)
                                .padding(.vertical, 8)
                                .background(Color.nexeRed.opacity(0.1))
                                .cornerRadius(8)
                                .overlay(
                                    RoundedRectangle(cornerRadius: 8)
                                        .stroke(Color.nexeRed, lineWidth: 1)
                                )
                            }
                            .buttonStyle(.plain)
                        }
                    }
                } else {
                    // Hugging Face
                    VStack(alignment: .leading, spacing: 8) {
                        Text(t("model_custom_hf_label"))
                            .font(.headline)

                        TextField(t("model_custom_hf_hint"), text: $hfRepo)
                            .textFieldStyle(.roundedBorder)
                            .frame(maxWidth: 400)
                            .onSubmit {
                                if !hfRepo.trimmingCharacters(in: .whitespaces).isEmpty {
                                    onSelectHF(hfRepo.trimmingCharacters(in: .whitespaces))
                                }
                            }

                        if !hfRepo.trimmingCharacters(in: .whitespaces).isEmpty {
                            Button(action: {
                                onSelectHF(hfRepo.trimmingCharacters(in: .whitespaces))
                            }) {
                                HStack {
                                    Image(systemName: "checkmark.circle.fill")
                                    Text(hfRepo.trimmingCharacters(in: .whitespaces))
                                        .fontWeight(.medium)
                                }
                                .padding(.horizontal, 16)
                                .padding(.vertical, 8)
                                .background(Color.nexeRed.opacity(0.1))
                                .cornerRadius(8)
                                .overlay(
                                    RoundedRectangle(cornerRadius: 8)
                                        .stroke(Color.nexeRed, lineWidth: 1)
                                )
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }

                // Warning
                HStack(spacing: 8) {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .foregroundColor(.orange)
                    Text(t("model_custom_warning"))
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
                .padding(.top, 8)
            }
            .padding(.horizontal, 24)
            .padding(.top, 8)
        }
    }

    private func t(_ key: String) -> String {
        T.get(key, lang: lang)
    }
}
