# === METADATA RAG ===
versio: "2.0"
data: 2026-03-28
id: nexe-installation-guide

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Como instalar server-nexe: 3 metodos. (1) DMG para macOS con wizard SwiftUI, Python 3.12 incluido, 15 modelos. (2) CLI: git clone + ./setup.sh (macOS/Linux). (3) Docker con docker-compose y Ollama. Requisitos: macOS 13+ o Linux, 8GB RAM minimo. Backends: MLX (Apple Silicon), llama.cpp, Ollama. Puerto por defecto: 9119."
tags: [installation, setup, dmg, swiftui, wizard, docker, cli, headless, macos, linux, requirements, models, backends, mlx, ollama, llama-cpp, tray, uninstaller, encryption, how-to]
chunk_size: 600
priority: P1

# === OPCIONAL ===
lang: es
type: docs
author: "Jordi Goy"
expires: null
---

# Instalacion — server-nexe 0.9.0 pre-release

Tres metodos de instalacion disponibles. Elige segun tu plataforma y preferencias.

## Requisitos del sistema

| Requisito | Minimo | Recomendado |
|-----------|--------|-------------|
| SO | macOS 12+ / Linux x86_64 | macOS 14+ (Apple Silicon) |
| RAM | 8 GB | 16+ GB |
| Disco | 10 GB libres | 20+ GB (para modelos mas grandes) |
| Python | 3.11+ (metodo CLI) | 3.12 incluido (metodo DMG) |

## Metodo 1: Instalador DMG para macOS (Recomendado)

Wizard nativo SwiftUI con 6 pantallas. Incluye Python 3.12 — sin dependencia del Python del sistema.

### Que hace el wizard

1. **Bienvenida:** Selector de idioma (ca/es/en), logo, info de version
2. **Destino:** Selector de carpeta con validacion de espacio libre
3. **Seleccion de modelo:** 4 pestanas (pequeno/mediano/grande/personalizado) con deteccion de hardware. Muestra 15 modelos con requisitos de RAM, compatibilidad de motor y ano. Recomienda modelos segun la RAM/GPU detectadas.
4. **Confirmacion:** Resumen de las elecciones antes de instalar
5. **Progreso:** Barra de progreso de 7 pasos con log en tiempo real. Parser de protocolo Python ([PROGRESS], [LOG], [DONE], [ERROR]). 8-30 minutos dependiendo de la descarga del modelo.
6. **Finalizacion:** Muestra la API key, opciones para anadir al Dock y a Elementos de Inicio, cuenta atras para el lanzamiento

### Deteccion de hardware

El wizard usa llamadas nativas a `sysctl` para detectar:
- Chip CPU (M1/M2/M3/M4, Intel)
- RAM total
- Soporte de GPU Metal
- Espacio libre en disco

Segun la deteccion, recomienda el backend y modelos apropiados.

### Seleccion de backend

| Backend | Plataforma | Mejor para |
|---------|------------|------------|
| MLX | Solo Apple Silicon | El mas rapido en serie M, GPU Metal + Neural Engine |
| llama.cpp | macOS + Linux | Formato GGUF universal, aceleracion Metal en Mac |
| Ollama | macOS + Linux | Si ya tienes Ollama instalado, la configuracion mas facil |

### Descarga

Descarga el DMG desde la pagina de releases de GitHub: https://github.com/jgoy-labs/server-nexe/releases

## Metodo 2: CLI Headless

Para usuarios que prefieren instalacion por terminal o estan en Linux.

```bash
git clone https://github.com/jgoy-labs/server-nexe
cd server-nexe
./setup.sh
```

`setup.sh` detecta tu plataforma:
- **macOS:** Comprueba Homebrew, Python 3.11+, crea venv, instala requirements.txt + requirements-macos.txt (rumps para bandeja)
- **Linux:** Sugiere paquetes apt/dnf, crea venv, instala solo requirements.txt

Despues del setup:
```bash
./nexe go    # Iniciar servidor -> http://127.0.0.1:9119
```

## Metodo 3: Docker

Para servidores Linux o despliegues en contenedores.

```bash
git clone https://github.com/jgoy-labs/server-nexe
cd server-nexe
docker-compose up
```

- **Dockerfile:** Python 3.12-slim, Qdrant embedded (almacenamiento en `storage/vectors/`), usuario non-root (`nexe`), EXPOSE 9119
- **docker-compose.yml:** Dos servicios — Nexe + Ollama
- **docker-entrypoint.sh:** Arranque secuencial (Qdrant -> esperar health -> Nexe), timeout de 15s con aviso

Montar `storage/` para datos persistentes (modelos, vectores Qdrant, logs).

## Catalogo de modelos (15 modelos)

### Pequenos (8 GB RAM)
| Modelo | Tamano | Motor | Ano |
|--------|--------|-------|-----|
| Qwen3 1.7B | 1.1 GB | Todos | 2025 |
| Qwen3.5 2B | 1.5 GB | Solo Ollama | 2025 |
| Phi-3.5 Mini | 2.4 GB | Todos | 2024 |
| Salamandra 2B | 1.5 GB | Todos | 2024 |
| Qwen3 4B | 2.5 GB | Todos | 2025 |

### Medianos (12-16 GB RAM)
| Modelo | Tamano | Motor | Ano |
|--------|--------|-------|-----|
| Mistral 7B | 4.1 GB | Todos | 2023 |
| Salamandra 7B | 4.9 GB | Todos | 2024 |
| Llama 3.1 8B | 4.7 GB | Todos | 2024 |
| Qwen3 8B | 5.0 GB | Todos | 2025 |
| Gemma 3 12B | 7.6 GB | Todos | 2025 |

### Grandes (32+ GB RAM)
| Modelo | Tamano | Motor | Ano |
|--------|--------|-------|-----|
| Qwen3.5 27B | 17 GB | Solo Ollama | 2025 |
| Qwen3 32B | 20 GB | Todos | 2025 |
| Gemma 3 27B | 17 GB | Todos | 2025 |
| DeepSeek R1 32B | 20 GB | Todos | 2025 |
| Llama 3.1 70B | 40 GB | Todos | 2024 |

Modelos personalizados: Ollama (por nombre) o Hugging Face (URL de repositorio GGUF).

## Verificacion post-instalacion

```bash
curl http://127.0.0.1:9119/health    # Health check
./nexe modules                        # Listar modulos cargados
./nexe chat                           # Probar chat
open http://127.0.0.1:9119/ui        # Web UI
```

## Encriptacion en reposo (opt-in)

Despues de la instalacion, puedes activar la encriptacion en reposo:

```bash
# Activar encriptacion
export NEXE_ENCRYPTION_ENABLED=true

# Comprobar estado actual
./nexe encryption status

# Migrar datos existentes a formato encriptado
./nexe encryption encrypt-all
```

Esto encripta las bases de datos SQLite (via SQLCipher), sesiones de chat (.json -> .enc), y texto de documentos RAG. Consulta SECURITY.md para todos los detalles.

## App de bandeja (macOS)

App de bandeja del sistema con: inicio/parada del servidor, indicador de estado (pulsante durante el arranque), modo oscuro/claro (automatico por hora + toggle manual), enlaces rapidos a la Web UI, acceso al desinstalador, menu multilingue (ca/es/en), Ollama se abre en segundo plano.

## Desinstalador

Accesible desde el menu de la bandeja. Doble confirmacion, calcula espacio, elimina elementos del Dock/Inicio, backup de storage/ con timestamp, NO elimina la carpeta.

## Resolucion de problemas

| Problema | Solucion |
|----------|----------|
| Puerto 9119 en uso | `lsof -i :9119` luego matar, o cambiar en server.toml |
| Qdrant no arranca | Verifica que `storage/vectors/` es escribible y no tiene lock files (`*.lock`). Reinicia el servidor. |
| Ollama no encontrado | Instalar desde ollama.com, o usar MLX/llama.cpp |
| Error de version de Python | Requiere 3.11+. El DMG incluye 3.12. |
| MLX no disponible | Solo Apple Silicon. Usar llama.cpp u Ollama. |
| Descarga de modelo lenta | Los modelos grandes tardan 30+ min. Timeout 600s. |
| OOM killed | Elegir modelo mas pequeno. 8GB -> modelos 2B. |

## Variables de entorno clave

| Variable | Proposito | Por defecto |
|----------|-----------|-------------|
| NEXE_PRIMARY_API_KEY | API key principal | (generada) |
| NEXE_MODEL_ENGINE | Backend por defecto | auto |
| NEXE_OLLAMA_MODEL | Modelo Ollama | (seleccionado durante la instalacion) |
| NEXE_LLAMA_CPP_MODEL | Ruta del modelo GGUF | storage/models/*.gguf |
| NEXE_DEFAULT_MAX_TOKENS | Tokens maximos de respuesta | 4096 |
| NEXE_LANG | Idioma del servidor | ca |
| NEXE_ENV | Entorno | production |
| NEXE_ENCRYPTION_ENABLED | Activar encriptacion en reposo | false |
