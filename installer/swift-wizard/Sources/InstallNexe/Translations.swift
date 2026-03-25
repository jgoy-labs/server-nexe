// Translations.swift — Strings multiidioma (ca/es/en)

import Foundation

enum Lang: String, CaseIterable {
    case ca, es, en

    var displayName: String {
        switch self {
        case .ca: return "Catala"
        case .es: return "Espanol"
        case .en: return "English"
        }
    }

    /// Detecta l'idioma del sistema (ca/es/en, default en)
    static func fromSystem() -> Lang {
        let preferred = Locale.preferredLanguages.first ?? "en"
        let code = String(preferred.prefix(2))
        return Lang(rawValue: code) ?? .en
    }
}

// MARK: - Claus de traducció

struct T {
    static func get(_ key: String, lang: Lang) -> String {
        return translations[lang]?[key] ?? translations[.en]?[key] ?? key
    }

    static let translations: [Lang: [String: String]] = [
        .ca: [
            // Welcome
            "welcome_title": "Benvingut a Nexe",
            "welcome_subtitle": "La teva IA privada, local i segura",
            "welcome_desc": "Nexe instal·lara un servidor d'intel·ligencia artificial al teu Mac. Tot funciona localment — les teves dades mai surten del teu ordinador.",
            "welcome_features_1": "Models d'IA locals (sense connexio a internet)",
            "welcome_features_2": "Base de coneixement amb memoria RAG",
            "welcome_features_3": "Interficie web integrada",
            "btn_start": "Comenca",
            "btn_next": "Seguent",
            "btn_back": "Enrere",
            "btn_install": "Instal·lar",
            "btn_close": "Tancar",
            "btn_cancel": "Cancel·lar",
            "cancel_confirm": "Segur que vols cancel·lar la instal·lacio?",
            "cancel_title": "Instal·lacio en curs",
            "cancel_message": "S'esta instal·lant server-nexe. Si tanques ara, la instal·lacio quedara incompleta.",
            "cancel_continue": "Continuar",
            "cancel_quit": "Sortir",
            "btn_open_nexe": "Obrir Nexe",
            "btn_copy": "Copiar",
            "btn_copied": "Copiat!",

            // Destination
            "dest_title": "Carpeta d'instal·lacio",
            "dest_desc": "Tria on vols instal·lar server-nexe. Es creara una carpeta 'server-nexe' al lloc que triis.",
            "dest_choose": "Triar carpeta...",
            "dest_free_space": "Espai lliure",
            "dest_required": "Espai necessari (aprox.)",
            "dest_warning_space": "No hi ha prou espai lliure al disc seleccionat",

            // Model picker
            "model_title": "Tria el teu model d'IA",
            "model_desc": "Selecciona un model segons les capacitats del teu hardware.",
            "model_hw_ram": "RAM",
            "model_hw_chip": "Processador",
            "model_hw_metal": "GPU Metal",
            "model_hw_disk": "Disc lliure",
            "model_tab_small": "Petits",
            "model_tab_medium": "Mitjans",
            "model_tab_large": "Grans",
            "model_engine": "Motor",
            "model_engine_auto": "Automatic (recomanat)",
            "model_disk": "Disc",
            "model_ram": "RAM",
            "model_params": "Parametres",
            "model_recommended": "Recomanat",
            "model_too_large": "Massa gran",
            "model_warning_ram": "Aquest model necessita mes RAM de la disponible",
            "model_tab_custom": "Personalitzat",
            "model_custom_desc": "Escriu el nom d'un model d'Ollama o un repo de Hugging Face (GGUF).",
            "model_custom_ollama_label": "Model Ollama",
            "model_custom_ollama_hint": "Ex: llama3:8b, gemma2:9b, qwen2:7b",
            "model_custom_hf_label": "Repo Hugging Face (GGUF)",
            "model_custom_hf_hint": "Ex: TheBloke/Llama-2-7B-GGUF",
            "model_custom_warning": "Assegura't que el model existeix i es compatible amb el teu hardware.",

            // Confirm
            "confirm_title": "Resum de la instal·lacio",
            "confirm_desc": "Es descarregaran els seguents components. Necessitaras connexio a internet.",
            "confirm_model_desc": "Model d'intel·ligencia artificial",
            "confirm_deps_desc": "Llibreries Python necessaries",
            "confirm_qdrant_desc": "Base de dades vectorial per memoria RAG",
            "confirm_embeddings_desc": "Model de cerca semantica",
            "confirm_quarantine": "macOS pot bloquejar alguns fitxers descarregats (quarantena). L'instal·lador eliminara la quarantena automaticament per als components necessaris (Qdrant).",

            // Progress
            "progress_title": "Instal·lant Nexe",
            "progress_step_venv": "Creant entorn virtual",
            "progress_step_deps": "Instal·lant dependencies",
            "progress_step_model": "Descarregant model d'IA",
            "progress_step_config": "Generant configuracio",
            "progress_step_qdrant": "Descarregant Qdrant",
            "progress_step_embeddings": "Descarregant embeddings",
            "progress_step_knowledge": "Processant base de coneixement",
            "progress_log": "Registre",
            "progress_error": "Error durant la instal·lacio",

            // Completion
            "done_title": "Instal·lacio completada!",
            "done_desc": "Nexe s'ha instal·lat correctament. Guarda la clau API — la necessitaras per accedir a la Web UI.",
            "done_partial_warning": "El model no s'ha pogut descarregar. Pots descarregar-lo mes tard des de la Web UI o amb: nexe model download",
            "done_api_key": "Clau API",
            "done_open_desc": "Nexe s'ha copiat a Aplicacions. Obre'l per iniciar el servidor.",
            "done_dock": "Afegir Nexe al Dock",
            "done_login_item": "Obrir Nexe al iniciar el Mac",
            "done_menubar_info": "S'ha afegit una icona a la barra de menus (a dalt a la dreta) per controlar el servidor.",
            "btn_opened": "Nexe obert!",
        ],
        .es: [
            "welcome_title": "Bienvenido a Nexe",
            "welcome_subtitle": "Tu IA privada, local y segura",
            "welcome_desc": "Nexe instalara un servidor de inteligencia artificial en tu Mac. Todo funciona localmente — tus datos nunca salen de tu ordenador.",
            "welcome_features_1": "Modelos de IA locales (sin conexion a internet)",
            "welcome_features_2": "Base de conocimiento con memoria RAG",
            "welcome_features_3": "Interfaz web integrada",
            "btn_start": "Empezar",
            "btn_next": "Siguiente",
            "btn_back": "Atras",
            "btn_install": "Instalar",
            "btn_close": "Cerrar",
            "btn_cancel": "Cancelar",
            "cancel_confirm": "Seguro que quieres cancelar la instalacion?",
            "cancel_title": "Instalacion en curso",
            "cancel_message": "Se esta instalando server-nexe. Si cierras ahora, la instalacion quedara incompleta.",
            "cancel_continue": "Continuar",
            "cancel_quit": "Salir",
            "btn_open_nexe": "Abrir Nexe",
            "btn_copy": "Copiar",
            "btn_copied": "Copiado!",

            "dest_title": "Carpeta de instalacion",
            "dest_desc": "Elige donde quieres instalar server-nexe. Se creara una carpeta 'server-nexe' en el lugar que elijas.",
            "dest_choose": "Elegir carpeta...",
            "dest_free_space": "Espacio libre",
            "dest_required": "Espacio necesario (aprox.)",
            "dest_warning_space": "No hay suficiente espacio libre en el disco seleccionado",

            "model_title": "Elige tu modelo de IA",
            "model_desc": "Selecciona un modelo segun las capacidades de tu hardware.",
            "model_hw_ram": "RAM",
            "model_hw_chip": "Procesador",
            "model_hw_metal": "GPU Metal",
            "model_hw_disk": "Disco libre",
            "model_tab_small": "Pequenos",
            "model_tab_medium": "Medianos",
            "model_tab_large": "Grandes",
            "model_engine": "Motor",
            "model_engine_auto": "Automatico (recomendado)",
            "model_disk": "Disco",
            "model_ram": "RAM",
            "model_params": "Parametros",
            "model_recommended": "Recomendado",
            "model_too_large": "Demasiado grande",
            "model_warning_ram": "Este modelo necesita mas RAM de la disponible",
            "model_tab_custom": "Personalizado",
            "model_custom_desc": "Escribe el nombre de un modelo de Ollama o un repo de Hugging Face (GGUF).",
            "model_custom_ollama_label": "Modelo Ollama",
            "model_custom_ollama_hint": "Ej: llama3:8b, gemma2:9b, qwen2:7b",
            "model_custom_hf_label": "Repo Hugging Face (GGUF)",
            "model_custom_hf_hint": "Ej: TheBloke/Llama-2-7B-GGUF",
            "model_custom_warning": "Asegurate de que el modelo existe y es compatible con tu hardware.",

            "confirm_title": "Resumen de la instalacion",
            "confirm_desc": "Se descargaran los siguientes componentes. Necesitaras conexion a internet.",
            "confirm_model_desc": "Modelo de inteligencia artificial",
            "confirm_deps_desc": "Librerias Python necesarias",
            "confirm_qdrant_desc": "Base de datos vectorial para memoria RAG",
            "confirm_embeddings_desc": "Modelo de busqueda semantica",
            "confirm_quarantine": "macOS puede bloquear algunos archivos descargados (cuarentena). El instalador eliminara la cuarentena automaticamente para los componentes necesarios (Qdrant).",

            "progress_title": "Instalando Nexe",
            "progress_step_venv": "Creando entorno virtual",
            "progress_step_deps": "Instalando dependencias",
            "progress_step_model": "Descargando modelo de IA",
            "progress_step_config": "Generando configuracion",
            "progress_step_qdrant": "Descargando Qdrant",
            "progress_step_embeddings": "Descargando embeddings",
            "progress_step_knowledge": "Procesando base de conocimiento",
            "progress_log": "Registro",
            "progress_error": "Error durante la instalacion",

            "done_title": "Instalacion completada!",
            "done_desc": "Nexe se ha instalado correctamente. Guarda la clave API — la necesitaras para acceder a la Web UI.",
            "done_partial_warning": "El modelo no se pudo descargar. Puedes descargarlo mas tarde desde la Web UI o con: nexe model download",
            "done_api_key": "Clave API",
            "done_open_desc": "Nexe se ha copiado a Aplicaciones. Abrelo para iniciar el servidor.",
            "done_dock": "Anadir Nexe al Dock",
            "done_login_item": "Abrir Nexe al iniciar el Mac",
            "done_menubar_info": "Se ha anadido un icono en la barra de menus (arriba a la derecha) para controlar el servidor.",
            "btn_opened": "Nexe abierto!",
        ],
        .en: [
            "welcome_title": "Welcome to Nexe",
            "welcome_subtitle": "Your private, local and secure AI",
            "welcome_desc": "Nexe will install an artificial intelligence server on your Mac. Everything runs locally — your data never leaves your computer.",
            "welcome_features_1": "Local AI models (no internet connection needed)",
            "welcome_features_2": "Knowledge base with RAG memory",
            "welcome_features_3": "Integrated web interface",
            "btn_start": "Get Started",
            "btn_next": "Next",
            "btn_back": "Back",
            "btn_install": "Install",
            "btn_close": "Close",
            "btn_cancel": "Cancel",
            "cancel_confirm": "Are you sure you want to cancel the installation?",
            "cancel_title": "Installation in progress",
            "cancel_message": "server-nexe is being installed. If you close now, the installation will be incomplete.",
            "cancel_continue": "Continue",
            "cancel_quit": "Quit",
            "btn_open_nexe": "Open Nexe",
            "btn_copy": "Copy",
            "btn_copied": "Copied!",

            "dest_title": "Installation Folder",
            "dest_desc": "Choose where to install server-nexe. A 'server-nexe' folder will be created at the location you choose.",
            "dest_choose": "Choose folder...",
            "dest_free_space": "Free space",
            "dest_required": "Required space (approx.)",
            "dest_warning_space": "Not enough free space on the selected disk",

            "model_title": "Choose your AI model",
            "model_desc": "Select a model based on your hardware capabilities.",
            "model_hw_ram": "RAM",
            "model_hw_chip": "Processor",
            "model_hw_metal": "Metal GPU",
            "model_hw_disk": "Free disk",
            "model_tab_small": "Small",
            "model_tab_medium": "Medium",
            "model_tab_large": "Large",
            "model_engine": "Engine",
            "model_engine_auto": "Automatic (recommended)",
            "model_disk": "Disk",
            "model_ram": "RAM",
            "model_params": "Parameters",
            "model_recommended": "Recommended",
            "model_too_large": "Too large",
            "model_warning_ram": "This model needs more RAM than available",
            "model_tab_custom": "Custom",
            "model_custom_desc": "Enter an Ollama model name or a Hugging Face repo (GGUF).",
            "model_custom_ollama_label": "Ollama Model",
            "model_custom_ollama_hint": "E.g.: llama3:8b, gemma2:9b, qwen2:7b",
            "model_custom_hf_label": "Hugging Face Repo (GGUF)",
            "model_custom_hf_hint": "E.g.: TheBloke/Llama-2-7B-GGUF",
            "model_custom_warning": "Make sure the model exists and is compatible with your hardware.",

            "confirm_title": "Installation summary",
            "confirm_desc": "The following components will be downloaded. You'll need an internet connection.",
            "confirm_model_desc": "Artificial intelligence model",
            "confirm_deps_desc": "Required Python libraries",
            "confirm_qdrant_desc": "Vector database for RAG memory",
            "confirm_embeddings_desc": "Semantic search model",
            "confirm_quarantine": "macOS may block some downloaded files (quarantine). The installer will automatically remove quarantine for required components (Qdrant).",

            "progress_title": "Installing Nexe",
            "progress_step_venv": "Creating virtual environment",
            "progress_step_deps": "Installing dependencies",
            "progress_step_model": "Downloading AI model",
            "progress_step_config": "Generating configuration",
            "progress_step_qdrant": "Downloading Qdrant",
            "progress_step_embeddings": "Downloading embeddings",
            "progress_step_knowledge": "Processing knowledge base",
            "progress_log": "Log",
            "progress_error": "Error during installation",

            "done_title": "Installation complete!",
            "done_desc": "Nexe has been installed successfully. Save the API key — you'll need it to access the Web UI.",
            "done_partial_warning": "Model download failed. You can download it later from the Web UI or with: nexe model download",
            "done_api_key": "API Key",
            "done_open_desc": "Nexe has been copied to Applications. Open it to start the server.",
            "done_dock": "Add Nexe to Dock",
            "done_login_item": "Open Nexe at Mac startup",
            "done_menubar_info": "A menu bar icon has been added (top right) to control the server.",
            "btn_opened": "Nexe opened!",
        ],
    ]
}
