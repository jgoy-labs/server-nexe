# === METADATA RAG ===
versio: "2.0"
data: 2026-04-02
id: nexe-usage-guide

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Com fer servir server-nexe: CLI (nexe go, nexe chat, nexe memory, nexe knowledge, nexe status), Web UI (http://localhost:9119), memoria automatica MEM_SAVE, pujada de documents PDF/TXT, comandes d'encriptacio. Exemples d'API amb curl i Python. Com instal-lar models, com canviar d'idioma (NEXE_LANG), com gestionar la memoria."
tags: [usage, cli, web-ui, chat, memory, knowledge, upload, i18n, loading-indicator, mem-save, api-examples, use-cases, encryption, how-to, commands]
chunk_size: 600
priority: P1

# === OPCIONAL ===
lang: ca
type: docs
author: "Jordi Goy"
expires: null
---

# Guia d'us — server-nexe 0.9.0 pre-release

## Arrencar el servidor

```bash
./nexe go    # Arrencar servidor -> http://127.0.0.1:9119
```

A macOS amb l'app de safata instal·lada, el servidor arrenca automaticament en iniciar sessio.

## Comandes CLI

| Comanda | Descripcio |
|---------|-------------|
| `./nexe go` | Arrencar servidor (Qdrant + FastAPI + safata) |
| `./nexe chat` | Xat interactiu per CLI |
| `./nexe chat --rag` | Xat amb memoria RAG activada |
| `./nexe chat --verbose` | Xat amb detall de pesos RAG per font |
| `./nexe status` | Estat del servidor |
| `./nexe modules` | Llistar moduls carregats i CLIs |
| `./nexe memory store "text"` | Guardar text a memoria |
| `./nexe memory recall "query"` | Cercar a memoria |
| `./nexe memory stats` | Estadistiques de memoria |
| `./nexe knowledge ingest` | Indexar documents de la carpeta knowledge/ |
| `./nexe health` | Health check |
| `./nexe encryption status` | Comprovar estat d'encriptacio |
| `./nexe encryption encrypt-all` | Migrar dades a format encriptat |
| `./nexe encryption export-key` | Exportar clau mestra per a copia de seguretat |

## Web UI

Acces a `http://127.0.0.1:9119/ui`. Requereix clau API (guardada a localStorage despres del primer login).

### Funcionalitats

- **Xat amb streaming:** Streaming de tokens en temps real amb tots 3 backends
- **Indicador de carrega de model:** Spinner blau amb cronometre quan es canvia de model. Transiciona a "Model carregat (Xs)" verd permanent a la conversa.
- **Mides de models al dropdown:** Mostra GB al costat de cada nom de model (Ollama via /api/tags, MLX via safetensors, llama.cpp via mida del fitxer gguf)
- **Panell d'informacio RAG:** Boto de toggle al costat del slider de llindar. Mostra explicacio de que fa el filtre RAG.
- **Barres de pes RAG:** Puntuacions de rellevancia amb codi de colors (verd > 0.7, groc 0.4-0.7, taronja < 0.4). Expandibles per mostrar fonts individuals.
- **Slider de llindar:** Ajusta el llindar de similitud RAG en temps real. Etiquetes: "Mes info" (llindar baix) / "Filtre alt" (llindar alt).
- **Selector d'idioma:** Dropdown al peu CA/ES/EN. Canvia tot el text de la UI instantaniament via `applyI18n()`. El servidor es la font de veritat (POST /ui/lang).
- **Dropdown de backend:** Mostra tots els backends configurats. Marca els backends desconnectats. Auto-fallback al primer backend disponible si el seleccionat cau.
- **Thinking tokens:** Auto-scroll de la caixa de pensament per a models com qwen3.5 que emeten thinking tokens.
- **Overlay de pujada:** Spinner + temporitzador + nom de fitxer durant la pujada de documents. Input bloquejat fins a completar. Mostra recompte de chunks i temps despres de completar.
- **Persistencia de sessio:** Clau API i preferencies a localStorage. Les sessions sobreviuen al recarregar la pagina.
- **Auto-scroll:** El xat i les caixes de pensament fan auto-scroll cap avall durant el streaming.
- **Sidebar col·lapsable:** Toggle amb icona panel-left, estat persistent a localStorage. (nou 2026-04-01)
- **Rename sessions:** Boto llapis per renombrar sessions inline via PATCH endpoint. (nou 2026-04-01)
- **Boto copiar text:** Copia respostes al porta-retalls amb feedback visual copy/check. (nou 2026-04-01)
- **Toggles de col·leccions:** Checkboxes a la sidebar per activar/desactivar Memory/Knowledge/Docs individualment. Persistent a localStorage. CLI: `--collections`. (nou 2026-04-01)
- **Pantalla de benvinguda:** Features clicables ("Conversa" foca input, "Documents" obre upload). (nou 2026-04-02)
- **Bloc MEM_SAVE blau:** Les memories guardades es mostren com a `<details>` blau col·lapsable (com thinking taronja). (nou 2026-04-01)
- **Avis de document truncat:** Notificacio groc quan un document es massa gran pel context. (nou 2026-04-02)
- **Mode clar/fosc automatic:** Detecta preferencia del sistema via `matchMedia`. (existent)

### Pujada de documents

Puja documents via el boto del clip a l'entrada del xat. Suportats: .txt, .md, .pdf.

- Documents indexats a la col·leccio `user_knowledge` amb session_id
- Nomes visibles dins la sessio de pujada (sense contaminacio entre sessions)
- Metadades generades sense LLM (instantani, sense bloqueig del model)
- Mostra el missatge "Carregat (N fragments, Xs)" despres de completar
- Documents marcats "per-xat" per indicar l'aillament de sessio

## MEM_SAVE — Memoria automatica

El model extreu i guarda automaticament fets de les converses:

- L'usuari diu "Em dic Jordi" -> el model guarda `[MEM_SAVE: name=Jordi]`
- L'usuari diu "Oblida el meu nom" -> MEM_DELETE: cerca per similitud (threshold 0.70), esborra la coincidencia mes propera, guard anti-re-save
- Propera conversa: "Com em dic?" -> RAG recupera "name=Jordi" -> el model respon correctament

No calen comandes extra. Funciona tant al CLI com a la Web UI. Indicadors: el badge `[MEM:N]` mostra el recompte de fets guardats.

## Encriptacio

L'encriptacio at-rest es opt-in. Activa-la per encriptar les teves dades emmagatzemades:

```bash
# Comprovar estat actual
./nexe encryption status

# Activar i migrar dades existents
export NEXE_ENCRYPTION_ENABLED=true
./nexe encryption encrypt-all

# Exportar clau mestra (per a copia de seguretat — guarda-la de forma segura!)
./nexe encryption export-key
```

Que s'encripta: bases de dades SQLite (memories.db via SQLCipher), sessions de xat (.json -> .enc), text de documents RAG (TextStore). Els payloads de Qdrant ja no contenen text (nomes vectors + IDs).

## Us de l'API

### Xat (curl)
```bash
curl -X POST http://127.0.0.1:9119/v1/chat/completions \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hello"}], "use_rag": true}'
```

### Xat (Python)
```python
import requests

response = requests.post(
    "http://127.0.0.1:9119/v1/chat/completions",
    headers={"X-API-Key": "YOUR_KEY"},
    json={"messages": [{"role": "user", "content": "Hello"}], "use_rag": True}
)
print(response.json()["choices"][0]["message"]["content"])
```

### Guardar a memoria
```bash
curl -X POST http://127.0.0.1:9119/v1/memory/store \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"text": "Project deadline is March 30", "collection": "user_knowledge"}'
```

## Casos d'us practics

1. **Assistent personal amb memoria:** Pregunta sobre els teus projectes, preferencies, terminis. MEM_SAVE recorda el context automaticament.
2. **Base de coneixement privada:** Puja documents tecnics, consulta'ls en llenguatge natural. Aillament per sessio per conversa.
3. **Desenvolupament assistit per IA:** L'API compatible amb OpenAI funciona amb Cursor, Continue, Zed. Apunta'ls a http://127.0.0.1:9119/v1.
4. **Cerca semantica:** Utilitza /v1/memory/search per a recuperacio de documents basada en similitud sense necessitat de coincidencia exacta de paraules clau.
5. **Experimentacio amb models:** Canvia entre backends MLX, llama.cpp i Ollama per comparar velocitat i qualitat.
6. **IA local segura:** Activa l'encriptacio at-rest per a gestionar dades sensibles sense cap dependencia del nuvol.

## Consells

- **Primera execucio:** La memoria esta buida. Parla amb el servidor, puja docs o utilitza `nexe knowledge ingest` per poblar el RAG.
- **Primera resposta lenta:** La carrega del model triga (10-60s). L'indicador de carrega mostra el progres.
- **Backend desconnectat:** El servidor fa auto-fallback al primer backend disponible. Comprova amb `./nexe status`.
- **Models grans:** Els models de 32B+ necessiten 32+ GB de RAM i poden trigar minuts a carregar. El timeout es de 600s.
- **Encriptacio:** Activa l'encriptacio aviat — migrar conjunts de dades grans mes tard triga temps. Exporta i guarda la clau mestra de forma segura.
