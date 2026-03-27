# === METADATA RAG ===
versio: "1.1"
data: 2026-03-27
id: nexe-usage-guide

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Guia d'ús de server-nexe 0.8.2. Cobreix comandes CLI (go, chat, memory, knowledge, status), funcionalitats de la Web UI (selector i18n, indicador de càrrega, panell d'informació RAG, mides de models, overlay de pujada, fallback de backend), memòria automàtica MEM_SAVE, pujada de documents amb aïllament de sessió, exemples d'ús de l'API (curl, Python) i casos d'ús pràctics."
tags: [ús, cli, web-ui, chat, memòria, coneixement, pujada, i18n, indicador-càrrega, mem-save, exemples-api, casos-ús]
chunk_size: 800
priority: P1

# === OPCIONAL ===
lang: ca
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# Guia d'ús — server-nexe 0.8.2

## Iniciar el servidor

```bash
./nexe go    # Inicia el servidor → http://127.0.0.1:9119
```

A macOS amb la tray app instal·lada, el servidor s'inicia automàticament en fer login.

## Comandes CLI

| Comanda | Descripció |
|---------|------------|
| `./nexe go` | Inicia el servidor (Qdrant + FastAPI + tray) |
| `./nexe chat` | Xat interactiu per CLI |
| `./nexe chat --rag` | Xat amb memòria RAG activada |
| `./nexe chat --verbose` | Xat amb detalls de pesos RAG per font |
| `./nexe status` | Estat del servidor |
| `./nexe modules` | Llista mòduls i CLIs carregats |
| `./nexe memory store "text"` | Desa text a la memòria |
| `./nexe memory recall "query"` | Cerca a la memòria |
| `./nexe memory stats` | Estadístiques de memòria |
| `./nexe knowledge ingest` | Indexa documents de la carpeta knowledge/ |
| `./nexe health` | Health check |

## Web UI

Accés a `http://127.0.0.1:9119/ui`. Requereix API key (desada a localStorage després del primer login).

### Funcionalitats

- **Xat amb streaming:** Streaming de tokens en temps real amb els 3 backends
- **Indicador de càrrega de model:** Spinner blau amb cronòmetre en canviar de model. Transiciona a "Model carregat (Xs)" verd permanentment a la conversa.
- **Mides de models al desplegable:** Mostra GB al costat de cada nom de model (Ollama via /api/tags, MLX via safetensors, llama.cpp via mida del fitxer gguf)
- **Panell d'informació RAG:** Botó de commutació al costat del slider de llindar. Mostra explicació del que fa el filtre RAG.
- **Barres de pes RAG:** Puntuacions de rellevància amb codi de colors (verd > 0.7, groc 0.4-0.7, taronja < 0.4). Expandible per mostrar fonts individuals.
- **Slider de llindar:** Ajusta el llindar de similitud RAG en temps real. Etiquetes: "Més info" (llindar baix) / "Filtre alt" (llindar alt).
- **Selector d'idioma:** Desplegable al peu CA/ES/EN. Canvia tot el text de la UI instantàniament via `applyI18n()`. El servidor és la font de veritat (POST /ui/lang).
- **Desplegable de backend:** Mostra tots els backends configurats. Marca backends desconnectats. Fallback automàtic al primer backend disponible si el seleccionat no respon.
- **Tokens de pensament:** Auto-scroll de la caixa de pensament per a models com qwen3.5 que emeten tokens de pensament.
- **Overlay de pujada:** Spinner + temporitzador + nom del fitxer durant la pujada de documents. Entrada bloquejada fins a completar. Mostra recompte de fragments i temps després de completar.
- **Persistència de sessió:** API key i preferències a localStorage. Les sessions sobreviuen a recarregar la pàgina.
- **Auto-scroll:** Les caixes de xat i pensament fan auto-scroll al final durant l'streaming.

### Pujada de documents

Puja documents via el botó de clip a l'entrada del xat. Suportats: .txt, .md, .pdf.

- Documents indexats a la col·lecció `user_knowledge` amb session_id
- Només visibles dins la sessió que els ha pujat (sense contaminació entre sessions)
- Metadata generada sense LLM (instantani, sense bloqueig de model)
- Mostra "Carregat (N fragments, Xs)" després de completar
- Documents marcats "per-chat" per indicar aïllament de sessió

## MEM_SAVE — Memòria automàtica

El model extreu i desa automàticament fets de les converses:

- L'usuari diu "Em dic Jordi" → el model desa `[MEM_SAVE: name=Jordi]`
- L'usuari diu "Oblida el meu nom" → el model esborra l'entrada de memòria corresponent
- Propera conversa: "Com em dic?" → RAG recupera "name=Jordi" → el model respon correctament

No calen comandes extra. Funciona tant al CLI com a la Web UI. Indicadors: badge `[MEM:N]` mostra el recompte de fets desats.

## Ús de l'API

### Xat (curl)
```bash
curl -X POST http://127.0.0.1:9119/v1/chat/completions \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hola"}], "use_rag": true}'
```

### Xat (Python)
```python
import requests

response = requests.post(
    "http://127.0.0.1:9119/v1/chat/completions",
    headers={"X-API-Key": "YOUR_KEY"},
    json={"messages": [{"role": "user", "content": "Hola"}], "use_rag": True}
)
print(response.json()["choices"][0]["message"]["content"])
```

### Desar a memòria
```bash
curl -X POST http://127.0.0.1:9119/v1/memory/store \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"text": "La data límit del projecte és el 30 de març", "collection": "user_knowledge"}'
```

## Casos d'ús pràctics

1. **Assistent personal amb memòria:** Pregunta sobre els teus projectes, preferències, dates límit. MEM_SAVE recorda context automàticament.
2. **Base de coneixement privada:** Puja documents tècnics, consulta'ls en llenguatge natural. Aïllat per sessió per conversa.
3. **Desenvolupament assistit per IA:** L'API compatible amb OpenAI funciona amb Cursor, Continue, Zed. Apunta'ls a http://127.0.0.1:9119/v1.
4. **Cerca semàntica:** Usa /v1/memory/search per a recuperació de documents basada en similitud sense coincidència exacta de paraules clau.
5. **Experimentació amb models:** Canvia entre backends MLX, llama.cpp i Ollama per comparar velocitat i qualitat.

## Consells

- **Primera execució:** La memòria està buida. Parla amb el servidor, puja documents, o usa `nexe knowledge ingest` per omplir el RAG.
- **Primera resposta lenta:** La càrrega del model triga (10-60s). L'indicador de càrrega mostra el progrés.
- **Backend desconnectat:** El servidor fa fallback automàticament al primer backend disponible. Comprova amb `./nexe status`.
- **Models grans:** Models de 32B+ necessiten 32+ GB de RAM i poden trigar minuts a carregar. Timeout de 600s.
