// ModelCatalog.swift — Catàleg de models carregat des de JSON (generat per export_catalog_json.py)

import Foundation

struct AIModel: Codable, Identifiable {
    let key: String
    let name: String
    let origin: String
    let year: Int?
    let lang: [String: String]
    let params: String
    let diskGB: Double
    let ramGB: Double
    let description: [String: String]
    let mlx: String?
    let ollama: String?
    let gguf: String?
    let chatFormat: String
    let promptTier: String

    var id: String { key }

    enum CodingKeys: String, CodingKey {
        case key, name, origin, year, lang, params, description, mlx, ollama, gguf
        case diskGB = "disk_gb"
        case ramGB = "ram_gb"
        case chatFormat = "chat_format"
        case promptTier = "prompt_tier"
    }

    /// Retorna els engines disponibles per aquest model
    var availableEngines: [String] {
        var engines: [String] = []
        if mlx != nil { engines.append("mlx") }
        if ollama != nil { engines.append("ollama") }
        if gguf != nil { engines.append("llama_cpp") }
        return engines
    }

    /// Tria l'engine recomanat (MLX > Ollama > llama_cpp)
    func recommendedEngine(isAppleSilicon: Bool) -> String {
        if isAppleSilicon, mlx != nil { return "mlx" }
        if ollama != nil { return "ollama" }
        if gguf != nil { return "llama_cpp" }
        return "ollama"
    }

    /// Descripció localitzada
    func localizedDescription(lang: Lang) -> String {
        return description[lang.rawValue] ?? description["en"] ?? ""
    }

    /// Idiomes suportats localitzats
    func localizedLang(lang: Lang) -> String {
        return self.lang[lang.rawValue] ?? self.lang["en"] ?? ""
    }

    /// Crea un model custom a partir d'un nom d'Ollama
    static func customOllama(_ name: String) -> AIModel {
        return AIModel(
            key: "custom_ollama_\(name)",
            name: name,
            origin: "Ollama",
            year: nil,
            lang: ["ca": "Variable", "es": "Variable", "en": "Variable"],
            params: "—",
            diskGB: 0,
            ramGB: 0,
            description: ["ca": "Model personalitzat", "es": "Modelo personalizado", "en": "Custom model"],
            mlx: nil,
            ollama: name,
            gguf: nil,
            chatFormat: "chatml",
            promptTier: "standard"
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
            lang: ["ca": "Variable", "es": "Variable", "en": "Variable"],
            params: "—",
            diskGB: 0,
            ramGB: 0,
            description: ["ca": repo, "es": repo, "en": repo],
            mlx: nil,
            ollama: nil,
            gguf: repo,
            chatFormat: "chatml",
            promptTier: "standard"
        )
    }
}

struct ModelCatalog: Codable {
    let small: [AIModel]
    let medium: [AIModel]
    let large: [AIModel]

    /// Carrega el catàleg des del JSON als Resources del bundle
    static func load() -> ModelCatalog {
        // Buscar models.json als Resources del bundle
        if let url = Bundle.main.url(forResource: "models", withExtension: "json"),
           let data = try? Data(contentsOf: url) {
            let decoder = JSONDecoder()
            if let catalog = try? decoder.decode(ModelCatalog.self, from: data) {
                return catalog
            }
        }

        // Buscar al costat del binary (per desenvolupament)
        let binaryDir = URL(fileURLWithPath: CommandLine.arguments[0]).deletingLastPathComponent()
        let devPath = binaryDir.appendingPathComponent("models.json")
        if let data = try? Data(contentsOf: devPath) {
            let decoder = JSONDecoder()
            if let catalog = try? decoder.decode(ModelCatalog.self, from: data) {
                return catalog
            }
        }

        // Fallback: catàleg buit
        return ModelCatalog(small: [], medium: [], large: [])
    }

    /// Tots els models en un array pla
    var allModels: [AIModel] {
        return small + medium + large
    }

    /// Models d'una categoria
    func models(for size: String) -> [AIModel] {
        switch size {
        case "small": return small
        case "medium": return medium
        case "large": return large
        default: return []
        }
    }
}
