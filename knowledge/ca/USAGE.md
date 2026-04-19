# === METADATA RAG ===
versio: "2.0"
data: 2026-04-16
id: nexe-usage-guide
collection: nexe_documentation

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Com fer servir server-nexe 1.0.1-beta: CLI (nexe go, nexe chat, nexe memory, nexe knowledge, nexe status), Web UI (http://localhost:9119) amb thinking toggle, memoria automatica MEM_SAVE, MEM_DELETE (threshold 0.20) amb confirmacio clear_all 2-torns, pujada de documents PDF/TXT, comandes d'encriptacio. Exemples d'API amb curl i Python. Com instal-lar models, com canviar d'idioma (NEXE_LANG), com gestionar la memoria."
tags: [usage, cli, web-ui, chat, memory, knowledge, upload, i18n, loading-indicator, mem-save, api-examples, use-cases, encryption, how-to, commands]
chunk_size: 600
priority: P1

# === OPCIONAL ===
lang: ca
type: docs
author: "Jordi Goy with AI collaboration"
expires: null
---

# Guia d'us — server-nexe 1.0.1-beta

## Taula de continguts

- [Arrencar el servidor](#arrencar-el-servidor)
- [Comandes CLI](#comandes-cli)
- [Web UI](#web-ui)
  - [Funcionalitats](#funcionalitats)
  - [Pujada de documents](#pujada-de-documents)
- [MEM_SAVE — Memoria automatica](#mem_save--memoria-automatica)
  - [Esborrat total (`CLEAR_ALL`) — confirmació 2-torns](#esborrat-total-clear_all--confirmació-2-torns)
- [Encriptacio](#encriptacio)
- [Us de l'API](#us-de-lapi)
  - [Xat (curl)](#xat-curl)
  - [Xat (Python)](#xat-python)
  - [Guardar a memoria](#guardar-a-memoria)
- [Casos d'us](#casos-dus)
- [Consells](#consells)

## En 30 segons

- **CLI:** `./nexe go` arrenca servidor + Qdrant + tray
- **Web UI** a `http://127.0.0.1:9119/ui` (xat, pujada docs, sessions)
- **API OpenAI-compatible:** `/v1/chat/completions`
- **MEM_SAVE automatic** (el model guarda fets de la conversa)
- **Menu al system tray** per start/stop, logs, uninstall

---

## Icona de Nexe a la barra de menú (tray)

La icona de Nexe apareix al costat del rellotge (barra de menú de macOS). Permet controlar el servidor sense obrir cap terminal.

**Opcions del menú:**

| Opció | Què fa |
|-------|--------|
| Aturar / Iniciar servidor | Engega o atura Nexe amb un clic |
| Obrir Web UI | Obre el xat al navegador (`http://127.0.0.1:9119/ui`) |
| Obrir logs | Mostra el fitxer de logs per si hi ha errors |
| Server RAM | Mostra quanta memòria usa el model carregat |
| Temps actiu | Quan de temps porta el servidor en marxa |
| Documentació | Obre la documentació oficial |
| Configuració → Desinstal·lar Nexe | Elimina Nexe amb còpia de seguretat automàtica |
| Sortir | Atura el servidor i tanca la icona del tray |

La icona és **verda** quan el servidor és actiu i **grisa** quan és aturat. Es refresca cada 5 segons.

---

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
- **Thinking toggle per sessio (v0.9.9):** Icona ✨ sparkles al costat de l'input + dropdown 🧠 al capçal de la sessió per activar/desactivar el mode thinking (reasoning tokens) per aquesta sessió. Només disponible per famílies compatibles (`THINKING_CAPABLE`: qwen3.5, qwen3, qwq, deepseek-r1, gemma3/4, llama4, gpt-oss). Default OFF. Si el model actual no suporta thinking, la UI mostra missatge d'avís i ofereix retry automàtic sense thinking. Endpoint intern: `PATCH /ui/session/{id}/thinking`.
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
- L'usuari diu "Oblida el meu nom" -> MEM_DELETE: cerca per similitud (**threshold 0.20** des de v0.9.9, abans 0.70), esborra la coincidencia mes propera, guard anti-re-save
- Propera conversa: "Com em dic?" -> RAG recupera "name=Jordi" -> el model respon correctament

No calen comandes extra. Funciona tant al CLI com a la Web UI. Indicadors: el badge `[MEM:N]` mostra el recompte de fets guardats.

### Esborrat total (`CLEAR_ALL`) — confirmació 2-torns

Si demanes esborrar **tota** la memòria ("esborra-ho tot", "forget everything", "olvida todo"), el sistema **no esborra immediatament**. Segueix un flux de 2 torns:

1. **Torn 1:** Detecta el patró i demana confirmació ("Estàs segur? Això esborrarà tota la memòria. Respon 'sí' per confirmar.").
2. **Torn 2:** Si respons `sí`/`confirma`/`ok`, s'executa l'esborrat. Qualsevol altra resposta cancel·la l'operació.

Aixo evita pèrdues massives accidentals per un missatge ambigu o per injecció des d'un document.

## Encriptacio

L'encriptacio at-rest es `auto` per defecte — s'activa automaticament si `sqlcipher3` esta disponible. Per forcar-la o gestionar-la manualment:

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

## Casos d'us

Consulta **[[USE_CASES|casos d'us practics]]** per a la llista completa amb context detallat (assistent personal, base de coneixement privada, dev amb Cursor/Continue/Zed, cerca semantica, experimentacio amb models, IA local segura) i guia de **quan server-nexe NO es la millor eina**.

## Consells

- **Primera execucio:** La memoria esta buida. Parla amb el servidor, puja docs o utilitza `nexe knowledge ingest` per poblar el RAG.
- **Primera resposta lenta:** La carrega del model triga (10-60s). L'indicador de carrega mostra el progres.
- **Backend desconnectat:** El servidor fa auto-fallback al primer backend disponible. Comprova amb `./nexe status`.
- **Models grans:** Els models de 32B+ necessiten 32+ GB de RAM i poden trigar minuts a carregar. El timeout es de 600s.
- **Encriptacio:** Activa l'encriptacio aviat — migrar conjunts de dades grans mes tard triga temps. Exporta i guarda la clau mestra de forma segura.
