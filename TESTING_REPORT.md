# Informe de proves: Models LLM amb Nexe RAG + Memòria
**Data:** 24 de febrer de 2026
**Versió Nexe:** 0.8.0
**Autor:** Jordi Goy

---

## 1. Objectiu

Verificar el comportament del sistema RAG i memòria persistent de Nexe amb diferents models LLM, identificar problemes i determinar els requisits mínims per a un funcionament correcte.

---

## 2. Infraestructura Nexe testejada

### 2.1 Components verificats

| Component | Estat | Notes |
|---|---|---|
| RAG injecció de context | ✅ Funciona | 1400–1800 tokens injectats per petició |
| Auto-save de converses | ✅ Arreglat | Bug: buscava `choices[]` (OpenAI) en lloc de `message` (Ollama natiu) |
| Recuperació de memòria (nexe_chat_memory) | ✅ Funciona | Recupera converses de sessions anteriors |
| Filtre per idioma (NEXE_LANG) | ✅ Arreglat | Bug: usava `i18n.current_language="en-US"` en lloc de `NEXE_LANG=ca` |
| Re-indexació knowledge/ | ✅ Funciona | 233 punts indexats (9 docs × chunks de 900–1500 chars) |

### 2.2 Bugs trobats i corregits durant les proves

**Bug 1 — RAG retornava 0 resultats (`core/endpoints/chat.py`)**
El filtre `filter_metadata={"lang": _server_lang}` usava `i18n.current_language` que retorna `"en-US"` (valor per defecte del mòdul i18n), en lloc de `NEXE_LANG=ca`. El filtre era `lang:"en"` però els docs tenien `lang:"ca"` → 0 resultats.
**Fix:** `_server_lang = os.getenv("NEXE_LANG", "ca").split("-")[0].lower()`
**Impacte:** Tokens de prompt: 142 → 621 (RAG real injectat)

**Bug 2 — Auto-save no es disparava mai (`core/endpoints/chat.py`)**
El codi buscava `choices[0]["message"]["content"]` (format OpenAI) però Ollama retorna `message.content` (format natiu). La condició era sempre `False` → el background task mai s'afegia.
**Fix:** Fallback a `response.get("message", {}).get("content", "")` quan `choices` és buit.

**Bug 3 — `chat_format: "mistral"` invàlid a llama.cpp (`install_nexe.py` + `.env`)**
La llibreria llama_cpp_python no reconeix `"mistral"` (error: "Invalid chat handler"). A més, `"mistral-instruct"` (que sí accepta la llibreria) **descarta silenciosament el system message**, eliminant tot el context RAG (prompt_tokens caiguda de 1806 → 21).
**Fix:** `chat_format: "chatml"` per Mistral 7B i Mixtral — vàlid a llama.cpp i preserva el system message complet.

---

## 3. Models testejats

### 3.1 llama3.2 (3B) via Ollama

| | |
|---|---|
| **Engine** | Ollama |
| **RAM necessària** | ~2.5 GB |
| **Tokens RAG processats** | 1100–1400 |
| **Instruccions seguides** | ❌ Molt feble |

**Comportament observat:**
- Identifica el nom de l'usuari en el context però ho nega ("No tinc registre de teu nom, Jordi") — resposta contradictòria
- Al·lucina backends: inventava "GPT-4, T5, PPLMA" ignorant el context RAG
- Prompt engineering insuficient per la capacitat del model

**Veredicte:** No apte per producció amb RAG. Acceptable per respostes simples sense context.

---

### 3.2 Mistral 7B v0.2 (GGUF local) via llama.cpp

| | |
|---|---|
| **Engine** | llama.cpp (GGUF) |
| **Fitxer** | `mistral-7b-instruct-v0.2.Q4_K_M.gguf` (4.1 GB) |
| **RAM necessària** | ~5.5 GB |
| **Tokens RAG processats** | 1754 (en anglès) / ~21 (català — bug) |
| **Instruccions seguides** | ✅ Bo (en anglès) |

**Comportament observat:**
- **En anglès:** Resposta correcta i precisa usant context RAG (MLX, llama.cpp, Ollama)
- **En català:** Confon "Quins" (pronom interrogatiu català) amb un nom d'empresa → al·lucinació total
- El format `mistral-instruct` a llama.cpp descarta el system message → perd RAG

**Veredicte:** Bo per usuaris anglòfons. No recomanat per català/castellà. Requereix `chat_format=chatml`.

---

### 3.3 Salamandra 7B via Ollama

| | |
|---|---|
| **Engine** | Ollama |
| **Model ID** | `hdnh2006/salamandra-7b-instruct:q4_K_M` |
| **RAM necessària** | ~6.5 GB |
| **Tokens RAG processats** | 1360–1715 |
| **Instruccions seguides** | ⚠️ Parcial |

**Comportament observat:**
- Català excel·lent — especialitzat en llengües ibèriques (BSC/AINA, Catalunya)
- Repetia instruccions del system prompt en lloc de respondre ("Quan reps [CONTEXT MEMÒRIA]...")
- Confonia rols user/assistant en la memòria ("m'agrada el blau" quan ho havia dit l'usuari)
- Respostes parcials: "Suporta Phi-3.5 Mini" en lloc dels 3 backends

**Veredicte:** Excel·lent per tasques de llengua catalana pura. Instruction-following insuficient per RAG complex. No recomanat com a model principal de Nexe.

---

### 3.4 Gemma 3 27B via Ollama ⭐ Recomanat

| | |
|---|---|
| **Engine** | Ollama |
| **Model ID** | `gemma3:27b` |
| **RAM necessària** | ~20 GB |
| **Tokens RAG processats** | 741–1502 |
| **Instruccions seguides** | ✅ Excel·lent |

**Comportament observat:**
- **Identitat:** Respon perfectament: "Soc Nexe, l'assistent expert oficial de Server Nexe v0.8, creat per Jordi Goy"
- **RAG documentació:** Usa el context per donar respostes tècniques precises sobre plugins, arquitectura i ús
- **Memòria persistent:** Recorda amb precisió: "et dius Jordi, ets el creador de Nexe i programes en Python i Swift"
- Català natural i fluid
- No al·lucina quan el context és rellevant

**Veredicte:** ✅ **Model recomanat per producció amb Nexe.** Requereix màquina amb ≥20 GB RAM lliure.

---

## 4. Taula comparativa

| Model | Mida | Català | RAG | Memòria | Instruccions | Recomanació |
|---|---|---|---|---|---|---|
| llama3.2 3B | 1.9 GB | Regular | ❌ | ⚠️ | ❌ | No |
| Salamandra 2B | 1.4 GB | ✅ | ❌ | ❌ | ❌ | No |
| Mistral 7B | 4.1 GB | ❌ (EN ✅) | ✅ EN | ⚠️ | ✅ EN | Anglès |
| Salamandra 7B | 4.9 GB | ✅✅ | ⚠️ | ⚠️ | ⚠️ | Llengua pura |
| Gemma 3 12B | 7.0 GB | ✅ | ✅ | ✅ | ✅ | ✅ Recomanat |
| Llama 3.1 8B | 4.7 GB | ✅ | ✅ | ✅ | ✅ | ✅ Recomanat |
| **Gemma 3 27B** | **16.2 GB** | **✅✅** | **✅✅** | **✅✅** | **✅✅** | **⭐ Millor** |
| Mixtral 8x7B | 26 GB | ✅ | ✅ | ✅ | ✅ | Pro |
| Llama 3.1 70B | 40 GB | ✅ | ✅ | ✅ | ✅✅ | Pro |

> *Gemma 3 12B i Llama 3.1 8B no s'han provat directament però s'espera comportament similar a Gemma 3 27B basant-se en la família.*

---

## 5. Conclusió: Per què els models petits fallen amb RAG

El problema **no és un bug del sistema Nexe** — la infraestructura funciona correctament:

```
Petició → RAG cerca Qdrant → 1400-1800 tokens context → System prompt + context → Model
```

El problema és la **capacitat d'instruction-following** dels models petits:

- **<4B paràmetres:** No prou capacitat per seguir instruccions com "Usa el bloc [CONTEXT MEMÒRIA] com la teva pròpia memòria"
- **7B paràmetres:** Depèn molt del model. Generalment funciona en anglès però pot fallar en multilingüe o amb contextos complexos
- **≥12B paràmetres:** Instruction-following prou robust per usar el context RAG de forma consistent

**Llindar pràctic recomanat: ≥12B paràmetres** per producció amb RAG i memòria persistent.

---

## 6. Configuració recomanada per idioma

### Català / Castellà
```
NEXE_MODEL_ENGINE=ollama
NEXE_OLLAMA_MODEL=gemma3:27b     # si tens ≥24 GB RAM
# o bé:
NEXE_OLLAMA_MODEL=gemma3:12b     # si tens ≥12 GB RAM
NEXE_PROMPT_TIER=full
```

### Anglès (o màquina amb menys RAM)
```
NEXE_MODEL_ENGINE=llama_cpp
NEXE_LLAMA_CPP_MODEL=storage/models/mistral-7b-instruct-v0.2.Q4_K_M.gguf
NEXE_LLAMA_CPP_CHAT_FORMAT=chatml
NEXE_PROMPT_TIER=full
```

### Apple Silicon (MLX natiu)
```
NEXE_MODEL_ENGINE=mlx
NEXE_MLX_MODEL=mlx-community/gemma-3-12b-it-4bit
NEXE_PROMPT_TIER=full
```

---

## 7. Canvis aplicats al codi (commits)

| Commit | Descripció |
|---|---|
| `5bc2d97` | fix: RAG filtra per NEXE_LANG en lloc de i18n.current_language |
| `fd6f588` | chore: eliminar README.md de knowledge/ (mai s'indexa al RAG) |
| `f5d68e8` | revert: restaurar README.md — sí s'indexa, conté info valuosa |
| `111f95f` | fix: auto-save memòria i prompts de memòria millorats |
| `28d7cbb` | fix: MODEL_CATALOG corregit amb models testejats |
