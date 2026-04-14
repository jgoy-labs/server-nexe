// ModelCatalog.swift — Catàleg de models carregat des de JSON (generat per export_catalog_json.py)

import Foundation

struct AIModel: Codable, Identifiable {
    let key: String
    let name: String
    let origin: String
    let year: Int?
    let role: String?
    let params: String
    let diskGB: Double
    let ramGB: Double
    let description: [String: String]
    let mlx: Bool?
    let ollama: String?
    let gguf: String?
    let iberic: Bool?

    var id: String { key }

    enum CodingKeys: String, CodingKey {
        case key, name, origin, year, role, params, description, mlx, ollama, gguf, iberic
        case diskGB = "disk_gb"
        case ramGB  = "ram_gb"
    }

    /// Retorna els engines disponibles per aquest model
    var availableEngines: [String] {
        var engines: [String] = []
        if mlx == true { engines.append("mlx") }
        if ollama != nil { engines.append("ollama") }
        if gguf != nil { engines.append("llama_cpp") }
        return engines
    }

    /// Tria l'engine recomanat (MLX > Ollama > llama_cpp)
    func recommendedEngine(isAppleSilicon: Bool) -> String {
        if isAppleSilicon, mlx == true { return "mlx" }
        if ollama != nil { return "ollama" }
        if gguf != nil { return "llama_cpp" }
        return "ollama"
    }

    /// Descripció localitzada
    func localizedDescription(lang: Lang) -> String {
        return description[lang.rawValue] ?? description["en"] ?? ""
    }

    /// Si el model té capacitat visual (VLM). Derivat de les descripcions
    /// (catàleg actual no porta flag explícit — si es formalitza, canviar aquí).
    var hasVision: Bool {
        let keywords = ["visi", "vision", "visión", "multimod"]
        for desc in description.values {
            let lowered = desc.lowercased()
            for kw in keywords {
                if lowered.contains(kw) { return true }
            }
        }
        return false
    }

    /// Crea un model custom a partir d'un nom d'Ollama
    static func customOllama(_ name: String) -> AIModel {
        return AIModel(
            key: "custom_ollama_\(name)",
            name: name,
            origin: "Ollama",
            year: nil,
            role: "custom",
            params: "—",
            diskGB: 0,
            ramGB: 0,
            description: ["ca": "Model personalitzat", "es": "Modelo personalizado", "en": "Custom model"],
            mlx: false,
            ollama: name,
            gguf: nil,
            iberic: false
        )
    }

    /// Crea un model custom a partir d'un repo de Hugging Face (GGUF)
    static func customHuggingFace(_ repo: String) -> AIModel {
        let shortName = repo.components(separatedBy: "/").last ?? repo
        return AIModel(
            key: "custom_hf_\(repo)",
            name: shortName,
            origin: "Hugging Face",
            year: nil,
            role: "custom",
            params: "—",
            diskGB: 0,
            ramGB: 0,
            description: ["ca": repo, "es": repo, "en": repo],
            mlx: false,
            ollama: nil,
            gguf: repo,
            iberic: false
        )
    }
}

struct ModelCatalog: Codable {
    let tier8: [AIModel]
    let tier16: [AIModel]
    let tier24: [AIModel]
    let tier32: [AIModel]
    let tier48: [AIModel]
    let tier64: [AIModel]

    enum CodingKeys: String, CodingKey {
        case tier8   = "tier_8"
        case tier16  = "tier_16"
        case tier24  = "tier_24"
        case tier32  = "tier_32"
        case tier48  = "tier_48"
        case tier64  = "tier_64"
    }

    /// Carrega el catàleg des del JSON als Resources del bundle
    static func load() -> ModelCatalog {
        let empty = ModelCatalog(tier8: [], tier16: [], tier24: [], tier32: [], tier48: [], tier64: [])

        // Buscar models.json als Resources del bundle
        if let url = Bundle.main.url(forResource: "models", withExtension: "json"),
           let data = try? Data(contentsOf: url),
           let catalog = try? JSONDecoder().decode(ModelCatalog.self, from: data) {
            return catalog
        }

        // Buscar al costat del binary (per desenvolupament)
        let binaryDir = URL(fileURLWithPath: CommandLine.arguments[0]).deletingLastPathComponent()
        let devPath = binaryDir.appendingPathComponent("models.json")
        if let data = try? Data(contentsOf: devPath),
           let catalog = try? JSONDecoder().decode(ModelCatalog.self, from: data) {
            return catalog
        }

        return empty
    }

    /// Tots els models en un array pla
    var allModels: [AIModel] {
        return tier8 + tier16 + tier24 + tier32 + tier48 + tier64
    }

    /// Models d'un tier (claus: "tier_8", "tier_16", ..., "tier_64")
    func models(for tier: String) -> [AIModel] {
        switch tier {
        case "tier_8":   return tier8
        case "tier_16":  return tier16
        case "tier_24":  return tier24
        case "tier_32":  return tier32
        case "tier_48":  return tier48
        case "tier_64":  return tier64
        default:         return []
        }
    }
}
