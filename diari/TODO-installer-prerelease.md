---
id_ressonant: "{{NAT_ID_RESSONANT}}"
versio: "v1.0"
data: 2026-04-08
id: todo-installer-prerelease
abstract: "TODOs pendents a l'installer abans del pre-release v0.9.0. Swift wizard, models per RAM, GUI+CLI unificats, icones. Feines no-complexes però crítiques per acceptació."
tags: [installer, todo, prerelease, v090, swift, ram, icones]
chunk_size: 800
priority: P0
project: server-nexe
area: dev
type: todo
estat: open
lang: ca
author: "Jordi Goy"
---

# TODO Installer — Pre-release v0.9.0

↑ [[nat/dev/server-nexe/diari/INDEX_DIARI|Diari]]
🔗 [[nat/dev/server-nexe/diari/mega-test/areas/03-installer-gui|Mega-test àrea 03 — Installer GUI]]
🔗 [[nat/dev/server-nexe/diari/plans/PLA-VALIDACIO-FINAL-2026-04-08|Pla validació final]]

---

## Context

Llista de feines **no-complexes però crítiques** per a l'acceptació de l'installer v0.9.0. Totes s'han de fer **abans del pre-release**. El mega-test àrea 03 verifica l'estat actual i apunta què queda pendent.

**Regla:** apunta estat i data d'aplicació un cop completat cada ítem.

---

## 🔥 BLOQUEJADOR v1.0 — Install neta 2026-04-15 tarda

### Símptoma
Install neta M4 amb DMG v0.9.8 → UI bloquejada amb `readiness: status = "unhealthy"`. No arrenca. (Observat per Jordi; la 1a install neta del dia sí va funcionar, la 2a no.)

### Pla de test (aparcat fins arreglar install)
Un cop install neta arrenqui OK, provar per a cada engine (Ollama / MLX / llama.cpp):

1. Memòria: afegir → reiniciar → recordar → esborrar → reiniciar → comprovar
2. Pujar imatge (VLM)
3. Pujar doc (PDF / MD)
4. Fer preguntes obrint la documentació (RAG)
5. Canviar pes / temperatura
6. Activar/desactivar els checks de col·leccions (personal_memory / user_knowledge / nexe_documentation)

Escenari complet per engine = 6 passos × 3 engines = 18 validacions.

### Fix installer ja commitat (dev, pendent gitoss + DMG rebuild)
Commit `5d72a92` al dev: `fix(installer): install all 3 backends so engine switching works`
- `installer_setup_env.py`: `llama-cpp-python` s'instal·la sempre (abans només si es triava llama.cpp al wizard).
- `installer_setup_config.py`: `NEXE_APPROVED_MODULES` inclou sempre els 3 backends.

**Pendent:** `/gitoss server-nexe` + `/dmg-nexe` + nova install neta amb DMG actualitzat.

---

## Ítems

### 1. Swift wizard — Selecció models per RAM (font oficial: blog jgoy 2026-04-06)

**Pendent** — `installer/swift-wizard/`

**Font de veritat:** [[nat/projectes/jgoy/blog/articles/cat/quin-model-llm-local-triar|"Tens la màquina. Ara, quin model?"]] (2026-04-06, Jordi Goy). També versions `es/` i `en/`.

Canviar el criteri de selecció de models:
- **Antic:** dividir per "petits / grans" (vague, subjectiu)
- **Nou:** dividir per **RAM disponible del sistema** seguint la taula oficial del blog

### Tiers RAM oficials (7 tiers segons article)

| RAM | Rang paràmetres (Q4_K_M) |
|---|---|
| 8 GB | 3B – 8B |
| 16 GB | 8B – 14B |
| 24 GB | 14B – 27B |
| 32 GB | 20B – 35B |
| 48 GB | 30B – 72B (o MoE grans) |
| 64 GB | 40B – 122B (MoE) |
| 128 GB | 70B – 400B (MoE) |

**Regla del 25 %**: mai carregar un model que ompli tota la RAM. Sempre deixar ≥25 % lliure. Si fora de tiers (ex: 12 GB), cau al tier inferior (8 GB).

### Models recomanats per tier (del propi article)

**Franja 8 GB**
- **Gemma 4 E4B** (Google) — 8B totals / ~4-8B efectius · ~4-5 GB · 128K ctx · thinking configurable · visió (img+audio) · Ollama/MLX/llama.cpp — *multimodal ràpid, millor qualitat per 8 GB*
- **Phi-4-mini** (Microsoft) — 3.8B · ~3.5 GB · 128K · thinking natiu · Ollama/MLX/llama.cpp — *rei del baix consum en mates i codi*
- **Qwen3.5 9B** (Alibaba) — 9B · ~5-6 GB · 128K (→1M) · thinking (pot sobrepensar) · visió VL · Ollama/MLX/llama.cpp — *multilingüe i codi sòlid*

**Franja 16 GB**
- **Qwen3.5 14B** — 14B · ~8-9 GB · 128K (→1M) · thinking excel·lent · visió VL · tots backends — *millor equilibri qualitat/velocitat*
- **Gemma 4 26B-A4B** (MoE) — 26B/4B actius · ~9-10 GB · 256K · thinking · visió · tots backends — *qualitat 26B a velocitat 4B*
- **Llama 3.3 8B** o **Llama 4 Scout petit** — 8B / 17B actius · ~6-8 GB · 128K-10M · thinking fort · visió (Scout) · tots backends — *context bestial amb Scout*
- **Salamandra 7B Instruct** (BSC/AINA) — `hdnh2006/salamandra-7b-instruct` — *català pur, recomanat per la comunitat catalana*

**Franja 24 GB**
- **Qwen3.5 27B** — 27B · ~16-18 GB · 128K (→1M) · thinking excel·lent · visió VL · tots backends — *millor ràtio qualitat/mida*
- **Gemma 4 31B dense** — 31B · ~17-19 GB · 256K · thinking excel·lent · visió · Ollama/llama.cpp — *alternativa potent en raonament*
- **GLM-4.7-Flash** (Zhipu) — ~27B · ~17 GB · 128K · thinking agentic · Ollama/llama.cpp — *excel·lent per agents i codi*

**Franja 32 GB**
- **Qwen3.5 35B-A3B** (MoE) — 35B/3B actius · ~20-22 GB · 128K (→1M) · thinking excel·lent · visió · tots backends — *velocitat 9B qualitat 35B*
- **Llama 4 Scout** (Meta) — 109B/17B actius · ~22-25 GB · **context 10M** · thinking fort · visió nativa · tots backends — *disbarat útil per documents enormes*
- **DeepSeek R1 20B** — 20B · ~18-20 GB · 128K · thinking excel·lent estil o1 · Ollama/llama.cpp — *millor pensament pas a pas obert*
- **gpt-oss 20B** (OpenAI, agost 2025) — 20B MoE · ~18-20 GB · 128K · thinking natiu · Ollama/llama.cpp — *raonament sòlid, dels que Jordi fa servir*
- **ALIA-40B Instruct** (BSC) — per feina seriosa en català, GGUF oficial a `BSC-LT/ALIA-40b-instruct-2601-GGUF` via llama.cpp — *el gran multilingüe europeu*

**Franja 48 GB**
- **Qwen3.5 72B o 122B-A10B** (MoE) — 72B/122B totals (10B actius) · ~35-42 GB · 128K (→1M) · thinking excel·lent · visió · tots backends — *potència frontera amb consum contingut*
- **Llama 4 Maverick** — 400B/17B actius · ~38-45 GB · ~1M · thinking fort · visió · Ollama/llama.cpp — *multimodal context enorme*
- **DeepSeek R1 32B dense** — 32B · ~36-40 GB · 128K · thinking excel·lent estil o1 · Ollama/llama.cpp — *pensament profund consum contingut*

**Franja 64 GB**
- **Llama 4 Maverick Q5** — 400B/17B actius · ~45-55 GB · ~1M · thinking fort · visió · tots backends — *quasi qualitat frontera*
- **Qwen3.5 122B-A10B** (MoE) — 122B/10B actius · ~48-52 GB · 128K (→1M) · thinking excel·lent · visió · tots backends — *màxim per codi i agents*
- **DeepSeek V3.2 o R1 gran** — 671B/37B actius · ~50-55 GB · 128K · pensament profund · Ollama/llama.cpp — *per problemes a fons*

**Franja 128 GB**
- **Qwen3.5 397B-A17B** (MoE) — 397B/17B actius · ~90-110 GB · 128K (→1M) · thinking excel·lent · visió · Ollama/llama.cpp — *el més proper a un model tancat*
- **Llama 4 Behemoth o Scout complet** — >400B MoE · ~100-120 GB · **context 10M** · thinking fort · visió · Ollama/llama.cpp — *context absurd + multimodal*
- **DeepSeek R1 671B** (MoE) — 671B/37B actius · ~95-115 GB · 128K · Ollama/llama.cpp — *rei del raonament obert, pensament visible al màxim*

### Secció destacada — Models catalans (BSC / AINA)

L'installer hauria de destacar visualment una secció **"Models catalans"** per als usuaris que volen català com a llengua de treball:

- **Salamandra 2B Instruct** — `BSC-LT/salamandra-2b-instruct` — tier 8-16 GB
- **Salamandra 7B Instruct** — `BSC-LT/salamandra-7b-instruct` — recomanat, tier 16 GB+
- **ALIA-40B Instruct** — `BSC-LT/ALIA-40b-instruct-2601-GGUF` — tier 32 GB+, llama.cpp

Criteri: entrenats des de zero amb català, castellà, portuguès, gallec, basc, aragonès, occità, aranès. Corpus MareNostrum 5.

### Detecció RAM

- Swift: `ProcessInfo.processInfo.physicalMemory`
- Shell: `sysctl hw.memsize`
- Fallback raonable si fora de tiers → tier inferior

### Verificació mega-test

- `grep -rn "tier\|8gb\|16gb\|24gb\|32gb\|48gb\|64gb\|128gb\|physicalMemory\|memsize" installer/swift-wizard/` → apareix post-fix
- `grep -rn "Salamandra\|ALIA\|BSC-LT" installer/swift-wizard/` → secció catalana present
- Test: sistema 16 GB → proposa tier-16gb; sistema 128 GB → tier-128gb
- Regla 25 %: si RAM = X GB, model consum ≤ 0.75 × X

**Data aplicació:** pendent
**Responsable:** pendent
**Notes post-aplicació:** [buit]

---

### 2. Actualitzar catàleg a models més nous

**Pendent** — `installer/` + catàleg models

**Font de veritat:** el mateix article del blog que l'ítem 1. La llista de models dins de cada tier (ítem 1) és la **referència canònica** per al catàleg de l'installer al pre-release v0.9.0.

**Acció concreta:**
1. Llegir el catàleg actual del Swift wizard / config installer
2. Comparar amb la llista de l'ítem 1 (per cada tier)
3. Afegir els models que falten (Gemma 4, Qwen3.5 variants, Llama 4 Scout/Maverick/Behemoth, gpt-oss 20B, DeepSeek R1/V3.2, Salamandra, ALIA)
4. Eliminar models obsolets o de versions anteriors (phi3:mini si phi-4-mini és millor, gemma-2 si gemma-4 és viu, etc.)
5. Per cada model: nom oficial Ollama/MLX/HF + mida estimada Q4_K_M + tier RAM recomanat + flags (thinking/visió)

**Verificació mega-test:**
- Comparar catàleg actual vs llista de l'ítem 1
- **Per cada model de la llista de referència**, verificar que hi és al catàleg installer
- Models del catàleg que **no** són a la llista → candidats a eliminar
- Data última actualització del catàleg (si és anterior a 2026-04-06 → cal revisar)

**Data aplicació:** pendent
**Responsable:** pendent
**Notes post-aplicació:** [buit]

---

### 3. GUI instal·la també el CLI

**Pendent** — `installer/install.py` + `installer/swift-wizard/`

Actualment (post-cirurgia) la GUI i el CLI són fluxos separats. Cal que el **flux GUI** també instal·li i configuri el CLI:
- Binari `nexe` al PATH (`/usr/local/bin/` o `~/bin/`)
- `nexe` CLI functional immediatament post-install GUI
- Ambdós comparteixen la mateixa install dir, venv, config

**Verificació mega-test:**
- Post-install GUI simulat → `nexe --help` respon
- Path `nexe` existeix i apunta al venv correcte
- `nexe go` arrenca el mateix servidor que la GUI

**Data aplicació:** pendent
**Responsable:** pendent
**Notes post-aplicació:** [buit]

---

### 4. Icona al logger

**Pendent** — `installer/` + logs

Afegir icona/identificació visual al logger:
- Logs de l'installer mostren icona `nexe` a l'output (terminal colors + emoji)
- Si el logger escriu a fitxer → fitxer té capçalera amb projecte
- Per distingir de logs d'altres processos quan es mira `console.app` o similar

**Verificació mega-test:**
- `grep -rn "🧠\|nexe logo\|log_icon\|logger.*icon" installer/` → apareix post-fix
- Logs de install fresca contenen identificació

**Data aplicació:** pendent
**Responsable:** pendent
**Notes post-aplicació:** [buit]

---

### 5. Icona al system tray

**Pendent** — `installer/tray.py`

El tray macOS ha de tenir **icona pròpia** (no icona genèrica de Python/rumps).
- Asset: `assets/tray-icon.png` (o `.icns` / template image)
- Visible a menu bar
- Dark mode / light mode variants
- Template image format (macOS auto-adapta colors)

**Verificació mega-test:**
- `find installer/ -name "*tray*icon*" -o -name "tray*.png" -o -name "tray*.icns"`
- `grep -n "icon\|NSImage\|template" installer/tray.py`
- Icon path referenciat al bundle (`Install Nexe.app/Contents/Resources/`)

**Data aplicació:** pendent
**Responsable:** pendent
**Notes post-aplicació:** [buit]

---

### 6. Icona a les tasques (Dock / Applications)

**Pendent** — `Install Nexe.app/Contents/Resources/`

El `.app` bundle ha de tenir **icona pròpia** (AppIcon.icns):
- Dock quan l'aplicació corre
- Applications folder
- Finder quan es mira el bundle
- Multi-resolució (16x16 fins 1024x1024)
- Info.plist referencia `CFBundleIconFile`

**Verificació mega-test:**
- `ls "Install Nexe.app/Contents/Resources/"*.icns`
- `plutil -p "Install Nexe.app/Contents/Info.plist" | grep -i icon`
- Icon real no genèric (mida raonable, no 1 KB default)

**Data aplicació:** pendent
**Responsable:** pendent
**Notes post-aplicació:** [buit]

---

### 7. Baixar tots els models al SSD per a les proves

**Pendent** — governança / secretaria (TODO_INBOX global)

Abans del primer run del mega-test amb servidor viu, cal tenir **tots els models del catàleg de l'ítem 1 descarregats al SSD** per poder provar el switch backend/model en viu (àrea 19 Stress GPU del mega-test).

**Regles de descàrrega:**
- **Memòria:** `feedback_descarregues_ssd.md` — primer al SSD, després moure a disc extern si cal
- **Ubicacions:** `~/.ollama` (Ollama), `~/.cache/huggingface/hub` (HF/MLX), `~/models/server-nexe/` (GGUF llama.cpp) — NO dins d'`AI/`
- **Prioritat:** tier 128 GB (Mac Studio M4 Max principal) + tiers 16/24 GB (portàtil)
- **Especial:** Salamandra 2B/7B + ALIA-40B prioritaris (català)

**Llista canònica:** la mateixa de l'ítem 1 (catàleg tiers).

**Referència global:** afegit a [[nat/diari/TODO_INBOX|TODO_INBOX]] secció "SERVER-NEXE pre-release v0.9.0".

**Verificació mega-test:**
- Àrea 19 (Stress GPU) necessita aquests models presents per poder fer el switch backend/model en viu
- Si falten → àrea 19 queda INCOMPLETA

**Data aplicació:** pendent
**Responsable:** governança / secretaria
**Notes post-aplicació:** [buit]

---

### 8. RAM monitor del tray — mostra "context" (RSS Python), no càrrega del model

**Pendent** — `installer/tray_monitor.py:82-107` + `installer/tray.py:181-394`

**Detectat:** repàs mega-test àrea 07, 2026-04-08
**Severitat:** 🟡 P1 (UX confús, no bloca funcionament)

#### Problema

`installer/tray_monitor.py::RamMonitor._read_ram()` mesura `RSS` del procés
server-nexe + fills directes via `ps -o rss= / pgrep -P`. Aquest número
**NO és la càrrega del model**:

- **Ollama backend** → procés extern, NO és fill → 0 bytes del model comptats. Tray pot mostrar 300 MB mentre Ollama té 20 GB carregats. **Especialment confús.**
- **MLX backend** → unified memory Apple Silicon, RSS infravalora la càrrega real (mmap + GPU shared)
- **llama.cpp + Metal** → similar
- **HF transformers** → sí que apareix al RSS

L'usuari interpreta el número com "RAM del model" quan és "RAM del procés Python".

#### Opcions de fix (per decidir pre-release)

- **a)** Etiqueta clara al menú: "Server RAM (no model)" / "Procés server-nexe"
- **b)** Detectar backend actiu i sumar la RAM corresponent:
  - Ollama → consultar `ollama ps` o el seu API HTTP
  - MLX → reportar memòria GPU shared via `mx.metal.get_active_memory()`
  - llama.cpp → consultar via API si exposa stats
- **c)** Mostrar dos números: "Server: X MB · Model: Y GB"
- **d)** Acceptar limitació i només etiquetar amb un tooltip explicatiu

#### Verificació mega-test

- Llegir `tray_monitor.py:_read_ram()` i confirmar fonts
- Cross-check matriu backends fills/externs amb àrea 11 (plugins)
- Test reproduïble: arrencar amb Ollama, comparar RAM tray vs `ollama ps`

**Data aplicació:** pendent
**Responsable:** pendent
**Notes post-aplicació:** [buit]

---

### 9. Tray apareix com "Python" a Force Quit / Activity Monitor — .app bundle propi

**Pendent** — `installer/tray.py` + `Nexe.app/` o nou `NexeTray.app/`

**Detectat:** repàs mega-test àrea 07, 2026-04-08 (captura Jordi 2026-04-07 16:20)
**Severitat:** 🔴 **P0 BLOCKER** (UX visible per usuari final, primera impressió)

#### Problema

`installer/tray.py:476-479` literal:

```python
# "Python" (requires CFBundleName via a real .app bundle — deferred to v0.9.1).
import setproctitle
setproctitle.setproctitle("nexe-tray")
```

El propi codi reconeix que **`setproctitle` no és suficient**: només canvia el que veu `ps` / Activity Monitor (per via `argv[0]`), però la finestra "Força la sortida de les apps" llista per `CFBundleName` del `.app` bundle real.

**Captura Jordi 2026-04-07** mostra "Python" amb icona Python a la finestra Force Quit. Lògicament és la **tray** (no el server, perquè si server estigués apagat només queda tray viva i continua sortint), llançada via `python -m installer.tray` directe → no és un .app bundle → macOS la tracta com a "Python".

**Promogut de v0.9.1 → v0.9.0** per decisió Jordi 2026-04-08.

#### Acció

- **Crear/usar .app bundle propi per la tray** amb `Info.plist`:
  - `CFBundleName` = `Nexe` o `server-nexe` (a decidir)
  - `CFBundleIdentifier` = `net.servernexe.tray`
  - `CFBundleIconFile` = icona pròpia (cross-check item 5)
  - `LSUIElement` = `<true/>` (status bar app, no dock real)
  - `CFBundleExecutable` apuntant a wrapper que llanci `python -m installer.tray`
- **Bundles existents al dev:** `Nexe.app/`, `InstallNexe.app/`, `Install Nexe.app/` — verificar quin reutilitzar o crear `NexeTray.app/` nou
- **Tots els paths d'arrencada han de llançar via .app**, NO via `python -m installer.tray` directe (cross-check item 11)

#### Verificació mega-test

- Llançar tray (per qualsevol via)
- Obrir "Força la sortida de les apps" (Cmd+Opt+Esc)
- Esperat: apareix "Nexe" o "server-nexe" amb icona pròpia, **NO** "Python"
- Mateix test a Activity Monitor

**Data aplicació:** pendent
**Responsable:** pendent
**Notes post-aplicació:** [buit]

---

### 10. LoginItem auto-arrencada al boot Mac (default OFF)

**Pendent** — `installer/swift-wizard/Sources/InstallNexe/CompletionView.swift:106-220` + `installer/install.py`

**Detectat:** repàs mega-test àrea 07, 2026-04-08
**Severitat:** 🟡 P1

#### Estat actual

`CompletionView.swift:106` ja té el toggle implementat:
```swift
@State private var addLoginItem = false  // ← OFF per defecte ✅
Toggle(isOn: $addLoginItem) { ... }
if addLoginItem { doAddLoginItem() }
```

Funció `doAddLoginItem()` a `:207`. **Verificar implementació.**

#### Decisions Jordi 2026-04-08

- **Default OFF** ("només dock per defecte" — l'usuari decideix activar)
- Cal funcionar tant a GUI (Swift wizard) com a headless (`install.py --add-login-item`)
- L'uninstaller (cross-check item 6 + àrea 06) ha d'eliminar-lo

#### Acció

- Llegir `CompletionView.swift:107-220` sencer, determinar si usa:
  - **`SMAppService`** (modern, macOS 13+ Ventura) — recomanat
  - **`LaunchAgent ~/Library/LaunchAgents/`** (legacy però universal)
- Verificar que el path al binari del bundle és correcte (cross-check item 9)
- Afegir flag equivalent a headless install: `install.py --add-login-item`
- Documentar al README com activar/desactivar manualment

#### Verificació mega-test

- GUI install amb toggle OFF → no LoginItem creat
- GUI install amb toggle ON → LoginItem creat, reboot Mac → tray arrenca sola
- Uninstaller → LoginItem eliminat
- `launchctl list | grep nexe` (LaunchAgent) o `sfltool dumpbtm` (SMAppService)

**Data aplicació:** pendent
**Responsable:** pendent
**Notes post-aplicació:** [buit]

---

### 11. Centralització arrencada — la tray és l'única via

**Pendent** — `installer/tray.py` + `core/cli/` + `core/server/runner.py`

**Detectat:** repàs mega-test àrea 07, 2026-04-08
**Severitat:** 🔴 **P0 BLOCKER** (origen arrel dels bugs Track B #1 múltiples instàncies)

#### Problema

Decisió Jordi 2026-04-08: *"Centralitzar tot al tray. Centralitzar les comandes de start. Sinó és quan comencen tots els bugs."*

Actualment hi ha múltiples vies d'arrencar el server independents:
- `installer/tray.py` (via menú tray)
- `./nexe go` (CLI wrapper)
- `python -m core.app` directe
- `Nexe.app` / `InstallNexe.app` (DMG launchd)
- LoginItem (post item 10)

Cap d'elles coordina amb les altres → tray orfe, doble bind port, segon procés silenciós.

#### Acció

La **tray ha de ser l'única via** d'arrencar el server. La resta han de:

- **Opció A — Avortar amb missatge clar:** "Error: arrencada del server centralitzada via tray. Usa `Nexe.app` o llança el tray des del menú."
- **Opció B — Delegar al tray:** la comanda llança el tray (si no està actiu) i el tray arrenca el server.

Recomanació: **Opció B** per UX (l'usuari fa `./nexe go` i tot funciona transparent), però amb **single-instance hard** (item 12) garantit.

#### Verificació mega-test

- Inventari empíric vies d'arrencada actuals (grep)
- Test: cada via no-tray ha d'avortar o delegar
- Test: només la tray pot arrencar el server "des de zero"
- Cross-check àrea 20 (CLI runner) i àrea 08 (lifespan)

**Data aplicació:** pendent
**Responsable:** pendent
**Notes post-aplicació:** [buit]

---

### 12. Single instance hard enforcement — impossible 2 servers al mateix port

**Pendent** — `core/server/runner.py` + `installer/tray.py` + `storage/server.pid`

**Detectat:** repàs mega-test àrea 07, 2026-04-08 (Bug #1 Track B preexistent)
**Severitat:** 🔴 **P0 BLOCKER** (sense això tornen els bugs múltiples instàncies)

#### Problema

Decisió Jordi 2026-04-08: *"no deixar tenir més de [un] servidors, sinó és quan comencen tots els bugs."*

Bug #1 Track B Fix-All 2026-04-07 va introduir PID file (`storage/server.pid`) i `tests/test_pid_file.py` (7 tests). **Però** l'enforcement cross-vies no està garantit — depèn item 11 (centralització).

#### Acció

- **PID file canònic:** `storage/server.pid` amb PID + timestamp (ja existeix post Bug #1)
- **Lock advisory:** `fcntl.flock(LOCK_EX | LOCK_NB)` o `O_EXCL` al fitxer PID
- **Tots els paths d'arrencada el respecten** (depèn item 11):
  - Si existeix + PID viu + port en ús → avortar amb missatge clar (`"Server already running, PID X"`)
  - Si existeix + PID mort o port lliure → esborrar i continuar
- **Endpoint `/admin/system/shutdown`** (autenticat) per shutdown net des de qualsevol controlador (cross-check àrea 14 sec auth)

#### Tests reproduïbles obligats post-fix

1. Tray actiu + server → `./nexe go` extern → avorta amb missatge
2. `./nexe go` actiu → segon `./nexe go` → avorta
3. Tray actiu sense server → `./nexe go` extern → tray "adopta" o avisa
4. Server crash brut → PID file residual + següent arrencada el detecta com a mort

#### Verificació mega-test

- Executar `pytest tests/test_pid_file.py -v`
- Test reproduïble manual dels 4 escenaris
- Cross-check àrees 08 (lifespan), 11 (plugins), 20 (CLI), 22 (DMG)

**Data aplicació:** pendent
**Responsable:** pendent
**Notes post-aplicació:** [buit]

---

### 13. i18n complet del tray (3 idiomes)

**Pendent** — `installer/tray.py` + `installer/tray_translations.py`

**Detectat:** repàs mega-test àrea 07, 2026-04-08
**Severitat:** 🟡 P1

#### Estat actual

`installer/tray_translations.py` existeix post Track B Fix-All 2026-04-07 (Bug #9 menu polish). Cobertura parcial.

Decisió Jordi 2026-04-08: *"si tot va amb i18n també verificar"* — el menú tray sencer ha d'estar i18n (en/ca/es), com la resta del sistema (cross-check àrea 17 Q3).

#### Acció

- Auditar `tray_translations.py`: confirmar 3 idiomes (en, ca, es) per cada clau
- Auditar `tray.py`: cap string visible hardcoded (`grep '"[A-Z][a-z]'` excloent comentaris i logs interns)
- Items menú a cobrir: Status, Settings, Logs, Quit, Documentació, Server start/stop, About, RAM usage label, errors visibles a usuari
- Coherència amb i18n API (cross-check àrea 17)
- Coherència amb knowledge base (cross-check àrea 21)

#### Verificació mega-test

- `grep -E "^\s*['\"]?(en|ca|es)['\"]?\s*[:=]" installer/tray_translations.py`
- Llançar tray amb LANG=ca, LANG=es, LANG=en — verificar menú correcte
- Comptar claus a `tray_translations.py` vs strings al `tray.py`

**Data aplicació:** pendent
**Responsable:** pendent
**Notes post-aplicació:** [buit]

---

### 14. Tray "Quit" no mata el server pare — server orfe sobreviu indefinidament

**✅ RESOLT — `b44645b` + `fbf029f` (2026-04-09)** — Bloc B Lifespan + PID file enforcement. SIGTERM propaga, server s'atura net. Bug #14 refutat al runtime per mega-consultoria real (./nexe stop --force funciona).

**Detectat:** sessió B.4-B.8 director, 2026-04-08 vespre, durant intent de tancament del server post-smoke test
**Severitat:** 🔴 P0 — bug d'usabilitat crític + risc d'estat brut entre execucions

#### Problema

Quan l'usuari clica **"Quit"** al menú del tray, el tray es tanca però **el server pare segueix viu indefinidament** escoltant al port 9119. Resultat: l'usuari creu que ha tancat server-nexe però en realitat segueix executant-se en background, consumint RAM i ocupant el port. La pròxima vegada que vulgui arrencar el server amb `./nexe go`, fallarà perquè el port està ocupat.

A més, el procés pare pot quedar **orfe** (PPID=1, adoptat per launchd) si la sessió que l'ha llançat acaba abans que el server, fent-lo invisible a `pkill` per process tree.

**Triple causa encadenada:**

1. **Tray és FILL del server, no a l'inrevés**. L'arbre real és:
   ```
   PID X — python -m core.cli go        (wrapper)
   └── PID Y — server-nexe (uvicorn)    (procés del server, escolta :9119)
       ├── PID Z — nexe-tray            (menú bar — fill, no pare)
       └── PID W — multiprocessing.resource_tracker
   ```
   El tray.py només pot enviar quit a si mateix (`rumps.quit_application()` o equivalent). No té cap canal per matar el seu pare server. Per tant **"Quit" del menú només mata el tray**, no el server.

2. **`setproctitle` enganya `pkill -f`**. El server es renombra a `server-nexe` via `setproctitle`. Per tant `pkill -f "nexe go"` (que sembla raonable) NO troba res — al títol ja no hi ha "nexe go". Documentació confusa per l'usuari que vol matar manualment via terminal.

3. **Wrapper pare no propaga signals**. El wrapper `python -m core.cli go` és un procés intermedi que arrenca el server uvicorn com a fill. SIGTERM al wrapper (PID X) NO propaga al fill server (PID Y) automàticament — cal matar el server directament. Verificat empíricament: matar el wrapper deixa els fills vius.

#### Reproducció (verificat empíricament 2026-04-08 16:34-17:15)

```bash
# 1. Arrencar el server en background des d'una sessió shell qualsevol
cd /Users/jgoy/AI/nat/dev/server-nexe
./nexe go &

# 2. Esperar que arrenci (15s)
sleep 15
curl -s http://127.0.0.1:9119/health   # OK

# 3. Tancar la sessió shell que va llançar-lo (Cmd+W al terminal, o exit)
exit

# 4. Verificar que el server segueix viu (PARE adoptat per launchd PPID=1)
ps -ef | grep -i 'server-nexe\|nexe-tray' | grep -v grep
# Sortida esperada (BUG):
#   PID  server-nexe       (uvicorn :9119)
#   PID  nexe-tray         (menú bar)

# 5. Provar el "Quit" del tray des del menú bar de macOS
# RESULTAT: el tray desapareix però el server segueix viu

# 6. Provar pkill amb el nom obvi
pkill -f "nexe go"
# RESULTAT: NO troba res — el setproctitle ha renombrat a "server-nexe"

# 7. Verificar — server encara viu
lsof -iTCP:9119 -sTCP:LISTEN
# RESULTAT: Python still listening
```

**Cas verificat real**: PID 12054 (wrapper) → 12064 (server-nexe) → 12068 (tray) + 12111 (resource_tracker). 41 minuts uptime. SIGTERM al wrapper 12054 va matar només el wrapper. Calgué SIGTERM directe al 12064 per matar el server (i 12111 cascade). El tray 12068 va sobreviure fins a SIGTERM directe explícit.

#### Què fer (proposta de correcció)

**Opció A — Tray envia signal al pare via PID file (recomanada):**
1. Al startup del server, escriure el PID del procés uvicorn (no el wrapper) a `storage/run/server.pid`
2. El tray, al "Quit", llegir aquest PID i fer `os.kill(pid, signal.SIGTERM)` abans de fer `rumps.quit_application()`
3. El server lifespan handler ha de capturar SIGTERM i fer shutdown ordenat (tancar Qdrant, desar estat, alliberar port)
4. Verificar que el tray fill mor automàticament en cascada (process group)

**Opció B — Tray al mateix process group que el server:**
1. Llançar el tray amb `os.setpgid(0, server_pid)` perquè comparteixin process group
2. SIGTERM al group ID els mata tots dos

**Opció C — Wrapper propaga signals (solució addicional, no exclusiva):**
1. `core/cli/cli.py` instal·la handlers SIGTERM/SIGINT que fan kill al fill uvicorn abans d'exit
2. Útil per al cas de tancament des del shell pare

**Recomanació**: Opció A + Opció C combinades. PID file és el camí més robust per al cas tray, i els handlers al wrapper resolen el cas de tancament des del terminal.

#### Acció complementària: workaround de documentació

Mentre es corregeix, afegir a `knowledge/{ca,en,es}/ERRORS.md` o `USAGE.md` la nota:

> **Si el "Quit" del tray no funciona**: el server s'està executant orfe. Mata'l amb `pkill -9 server-nexe` (NO `pkill -9 "nexe go"` — el `setproctitle` el renombra). Verifica amb `lsof -iTCP:9119` que el port queda lliure.

#### Verificació mega-test (àrea 07 — tray macOS)

- Arrencar `./nexe go &` des d'un terminal
- Tancar el terminal que el va llançar
- Clicar "Quit" al tray del menú bar
- Verificar amb `pgrep -f server-nexe` que NO queda cap procés viu
- Verificar amb `lsof -iTCP:9119` que el port queda lliure
- Repetir 3 vegades consecutives sense reset manual

#### Cross-check amb altres àrees del mega-test

- **Àrea 07** (tray macOS) — el lloc principal on validar
- **Àrea 08** (core lifespan) — verificar shutdown ordenat post-SIGTERM
- **Àrea 22** (instal·lació test real) — l'usuari final ha de poder tancar el server netament des del tray

**Data detecció:** 2026-04-08 vespre
**Responsable:** pendent (mega-test director, sessió dedicada)
**Notes post-aplicació:** [buit]
**Cross-ref diari:** [[nat/dev/server-nexe/diari/2026-04/20260408/20260408_tancament_refactor_b4_b8|Tancament B.4-B.8]] (origen del descobriment)

#### 14.bis — Sub-tasca Cause 3 verificada empíricament 2026-04-08 nit (vigilant àrea 20)

**Estat empíric vigilant Director Repàs àrea 20:**

| Component | SIGINT handler | SIGTERM handler |
|---|---|---|
| Server (`core/server/helpers.py:38-48`) | ✅ `signal.signal(SIGINT, handler)` instal·lat | ✅ `signal.signal(SIGTERM, handler)` instal·lat |
| Server runner (`core/server/runner.py:251`) | ✅ crida `setup_signal_handlers()` | ✅ crida `setup_signal_handlers()` |
| **CLI wrapper (`core/cli/cli.py:155`)** | ✅ `KeyboardInterrupt` (SIGINT via excepció Python) | ❌ **0 hits `signal.signal(SIGTERM, ...)`** |

**Conseqüència del cause 3 confirmada parcialment:**
- ✅ `Ctrl+C` (SIGINT) al wrapper → `KeyboardInterrupt` capturat → cleanup mínim
- ⚠️ `kill -TERM <wrapper_pid>` → wrapper mor instantàniament SENSE handler explícit
- 🟡 **Però**: `subprocess.run` (Python 3.8+ POSIX) propaga el SIGTERM al child via OS automàticament → server child SÍ rep SIGTERM via `setup_signal_handlers()` → cleanup OK
- 🟡 Mac només scope v0.9.0 → comportament POSIX → **probablement OK**, però **sense test que ho garanteixi**

**Acció afegida (cirurgia ~10 min, post-Opció A+C):**

1. Afegir `signal.signal(signal.SIGTERM, lambda s, f: ctx.exit(0))` abans del `subprocess.run` a `cli.py:_start_nexe`
   ```python
   import signal
   def _term_handler(signum, frame):
       click.echo("\n👋 Stopping (SIGTERM)...")
       sys.exit(0)
   signal.signal(signal.SIGTERM, _term_handler)
   ```
2. Test empíric (chaos): `./nexe go &; PID=$!; sleep 5; kill -TERM $PID; sleep 2; lsof -iTCP:9119` → port lliure

**Aquesta sub-tasca s'inclou dins del item 14 (Cause 3 estructural).**

---

### 15. 🔮 `core/config.py` registry pattern — preparació futur panell d'administració

**✅ RESOLT — `c926555` (2026-04-08)** — NexeSettings amb pydantic-settings + list_settings() implementat.

**Detectat:** repàs mega-test àrea 09, 2026-04-08
**Severitat:** 🔴 P0 (arquitectura — lligat directament al futur panell admin del server-nexe)
**Decisió Jordi 2026-04-08 (literal):** *"una única font de veritat per tot. A més, quan fem el panell d'administració podrem recuperar variables i no estaran hardcoded per tot el codi."*

#### Problema

L'àrea 09 del mega-test (pas 9.3) ha estat designada com a **font única de veritat del catàleg d'env vars** del server-nexe. Aquesta decisió té una implicació arquitectònica que toca el codi: `core/config.py` ha de **exposar un registry** perquè el futur panell d'administració pugui llistar i descriure totes les settings dinàmicament, sense haver de grepejar el codi sencer cada vegada que afegim/canviem una env var.

**Estat actual (a verificar empíricament):**
- `core/config.py` defineix les env vars (probablement amb `os.getenv` o `pydantic-settings`)
- **Probable gap:** NO exposa cap API tipus `Config.list_settings()` / `get_all_env_vars()` / `describe_settings()` per descobriment dinàmic
- El futur panell admin avui hauria de grepejar el codi (inacceptable)

#### Acció

**Opció A — `pydantic-settings` amb `BaseSettings`:**
```python
# core/config.py
from pydantic_settings import BaseSettings
from pydantic import Field

class NexeSettings(BaseSettings):
    server_host: str = Field("127.0.0.1", description="Bind host del server", env="NEXE_SERVER_HOST")
    server_port: int = Field(9119, description="Port del server", env="NEXE_SERVER_PORT", ge=1024, le=65535)
    pid_file: str = Field("storage/server.pid", description="Path del PID file", env="NEXE_PID_FILE")
    encryption_key: str | None = Field(None, description="Clau crypto opcional", env="NEXE_ENCRYPTION_KEY")
    # ... totes les altres
    
    class Config:
        env_file = ".env"

    @classmethod
    def list_settings(cls) -> list[dict]:
        """Per al futur panell admin: llista totes les settings amb metadata."""
        return [
            {"name": name, "default": field.default, "description": field.description, "type": str(field.annotation)}
            for name, field in cls.model_fields.items()
        ]
```

**Opció B — `@dataclass` amb registry manual:**
- Si `pydantic-settings` no és vol afegir com a dependència
- Funciona igual però amb més codi boilerplate

**Recomanació:** Opció A (`pydantic-settings`) — ja està al món Python modern, validació gratis, descobriment automàtic via `model_fields`.

#### Verificació mega-test (àrea 09 pas 9.6)

```bash
# Confirmar pydantic-settings o equivalent
grep -nE "BaseSettings|pydantic_settings|@dataclass" core/config.py
grep -n "pydantic" requirements.txt requirements-macos.txt

# Confirmar API list_settings o equivalent
grep -nE "def (list_settings|get_all_env_vars|list_config|describe_settings|get_schema)" core/config.py
```

**Esperat post-fix:**
- `core/config.py` usa pydantic-settings (o equivalent amb registry)
- Mètode públic per llistar totes les settings amb metadata (nom, default, descripció, tipus, validacions)
- Tota env var nova s'afegeix **una sola vegada** al `core/config.py` i automàticament queda disponible al panell admin

#### Cross-checks

- **Àrea 09 pas 9.3** — la taula del Dev és la "vista" del registry; han de ser coherents
- **Àrea 08 pas 8.5** — el lifespan llegeix env vars **via** `core.config` (no `os.getenv` directe)
- **Tots els consumidors** (lifespan, tray, plugins, middleware) — han de cridar `core.config` no llegir env vars directament
- **TODO item 16 futur:** quan existeixi el panell admin, integració amb aquest registry

#### Beneficis col·laterals

- Validació al startup (pydantic-settings la fa gratis)
- Documentació automàtica generable des del registry
- Tests més fàcils (settings com a fixture)
- Menys risc de typos a env var names (constants tipades)

**Data aplicació:** pendent
**Responsable:** pendent
**Notes post-aplicació:** [buit]
**Cross-ref:** [[nat/dev/server-nexe/diari/mega-test/areas/09-config-xarxa]] pas 9.6 + decisió Jordi 2026-04-08

---

### 16. 🏛️ Estàndard plugin UI — paritat funcional 5 backends + marc per plugins futurs

**Pendent — 🟢 POST-RELEASE v0.9.1+** — `plugins/{mlx,llama_cpp}_module/{ui,languages}/` + `nat/dev/plugins-nexe/GUIA-PLUGINS.md`

**Detectat:** repàs mega-test àrea 10/11, 2026-04-08
**Severitat inicial:** 🔴 P0 BLOQUEJANT pre-mega-test
**Severitat revisada (Jordi 2026-04-08):** 🟢 **POST-RELEASE — NO bloca v0.9.0**
**Decisió Jordi 2026-04-08 (literal):** *"bloca perquè vull crear un estàndard. Cada plugin serà especial i explicarà la tecnologia... podrà tenir funcionalitats: en el cas dels backends podem posar per descarregar nous models, gestionar, o fins i tot tenir informació detallada de cada cosa, i un assistent només per això."*

**Aclariment Jordi 2026-04-08 (revisió):** *"deixa estar els plugins i les UI per ara, apunta com a TODO però després del release. Ara poden ser simples o no tenir res. Quan portem el module_manager allà vindrà la txitxa."*

**Per què el canvi de severitat:** la paritat UI completa només té sentit **quan existeixi el `module_manager`** al server, perquè aquest serà el plugin que orquestrarà les UIs (apagar/encendre, entrar a cada panel, navegar entre plugins). Sense module_manager, paritzar les UIs ara seria treball en va — no hi hauria orquestrador per consumir-les. **Decisió correcta:** primer migrar `module_manager` (post-release v0.9.1+), i en aquell moment fer la paritat completa de les UIs de tots els plugins.

#### Visió estàndard

**Cada plugin de server-nexe = experiència completa + autocontinguda.** NO només API backend. La UI pròpia és **part del valor del plugin**, no un extra.

**Per a backends LLM (mlx_module, llama_cpp_module, ollama_module):**
- 📥 **Descarregar nous models** des del propi panel del plugin
- 🛠️ **Gestionar models** (esborrar, actualitzar, info detallada)
- 📊 **Informació detallada** de la tecnologia (memòria GPU, throughput, càrrega, capacitats)
- 🤖 **Assistent IA propi** del plugin contextualitzat per ajudar amb la tecnologia específica
- 🌐 **i18n complet** 3 idiomes (ca-ES, es-ES, en-US)

**Per a plugins de tipus diferent** (futurs `document_loader`, `research`, `prompt_manager`, `doctor`, etc.):
- Cada un té el seu propi panel/dashboard
- Cada un explica què fa, com es configura, què exposa
- Cada un pot tenir el seu propi assistent contextualitzat

#### Estat actual (verificat empíricament 2026-04-08)

| Plugin | `languages/` | `ui/` | UI funcional | Estat |
|---|---|---|---|---|
| ollama_module | ✅ ca-ES + es-ES + en-US (`common.json`) | ✅ `index.html` + `assets/js/status.js` | ✅ pàgina d'estat | **REFERÈNCIA** |
| mlx_module | ❌ buida | ❌ només `assets/` buida | ❌ | 🔴 PENDENT |
| llama_cpp_module | ❌ buida | ❌ només `assets/` buida | ❌ | 🔴 PENDENT |
| security | ⏳ a verificar | ⏳ a verificar | ⏳ | ⏳ |
| web_ui_module | ✅ chat principal (cosa diferent) | ✅ chat principal | ✅ chat principal | ⚠️ no és UI de plugin sinó UI core |

**Inconsistència visible per l'usuari final:** un usuari amb Ollama veu el seu panel; un usuari amb MLX o llama.cpp no veu res. Mateix producte, experiència fragmentada → percepció amateur.

#### Acció

**Fase 1 — Definir estàndard a `GUIA-PLUGINS.md`:**

Afegir secció nova "Estàndard UI per plugin" amb:
- Estructura mínima requerida (`ui/index.html` + `ui/assets/`)
- Patrons recomanats per tipus de plugin (backend, core, web, futures categories)
- Template de `status.js` reutilitzable
- Patró d'i18n (`languages/{ca-ES,es-ES,en-US}/common.json`)
- Com el server descobreix i serveix la UI del plugin
- Què passa si un plugin no té UI (graceful degradation)
- Exemple complet basat en `ollama_module/ui/`

**Fase 2 — Paritzar mlx_module amb ollama_module:**

Construir `mlx_module/ui/index.html` + `mlx_module/ui/assets/js/status.js` amb:
- Pàgina d'estat MLX (memòria unified, models carregats, latència)
- Botons descarregar/gestionar models MLX
- Info backend (chip Apple Silicon detectat, capacitats Metal)
- Assistent contextualitzat per MLX (si infraestructura permet)

I `mlx_module/languages/{ca-ES,es-ES,en-US}/common.json` (paritat amb ollama).

**Fase 3 — Paritzar llama_cpp_module:**

Igual que mlx, però per a llama.cpp:
- Pàgina d'estat (models GGUF, quantitzacions disponibles)
- Botons descarregar/gestionar models GGUF
- Info backend (Metal, threads, capa GPU)
- Assistent contextualitzat per llama.cpp

I el seu `languages/`.

**Fase 4 — Cross-check security i web_ui_module:**

- `security` — té UI? Hauria de tenir-la? Si sí, paritzar
- `web_ui_module` — distingir clarament: és UI **core** del chat, NO UI de plugin estàndard. Documentar la diferència.

**Fase 5 — Documentar l'estàndard a `plugins-nexe`:**

Quan el repàs acabi i passem resultats a `plugins-nexe`, l'estàndard ha d'estar documentat com a contracte obligatori per a tots els plugins futurs. Tots els 21 plugins en desenvolupament a `plugins-nexe/plugins/` han de complir-lo.

#### Verificació mega-test

- **Àrea 10 pas 10.10** — verificar UI pròpia present per a cada plugin (sub-ítem nou)
- **Àrea 10 pas 10.11** — verificar que `GUIA-PLUGINS.md` documenta l'estàndard UI
- **Àrea 11** — comparar paritat funcional dels 5 plugins (matriu UI)
- **Àrea 17** — i18n del plugin coherent amb i18n general
- **Àrea 18** — UI del web_ui core no contamina UI dels plugins
- **Àrea 22** — DMG instal·lat: cada plugin mostra el seu panel correctament

#### Beneficis

- Plug-and-play complet (API + UI, no només API)
- Coherència de producte (mateix nivell qualitat per tots els backends)
- Marc clar per a plugins futurs (contracte explícit)
- Assistent específic per tecnologia → millor onboarding usuari
- Diferenciació amb competència (panel per backend és UX premium)

#### Cross-refs

- **Item 5** (icona system tray) — relacionat però no és el mateix
- **Item 9** (Tray .app bundle) — relacionat amb percepció Mac native
- **Àrea 10/11** del mega-test
- **plugins-nexe** GUIA-PLUGINS — destinatari final de l'estàndard
- **`module_manager` futur** (decisió Jordi 2026-04-08): plugin tipus manager que ja existeix a `plugins-nexe/plugins/module_manager/`. Quan arribi al server-nexe podrà:
  - Apagar/encendre plugins on-the-fly
  - **Entrar a la UI de cada plugin** (consumirà l'estàndard d'aquest item 16)
  - Gestionar lifecycle dels plugins
  - Reports `nat/dev/plugins-nexe/reports/plugins_normalitzacio_informe_2026-04-06.md` i `managers_dependencies_informe_2026-04-06.md`
- **Auditor existent `plugins/architecture/audit_dependencies.py`** a plugins-nexe — valida 18 plugins, errors=0. Eina reusable per al mega-test (cross-check àrea 11)
- **Categorització plugins** (de plugins-nexe `manager_functional_map.toml`): managers / funcionals / interfície — defineix qui necessita UI i de quin tipus

#### Velocitat d'execució (decisió Jordi)

*"Si està ben fet, fer-ho ha de ser ràpid"* — l'estàndard ben definit hauria de permetre paritzar mlx i llama_cpp amb ollama de manera ràpida (template + adaptar). El temps real dependrà del bon disseny del template a la GUIA-PLUGINS, no de la implementació.

**Data aplicació:** pendent
**Responsable:** pendent (probablement sessió dedicada post-mega-test)
**Notes post-aplicació:** [buit]

---

### 17. 🚨 Bug MEM_SAVE — pipeline rebutja contingut, no guarda res

**✅ RESOLT — `94cbf10` (2026-04-08)** — Bloc 2 Security & Memory Pipeline. is_mem_save=True passa correctament al servei. MEM_SAVE funcional.

**Detectat:** smoke test director B.4-B.8 2026-04-08 (post-refactor `personal_memory`)
**Severitat:** 🔴 P0 BLOQUEJANT — sense MEM_SAVE funcional, **server-nexe és un Ollama més**
**Decisió Jordi 2026-04-08 (literal):** *"doncs també apunta com a TODO per guardar, per això no funciona bé, el test no està guardant enlloc."*

#### Problema

El smoke test runtime del director B.4-B.8 (2026-04-08) va detectar que `POST /v1/memory/store` amb body `{content: "test ...", collection: "personal_memory"}` retorna:

```json
{
  "success": false,
  "message": "Content rejected by pipeline"
}
```

**Resultat:** **NO es guarda res** a la collection `personal_memory`. La memòria personal del chat (MEM_SAVE) **està trencada** per a qualsevol contingut que dispari el filtre.

#### Hipòtesi inicial (B.4-B.8)

> *"Probablement filtre auto-save (la paraula 'test' pot disparar el detector de brossa)."*

Però **NO confirmat empíricament** — pot ser que el filtre rebutgi MÉS coses que només la paraula "test". Cal investigar exactament què rebutja el pipeline.

#### Impacte funcional

- ❌ MEM_SAVE des del chat web no funciona per a contingut filtrat
- ❌ La metàfora "biblioteca-passadissos" queda mig-trencada (el passadís Memory no rep llibres nous)
- ❌ La diferenciació pública del server-nexe vs Ollama queda anul·lada
- ❌ El refactor B.3-B.8 personal_memory queda **incomplet en producció** (collection existeix però no rep dades reals)

#### Acció

**Fase 1 — Diagnòstic empíric (cirurgia dedicada):**

1. Localitzar el pipeline de filtres que rebutja el contingut
   ```bash
   grep -rn "Content rejected by pipeline\|Content rejected" core/ memory/ plugins/web_ui_module/
   ```
2. Identificar quin filtre dispara (filtre brossa, filtre paraules, filtre validació, etc.)
3. Reproduir el bug amb diferents inputs:
   - Contingut amb paraula "test" → rebutjat?
   - Contingut sense "test" però breu → rebutjat?
   - Contingut llarg neutral → rebutjat?
   - Contingut tècnic real (cas d'ús real) → rebutjat?

**Fase 2 — Decisió:**

- **Opció A — Suavitzar el filtre**: si rebutja massa coses, fer-lo menys agressiu (whitelist en comptes de blacklist, threshold més alt, etc.)
- **Opció B — Documentar el filtre**: si la lògica és correcta, exposar-la a l'usuari (UI mostra "Aquest contingut ha estat rebutjat per [motiu]" en comptes d'error críptic)
- **Opció C — Bypass per al chat**: el chat web pot tenir un canal directe sense filtre (autoritzat) i el filtre només aplica a ingest extern (uploads)
- **Opció D — Combinació A+B**: suavitzar + documentar

**Fase 3 — Test regression:**

- `tests/test_memory_save_pipeline.py` (nou) que cobreixi:
  - Contingut amb "test" → ha de PASS (smoke test no hauria de petar)
  - Contingut buit → REJECT explícit
  - Contingut llarg vàlid → PASS
  - Contingut maliciós (XSS, prompt injection) → REJECT explícit amb missatge clar

#### Reproducció (smoke test director B.4-B.8)

```bash
curl -X POST http://127.0.0.1:9119/v1/memory/store \
  -H "Content-Type: application/json" \
  -d '{
    "content": "test memory content from smoke test",
    "collection": "personal_memory"
  }'
```

**Resultat actual:**
```json
{"success": false, "message": "Content rejected by pipeline"}
```

**Resultat esperat post-fix:**
```json
{"success": true, "id": "...", "collection": "personal_memory"}
```

#### Verificació mega-test (àrea 12 pas 12.8)

L'àrea 12 del mega-test verifica empíricament que MEM_SAVE flux complet funciona. Aquest bug el confirmarà quan s'executi al Run real.

#### Cross-refs

- **Àrea 12 pas 12.8** — MEM_SAVE flux (BLOCKER P0)
- **Àrea 11 pas 11.E** — `web_ui_module` post-refactor
- **Diari B.4-B.8 finding** — `2026-04/20260408/20260408_tancament_refactor_b4_b8.md` secció smoke test runtime
- **Refactor B.3-B.8 `personal_memory`** — refactor sintàctic complet però **funcionalment trencat** en producció

#### Per què bloca v0.9.0

Decisió Jordi 2026-04-08: *"Aquest igual que els plugins és bloquejant. Si això no funciona és un Ollama més."*

La memòria conversacional (MEM_SAVE/RECALL) és una de les **tres features diferenciadores** del server-nexe vs alternatives genèriques (Ollama, LM Studio, etc.). Sense MEM_SAVE funcional, l'usuari no pot:
- Guardar context entre converses
- Construir memòria personal a llarg termini
- Beneficiar-se del passadís Memory de la metàfora biblioteca

**No es pot llançar v0.9.0 amb aquest bug obert.**

**Data aplicació:** pendent
**Responsable:** pendent (cirurgia dedicada urgent)
**Notes post-aplicació:** [buit]
**Cross-ref diari:** [[nat/dev/server-nexe/diari/2026-04/20260408/20260408_tancament_refactor_b4_b8|Tancament refactor B.4-B.8]] secció smoke test runtime + [[nat/dev/server-nexe/diari/2026-04/20260408/20260408_pre_megaauditoria_estat_post_refactor|Pre-mega-auditoria]] secció finding

---

## Estat global

| # | Ítem | Estat | Severitat | Data | Notes |
|---|------|-------|-----------|------|-------|
| 1 | Swift wizard RAM tiers (7 del blog) | ⚪ pendent | 🔴 P0 | — | — |
| 2 | Catàleg models actualitzat | ⚪ pendent | 🔴 P0 | — | depèn ítem 1 |
| 3 | GUI instal·la CLI | ⚪ pendent | 🔴 P0 | — | — |
| 4 | Icona al logger | ⚪ pendent | 🟡 P1 | — | — |
| 5 | Icona system tray | ⚪ pendent | 🟡 P1 | — | — |
| 6 | Icona Dock/Applications | ⚪ pendent | 🟡 P1 | — | — |
| 7 | Baixar models al SSD (govern/secret) | ⚪ pendent | 🔴 P0 | — | afegit TODO_INBOX global |
| **8** | **RAM monitor confús (RSS Python ≠ model)** | ⚪ pendent | 🟡 P1 | — | mega-test àrea 07, 2026-04-08 |
| **9** | **Tray "Python" a Force Quit — .app bundle propi** | ⚪ pendent | 🔴 **P0** | — | promogut v0.9.1→v0.9.0; captura Jordi |
| **10** | **LoginItem auto-arrencada (default OFF)** | ⚪ pendent | 🟡 P1 | — | toggle ja existeix Swift wizard |
| **11** | **Centralització arrencada — tray única via** | ⚪ pendent | 🔴 **P0** | — | origen arrel bugs Track B #1 |
| **12** | **Single instance hard enforcement** | ⚪ pendent | 🔴 **P0** | — | depèn item 11; PID file ja parcial |
| **13** | **i18n complet tray (3 idiomes)** | ⚪ pendent | 🟡 P1 | — | tray_translations.py parcial |
| **14** | **Tray "Quit" no mata server pare (Bug #14)** | ✅ resolt | 🔴 **P0** | 2026-04-09 | `b44645b` Bloc B Lifespan + PID |
| **15** | **`core/config.py` registry pattern (futur panell admin)** | ✅ resolt | 🔴 **P0** | 2026-04-08 | `c926555` NexeSettings + pydantic-settings |
| **16** | **🏛️ Estàndard plugin UI — paritat 5 backends + marc plugins futurs** | ⚪ pendent | 🟢 **POST-RELEASE** | — | decisió Jordi 2026-04-08 revisada — esperar arribada `module_manager` v0.9.1+ |
| **17** | **🚨 Bug MEM_SAVE — `Content rejected by pipeline` no guarda res** | ✅ resolt | 🔴 **P0 BLOQUEJANT release** | 2026-04-08 | `94cbf10` Bloc 2 Security & Memory |

Símbols:
- ⚪ pendent
- 🟡 en curs
- ✅ completat
- ❌ bloquejat

---

## Com funciona amb el mega-test

1. **El Dev àrea 03** del mega-test llegeix aquest fitxer
2. Per cada ítem, verifica empíricament l'estat al codi/bundles
3. Apunta al report de l'àrea 03 l'estat actual (⚪/🟡/✅/❌)
4. Si un ítem és ✅, verifica que el test de verificació descrit passa
5. **El Dev NO aplica els canvis** — només verifica + apunta (regla absoluta)

Quan una sessió dedicada aplica un ítem:
1. Fa els canvis al codi
2. Actualitza aquest fitxer (estat + data + notes)
3. Re-executa l'àrea 03 del mega-test per confirmar
4. Un cop tots els 6 ítems són ✅ → pre-release desbloquejat

---

### 18. 🔌 Substituibilitat Qdrant — Protocol VectorStore declarat però no implementat

**✅ RESOLT — `4728e1a` + `43ab9dd` (2026-04-08)** — imports durs qdrant_client migrats a TYPE_CHECKING guard. VectorStore Protocol documentat a ARCHITECTURE.md.

**Decisió Jordi 2026-04-08 nit (literal):** *"si ha de ser fàcilment substituïble igual que els transformers i els embeddings... entenc que no és plug & play però que no sigui un maldecap... també documentar"*

**Resolució:** **Pre-release confirmat.** Mateix nivell que embeddings/transformers — no plug & play, però el camí ha d'estar **documentat clarament** perquè algú que vulgui canviar Qdrant per (ex) Weaviate o Chroma no s'hagi d'arrancar els cabells. **Acció afegida obligatòria:** secció nova al `knowledge/{ca,en,es}/ARCHITECTURE.md` (o similar) amb el procediment "Com canviar el vector store" — anàleg al que ja documentem per embeddings.

**Detectat:** revisió profunda àrea 12 vigilant Director Repàs 2026-04-08
**Severitat:** 🔴 P0 PRE-RELEASE — sense substituibilitat real, **server-nexe és un Ollama més** (decisió Jordi 2026-04-08)
**Decisió Jordi 2026-04-08 (literal):** *"si això no funciona és un Ollama més... cada part substituïble sense gran avalot. La biblioteca (Qdrant) ha de poder canviar-se per un altre vector store."*

#### Problema

El **Protocol `VectorStore` existeix** com a contracte arquitectònic:
```
memory/embeddings/core/vectorstore.py:101  →  class VectorStore(Protocol):
```

**Però NO es fa servir.** Els consumidors de `memory/memory/` fan **import directe de `qdrant_client`** en lloc d'usar el Protocol. Verificat empíricament 2026-04-08:

| Fitxer | Línia | Import dur |
|---|---|---|
| `memory/memory/storage/vector_index.py` | 43, 97, 147, 180 | `from qdrant_client.models import ...` (4 cops) |
| `memory/memory/engines/persistence.py` | 22, 23 | `from qdrant_client import QdrantClient` + models |
| `memory/memory/api/documents.py` | 20, 21 | `from qdrant_client import QdrantClient` + models |
| `memory/memory/api/__init__.py` | 19 | `from qdrant_client import QdrantClient` |
| `memory/memory/api/collections.py` | 17 | `from qdrant_client import QdrantClient` |

**Total: 10 imports durs** de `qdrant_client` dins `memory/memory/`.

**A més:** **NO existeix `QdrantAdapter`** (ni cap classe que implementi el Protocol amb Qdrant). El find buit:
```bash
find memory/embeddings -name "*qdrant*" -type f
# (buit)
```

#### Diagnòstic vigilant

**Dissonància estructural** entre 2 sub-mòduls de `memory/`:
- `memory/embeddings/` → té el Protocol (declaratiu, abstracte)
- `memory/memory/` → té els imports durs Qdrant (real, hardcoded)

La substituibilitat existeix **només en teoria** (Protocol declarat) però **no en pràctica** (consumidors fan import directe).

#### Impacte funcional

- ✅ El sistema **funciona perfectament amb Qdrant** ara mateix (cap regressió)
- ❌ **Si demà cal canviar Qdrant** per (ex) Weaviate/Chroma/Milvus → cal **tocar els 10 imports** + crear adapter manualment + canviar la lògica de cada `vector_index.py`/`persistence.py`/etc.
- ❌ **La promesa "substituïble per disseny" del v0.9.0 queda incomplerta** — segons la decisió Jordi 2026-04-08, és un dels pilars de "no Ollama més"
- ❌ **Tests amb `MockVectorStore`** (al Protocol) NO testegen el flux real (els tests passen però la realitat usa Qdrant directe)

#### Acció

**Fase 1 — Diagnòstic complet (cirurgia dedicada):**

1. Llegir tots els 10 imports a `memory/memory/` per entendre quins mètodes Qdrant s'usen exactament
2. Verificar si el Protocol `VectorStore` cobreix tots aquests mètodes (pot ser que falti `add_vectors`, `search`, `delete`, `health`, `query_filter`, etc.)
3. Identificar gaps entre Protocol vs ús real

**Fase 2 — Crear `QdrantAdapter`:**

1. Crear `memory/embeddings/adapters/qdrant_adapter.py` que implementa `VectorStore` Protocol completament
2. Wrapper sobre `QdrantClient` exposant els mètodes del Protocol
3. Tests amb el Protocol real (no només `MockVectorStore`)

**Fase 3 — Migrar consumidors:**

1. `memory/memory/storage/vector_index.py` → usar `VectorStore` injectat en lloc de `qdrant_client.models` directe
2. `memory/memory/engines/persistence.py` → usar `VectorStore` per al CRUD
3. `memory/memory/api/documents.py` → usar `VectorStore`
4. `memory/memory/api/__init__.py` + `collections.py` → usar `VectorStore`
5. Mantenir compat layer si calgut

**Fase 4 — Validació:**

1. Tests F8 segueixen passant (singleton + pool intactes)
2. Tests memory passen (4396 baseline)
3. `MockVectorStore` substitueix Qdrant en runtime real (chaos test del Hacker Nexe)
4. Creació de 2n adapter mock (ChromaAdapter o similar) com a prova de concepte

#### Estimació esforç

Cirurgia mitjana: ~4-8h de feina seriosa (Phase 1: 1h, Phase 2: 2h, Phase 3: 3-4h, Phase 4: 1-2h). **NO és refactor gros** perquè el Protocol ja existeix — només cal la implementació + migració dels consumidors.

#### Notes

- **NO bloca el repàs del mega-test** (el Dev pot continuar revisant àrees)
- **SÍ bloca el push del release v0.9.0** — Jordi 2026-04-08 confirma "candidat a TODO pre-release"
- Cross-check 12.3 (Dev) + auditor 12.3 (Hacker Nexe chaos `chaos_qdrant_swap_mock.py`)
- **Mai fer el rollback al Qdrant directe** un cop migrat — la substituibilitat ha de quedar real

---

### 19. 🚨 Memory-injection via API directe — `core/endpoints/chat.py` no aplica `strip_memory_tags`

**✅ RESOLT — `94cbf10` (2026-04-08)** — strip_memory_tags afegit a /v1/chat/completions. Bloc 2.

**Detectat:** revisió profunda àrea 15 vigilant Director Repàs 2026-04-08
**Severitat:** 🔴 P0 PRE-RELEASE — vulnerabilitat sec real, contamina passadís Memory
**Decisió Jordi 2026-04-08:** *"NASA / militar / extraterrestre... local + monousuari NO és excusa per saltar-se sec"*

#### Problema

El POST `/v1/chat/completions` (API directe sense passar pel UI web) **NO aplica `strip_memory_tags`** al missatge d'usuari. Verificat empíricament 2026-04-08:

```bash
$ grep -n "strip_memory_tags" core/endpoints/chat.py
(buit — 0 hits)
```

**Diferència crítica:**

| Path d'entrada | Aplica `strip_memory_tags`? |
|---|---|
| Web UI chat (`plugins/web_ui_module/api/routes_chat.py:212`) | ✅ SÍ |
| API directe (`core/endpoints/chat.py`) | ❌ **NO** |

#### Impacte funcional

- ❌ Un usuari (o client tercer) que crida `/v1/chat/completions` directament pot enviar `[MEM_SAVE: contingut maliciós]` al missatge
- ❌ El tag arriba al pipeline LLM/memory sense ser strippejat → el LLM podria interpretar-ho com a instrucció de guardar memòria
- ❌ Memory-injection via API directe → contaminació del passadís `personal_memory`
- ❌ El web UI està protegit, l'API no — **inconsistència de defensa**

#### Acció

**Cirurgia simple (~30 min):**

1. Importar `strip_memory_tags` a `core/endpoints/chat.py`:
   ```python
   from plugins.security.core.input_sanitizers import strip_memory_tags, validate_string_input
   ```
2. Aplicar `strip_memory_tags` al `_msg.content` abans de qualsevol processament (mateix patró que `routes_chat.py:212`)
3. Re-córrer tests: `pytest tests/test_chat_v1_validation.py plugins/security/core/tests/test_mem_save_strip.py -v`
4. Cross-check 15.7 + 12.X (refactor `personal_memory`)

#### Quan

**Pre-release v0.9.0** — abans del push.

---

### 20. 🚨 Prompt-injection via ingest knowledge — `core/ingest/` no aplica `_filter_rag_injection`

**✅ RESOLT — `94cbf10` (2026-04-08)** — _filter_rag_injection aplicat a ingest_knowledge.py + ingest_docs.py. Bloc 2.

**Detectat:** revisió profunda àrea 15 vigilant Director Repàs 2026-04-08
**Severitat:** 🔴 P0 PRE-RELEASE — vulnerabilitat prompt-injection via document corpus

#### Problema

Els 36 fitxers de `knowledge/{ca,es,en}/` que s'ingesten al startup mitjançant `core/ingest/ingest_knowledge.py` **NO passen pel filtre `_filter_rag_injection`**. Verificat empíricament 2026-04-08:

```bash
$ grep -rn "_filter_rag_injection\|_sanitize_rag_context" --exclude-dir="__pycache__" core/ingest/
(buit — 0 hits)
```

**Diferència crítica:**

| Path d'ingest | Aplica `_filter_rag_injection`? |
|---|---|
| Upload PDF/MD via web UI (`plugins/web_ui_module/api/routes_files.py:124`) | ✅ SÍ |
| Ingest knowledge auto-startup (`core/ingest/ingest_knowledge.py`) | ❌ **NO** |
| Ingest docs corporate (`core/ingest/ingest_docs.py`) | ❌ **NO** |

#### Impacte funcional

- ❌ Si algun fitxer de `knowledge/{ca,es,en}/` conté patrons com `[INST]`, `<|system|>`, `<|user|>`, `### system`, "ignore previous instructions" → el LLM els llegirà com a **instruccions vàlides** quan els recuperi via RAG
- ❌ Contaminació del passadís `nexe_documentation` amb injeccions latents
- ❌ Especialment perillós perquè els fitxers `knowledge/` són **font interna** (els hem escrit nosaltres) i podrien tenir-ne sense voler (ex: documentar com es defensa contra prompt-injection requereix exemples literals)
- ❌ El path d'upload UI està protegit, l'auto-ingest no — **inconsistència de defensa**

#### Acció

**Cirurgia simple (~1h):**

1. Importar `_filter_rag_injection` a `core/ingest/ingest_knowledge.py` i `ingest_docs.py`:
   ```python
   from core.endpoints.chat_sanitization import _filter_rag_injection
   ```
2. Aplicar `_filter_rag_injection` al contingut de cada chunk **abans** d'embed-lo
3. Re-córrer tests: `pytest core/ingest/tests/ core/endpoints/tests/test_rag_sanitization.py -v`
4. Verificar empíricament que els 36 fitxers `knowledge/` no contenen patrons literals (auditoria del corpus)
5. Cross-check 15.8 + 12.X (RAG sanitization)

#### Quan

**Pre-release v0.9.0** — abans del push.

---

### 21. 🚨 False sense of security — `lifespan.py` no comprova `SQLCIPHER_AVAILABLE`

**✅ RESOLT — `94cbf10` (2026-04-08)** — SQLCIPHER fail-closed: RuntimeError si encryption sol·licitada però sqlcipher3 absent. Bloc 2.

**Detectat:** revisió profunda àrea 16 vigilant Director Repàs 2026-04-08
**Severitat:** 🔴 P0 PRE-RELEASE — vulnerabilitat de "false sense of security" segons estàndard NASA/militar Jordi

#### Problema

Si l'usuari activa l'encriptació at-rest amb `NEXE_ENCRYPTION_ENABLED=true` però NO té `sqlcipher3` instal·lat:

1. `lifespan.py:130` `crypto_enabled = True` ✓
2. `lifespan.py:140` `CryptoProvider()` instanciat ✓
3. **`lifespan.py` declara "encryption ENABLED"** sense comprovar `SQLCIPHER_AVAILABLE`
4. `persistence.py:172-174` emet warning *"CryptoProvider provided but sqlcipher3 not installed. Database will NOT be encrypted"*
5. Sessions SÍ encriptades (SessionManager via crypto provider)
6. **Database `memories.db` SENSE encriptar** però l'usuari creu que sí

**Verificat empíricament 2026-04-08:**
```bash
$ grep -n "SQLCIPHER_AVAILABLE" core/lifespan.py
(buit — 0 hits)
```

**`core/lifespan.py` NO comprova `SQLCIPHER_AVAILABLE`** abans de declarar `crypto_enabled=True`.

#### Impacte funcional

- ❌ L'usuari activa encryption pensant que tot està encriptat
- ❌ Les sessions sí ho són, però la DB de memòries NO
- ❌ El warning del log es perd si l'usuari no llegeix els logs
- ❌ NASA/militar standard requereix **fail-closed** o avís user-facing immediat
- ❌ Decisió Jordi 2026-04-08: *"NASA / militar / extraterrestre"* — un warning al log NO és prou

#### Acció

**Cirurgia ràpida (~30 min):**

1. Importar `SQLCIPHER_AVAILABLE` a `core/lifespan.py`:
   ```python
   from memory.memory.engines.persistence import SQLCIPHER_AVAILABLE
   ```
2. Afegir check abans de declarar enabled:
   ```python
   if crypto_enabled and not SQLCIPHER_AVAILABLE:
       logger.error(
           "Encryption requested but sqlcipher3 not installed. "
           "Database will NOT be encrypted. Set NEXE_ENCRYPTION_ENABLED=false "
           "or install sqlcipher3 to fix this."
       )
       # Decisió Jordi: fail-closed o downgrade?
       # Opció A (estricte NASA): raise RuntimeError("sqlcipher3 required for encryption")
       # Opció B (graceful): crypto_enabled = False + warning user-facing
   ```
3. Re-córrer tests: `pytest core/tests/test_crypto_lifespan.py -v`
4. Cross-check 16.5 + 16.4

#### Decisió Jordi 2026-04-08 nit — OPCIÓ A (fail-closed estricte)

**Cita Jordi (literal):** *"21, A. important no??"*

**Resolució:** **Opció A — Fail-closed estricte**. Si encryption demanada però sqlcipher3 falta, el server **NO arrenca** i mostra error clar. Coherent amb estàndard NASA/militar — no acceptem "false sense of security".

**Implementació:**
```python
# core/lifespan.py — afegir abans del CryptoProvider() init:
from memory.memory.engines.persistence import SQLCIPHER_AVAILABLE

if crypto_enabled and not SQLCIPHER_AVAILABLE:
    raise RuntimeError(
        "Encryption at rest requested (NEXE_ENCRYPTION_ENABLED=true) "
        "but sqlcipher3 is not installed. The server will NOT start to avoid "
        "a false sense of security. Either:\n"
        "  (1) Install sqlcipher3: pip install sqlcipher3-binary\n"
        "  (2) Disable encryption: NEXE_ENCRYPTION_ENABLED=false"
    )
```

#### Quan

**Pre-release v0.9.0** — abans del push.

---

### 22. 🚨 Workflows declaratiu sense implementació — stub 501 Not Implemented

**✅ RESOLT — `94cbf10` (2026-04-08)** — workflows.py stub 501 + metadata status="stub-v0.9.1". Bloc 2.

**Detectat:** revisió profunda àrea 17 vigilant Director Repàs 2026-04-08
**Severitat:** 🔴 P0 PRE-RELEASE — declaració falsa al metadata `/v1/`
**Decisió Jordi 2026-04-08 nit:** *"el workflow és funcionalitat futura, podem posar-ho com a després del llançament... el que pots fer és l'opció B, deixa només 501 i així ho tenim preparat"*

#### Problema

`core/endpoints/v1.py:36-40` declara als metadata del `v1_root`:

```python
"workflows": {
    "base": "/v1/workflows",
    "status": "implemented",  # ← FALS
    ...
}
```

Però **NO existeix cap `workflows_router`** ni cap `include_router` per workflows. Verificat empíricament 2026-04-08:

```bash
$ grep -rnE "workflows.*router|router.*workflows|/v1/workflows" core/ plugins/ memory/
core/endpoints/v1.py:36-40  ← única declaració metadata
```

**Conseqüència:**
- Un client llegint `/v1/` veurà workflows com a "implementat"
- Però qualsevol crida a `/v1/workflows/*` retorna **404 Not Found**
- Declaració falsa = problema documental + funcional + percepció amateur

#### Decisió Jordi 2026-04-08 nit — Opció B

> *"el que pots fer és l'opció B, deixa només 501 i així ho tenim preparat"*

**El workflow engine real és post-release** (3-4 mesos) — apuntat a `TODO-postrelease.md`. Mentrestant, **stub 501 Not Implemented** consistent amb la declaració metadata.

#### Acció

**Cirurgia ràpida (~15 min):**

1. Crear `core/endpoints/workflows.py` amb stub:
   ```python
   from fastapi import APIRouter, HTTPException
   
   router_workflows = APIRouter(prefix="/v1/workflows", tags=["v1", "workflows"])
   
   @router_workflows.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
   async def workflows_not_implemented(path: str):
       """Stub Not Implemented — workflow engine planejat post-release v0.9.1+"""
       raise HTTPException(
           status_code=501,
           detail="Workflow engine not yet implemented. Planned for v0.9.1+ (3-4 months post-launch)."
       )
   ```

2. Afegir `include_router` a `core/endpoints/v1.py`:
   ```python
   try:
       from .workflows import router_workflows
       router_v1.include_router(router_workflows)
   except ImportError:
       pass
   ```

3. Actualitzar `v1_root` metadata `workflows.status` de `"implemented"` a `"stub"` o `"planned-v0.9.1"`

4. Re-córrer tests: `pytest core/endpoints/tests/test_v1.py -v`

5. Cross-check 17.3 + decisió Jordi workflow engine post-release

#### Quan

**Pre-release v0.9.0** — abans del push. Cirurgia ràpida (~15 min).

#### Cross-ref

- **`TODO-postrelease.md`** item nou: Workflow engine real (3-4 mesos post-launch)
- Memòria: `project_workflow_engine_futur` (visió llarg termini Jordi)

---

### 23. ✅ RESOLT PER ITEM 24 — Auth bypass plugin endpoints `/mlx/chat` + `/llama-cpp/chat`

**Resolt per item 24 (decisió Jordi 2026-04-08 nit):** com que item 24 elimina els endpoints `/mlx/chat`, `/llama-cpp/chat`, `/ollama/api/chat`, ja no cal afegir-los auth — desapareixen del codi. **Vegeu item 24 per la cirurgia.**

**Pendent (resolt per item 24)** — `plugins/mlx_module/api/routes.py:41` + `plugins/llama_cpp_module/api/routes.py:34`

**Detectat:** revisió profunda àrea 18 vigilant Director Repàs 2026-04-08
**Severitat:** 🔴 P0 PRE-RELEASE — vulnerabilitat sec NASA/militar Jordi
**Decisió Jordi 2026-04-08:** *"NASA / militar / extraterrestre... local + monousuari NO és excusa per saltar-se sec"*

#### Problema

Els plugins `mlx_module` i `llama_cpp_module` exposen endpoints `/chat` directes **sense API key**. Verificat empíricament 2026-04-08:

| Endpoint | Fitxer:línia | Auth |
|---|---|---|
| `/mlx/chat` | `plugins/mlx_module/api/routes.py:41` `@router.post("/chat")` | ❌ **SENSE auth** |
| `/llama-cpp/chat` | `plugins/llama_cpp_module/api/routes.py:34` `@router.post("/chat")` | ❌ **SENSE auth** |
| `/ollama/api/chat` | `plugins/ollama_module/api/routes.py:120` | ✅ `Depends(require_api_key)` |

**Asimetria crítica:** ollama TÉ auth, mlx i llama_cpp NO. **Inconsistència de seguretat.**

**Reproducció:**
```bash
curl -X POST http://localhost:9119/mlx/chat \
     -H "Content-Type: application/json" \
     -d '{"messages": [{"role":"user","content":"hola"}]}'
# 200 OK — sense API key
```

#### Impacte funcional

- ❌ Qualsevol procés local pot accedir al backend MLX/llama_cpp sense autenticació
- ❌ Air-gapped local és menys greu, però segons NASA/militar Jordi és **inacceptable**
- ❌ Inconsistència entre plugins (asimetria suggereix oblit, no decisió)
- ❌ El cross-check 14.9 (auditor 14 sec auth) hauria d'haver-ho detectat però només va comptar "≥9 endpoints amb auth" sense inventari exhaustiu

#### Acció

**Cirurgia ràpida (~15 min):**

1. Afegir `Depends(require_api_key)` a `mlx_module/api/routes.py:41`:
   ```python
   from fastapi import APIRouter, HTTPException, Depends
   from plugins.security.core.auth import require_api_key
   
   @router.post("/chat", dependencies=[Depends(require_api_key)])
   async def chat_endpoint(request: Dict[str, Any]):
       ...
   ```

2. Afegir `Depends(require_api_key)` a `llama_cpp_module/api/routes.py:34` (mateix patró)

3. Re-córrer tests dels plugins: `pytest plugins/mlx_module/tests/ plugins/llama_cpp_module/tests/ -v`

4. **Re-executar auditor 14** retroactiu amb inventari `Depends(require_api_key)` exhaustiu (no només comptar)

#### Cross-refs

- Pas 18.12.ter (descobriment 5 endpoints, no 2)
- Cross-check fallit 14.9
- Item 24 pipeline únic trencat (cross-related)

#### Quan

**Pre-release v0.9.0** — abans del push.

---

### 24. 🚨 Pipeline únic trencat parcialment — 5 endpoints chat al server

**✅ RESOLT — `94cbf10` (2026-04-08)** — Endpoints /mlx/chat, /llama-cpp/chat, /ollama/api/chat eliminats. Pipeline únic: /ui/chat + /v1/chat/completions. Confirmat 403 per mega-consultoria real.

**Detectat:** revisió profunda àrea 18 vigilant Director Repàs 2026-04-08
**Severitat:** 🔴 P0 PRE-RELEASE arquitectònic
**Decisió Jordi 2026-04-08 nit (literal):** *"el CLI i la UI han de tenir el mateix pipeline... un sol pipeline amb endpoint que es recuperés ja que el pipeline anirà creixent"*

#### Problema

El server-nexe té **5 endpoints chat** (no 2 com esperava el prompt 18.12.ter):

| # | Endpoint | Pipeline | Auth |
|---|---|---|---|
| 1 | `/v1/chat/completions` | OpenAI-compat (Cursor/Continue/Zed) | ✅ |
| 2 | `/ui/chat` | **Canònic CLI/UI** | ✅ |
| 3 | `/mlx/chat` | Backend-direct mlx | ❌ (item 23) |
| 4 | `/llama-cpp/chat` | Backend-direct llama_cpp | ❌ (item 23) |
| 5 | `/ollama/api/chat` | Backend-direct ollama | ✅ |

Els 3 plugin endpoints permeten **saltar el pipeline únic `/ui/chat`** accedint directament al backend.

#### Decisió pendent Jordi

**Opció A — Eliminar plugin endpoints chat:**
- Forçar tothom a usar el pipeline únic `/ui/chat`
- Plugin endpoints `/chat` són legacy del refactor pre-pipeline únic
- Cirurgia mitjana ~30-60 min (eliminar codi + actualitzar tests + verificar no rompre res)
- **Pro:** pipeline únic real, sense escapatòries
- **Con:** perd debug directe per backend (eines dev)

**Opció B — Mantenir plugin endpoints + auth obligat + documentar:**
- Acceptar que els plugin endpoints són **debug/dev intencional**
- Afegir auth a tots (item 23 fa la meitat)
- Documentar al `knowledge/{ca,en,es}/API.md` com a "advanced backend-direct API for debug/dev"
- Pipeline canònic continua sent `/ui/chat`
- Cirurgia ~15 min (només auth, ja inclòs a item 23)
- **Pro:** flexibilitat dev preservada, pipeline únic seguit per l'ús normal
- **Con:** múltiples camins amb el risc d'oblidar-se d'algun fix

#### Decisió Jordi 2026-04-08 nit — OPCIÓ A (eliminar plugin endpoints chat)

**Cita Jordi (literal):** *"pipeline únic, pensa que s'afegiran moltes coses al pipeline i haurà d'aportar, no vull mantenir dos pipelines, seria un autèntic infern, no creus??? Això seria pre-release."*

**Resolució:** **Opció A — Eliminar `/mlx/chat`, `/llama-cpp/chat`, `/ollama/api/chat`** (els 3 plugin endpoints chat). El pipeline únic és `/ui/chat`. L'única altra "interfície chat" que es manté és `/v1/chat/completions` (OpenAI-compat per Cursor/Continue/Zed, decisió arquitectònica separada).

**Justificació:** el pipeline anirà creixent (workflow engine futur, MEM_SAVE, RAG, sanitization, etc.). Mantenir 2+ pipelines en paral·lel és **maldecap insostenible**.

#### Acció (Opció A confirmada)

**Cirurgia mitjana ~1-2h pre-release:**

1. **Eliminar** `@router.post("/chat")` de `plugins/mlx_module/api/routes.py:41` + funció `chat_endpoint`
2. **Eliminar** `@router.post("/chat")` de `plugins/llama_cpp_module/api/routes.py:34` + funció `chat_endpoint`
3. **Eliminar** `@router.post("/api/chat")` de `plugins/ollama_module/api/routes.py:120` + funció `chat`
4. **Re-córrer tests** dels 3 plugins: `pytest plugins/{mlx,llama_cpp,ollama}_module/tests/ -v`
5. **Verificar** que cap test trenca (si trenquen → els tests usaven plugin endpoints directes; cal migrar al `/ui/chat` o documentar com a regressió esperada)
6. **Verificar empíricament** que `/ui/chat` segueix funcionant amb tots 3 backends — cross-check 19 Bloc A
7. **Eliminar** funcions associades als plugin endpoints si no s'usen enlloc més
8. Actualitzar memòria `feedback_pipeline_unic_ui_cli.md` amb la decisió "només `/ui/chat`, 0 plugin endpoints chat"

#### Item 23 queda RESOLT per item 24

**Item 23 (auth bypass mlx/llama_cpp) queda RESOLT automàticament per item 24** — si eliminem els endpoints, no cal afegir-los auth perquè ja no existiran. Marcar item 23 com a "resolt per item 24" al moment d'aplicar la cirurgia.

#### Cross-refs

- Item 23 (auth bypass mlx + llama_cpp)
- Pas 18.12.ter (descobriment 5 endpoints)
- Memòria `feedback_pipeline_unic_ui_cli.md`
- `knowledge/{ca,en,es}/API.md:228-236` (documentació `/v1/chat/completions` separat)

#### Quan

**Pre-release v0.9.0** — junt amb item 23.

---

### 25. 🚨 Drift Q5.5 al knowledge — port 6333 + binari Qdrant a ERRORS.md + INSTALLATION.md

**✅ RESOLT — `c926555` (2026-04-08)** — Documentació Qdrant embedded actualitzada als 3 idiomes. Port 6333 i binari Qdrant eliminats.

**Detectat:** revisió profunda àrea 21 vigilant Director Repàs 2026-04-08 nit
**Severitat:** 🔴 P0 PRE-RELEASE — misleading documentation, bug d'usabilitat real
**Decisió Jordi 2026-04-08 nit (literal):** *"Pensa que això és la base per després fer les webs, ampliar nexe, fer plugins, etc. Ha d'estar al detall."*

#### Problema

El refactor Q5.5 (commit `ae30f29`) va eliminar el binari Qdrant servidor extern. server-nexe usa Qdrant **embedded** (no com a procés extern al port 6333). Però el knowledge encara documenta troubleshoot del binari + port 6333. Verificat empíricament 2026-04-08:

| Fitxer:línia | Hit (ha de canviar) |
|---|---|
| `knowledge/ca/ERRORS.md:36` | "Qdrant connection refused — Comprova el **port 6333**, reinicia el servidor amb `./nexe go`" |
| `knowledge/ca/INSTALLATION.md:172` | "Qdrant no arrenca — Comprova el **port 6333**, comprova els permisos del **binari**" |
| `knowledge/en/ERRORS.md:36` | "Qdrant connection refused — Check **port 6333**, restart server with `./nexe go`" |
| `knowledge/en/INSTALLATION.md:172` | "Qdrant won't start — Check **port 6333**, check **binary permissions**" |
| `knowledge/es/ERRORS.md:29` | "**Qdrant binary not found** — Ejecutar el instalador, o **descargar manualmente** para tu plataforma" |

#### Impacte funcional

- ❌ Un usuari amb problemes Qdrant llegirà aquesta doc i intentarà solucions IMPOSSIBLES
- ❌ Port 6333 ja no s'usa (Qdrant és embedded, no servidor extern)
- ❌ Binari Qdrant no existeix (Q5.5 commit `ae30f29` el va eliminar)
- ❌ "Descargar manualmente" no té sentit (no hi ha res a descarregar)
- ❌ **Misleading documentation = primer contacte de l'usuari amb el producte = percepció amateur**
- ❌ Quan futures IAs (Claude/GPT/Codex/Gemini) llegeixin el knowledge per ajudar l'usuari, donaran instruccions falses

#### Acció

**Cirurgia knowledge ~30 min:**

1. Per cada hit dels 5 fitxers, substituir per missatge correcte post-Q5.5:
   - **ca/ERRORS.md:36:**
     ```markdown
     | Qdrant connection refused | Qdrant embedded no s'ha inicialitzat correctament | Reinicia el servidor amb `./nexe go`. Si persisteix, mira els logs a `storage/logs/`. |
     ```
   - **ca/INSTALLATION.md:172:**
     ```markdown
     | Qdrant no arrenca | Verifica que `storage/vectors/` és escrivible i no té lock files (`*.lock`). Reinicia el servidor. |
     ```
   - Equivalents en/es traduïts coherentment
2. **Verificar** que cap altre fitxer del knowledge té referències a "binari Qdrant" / "port 6333" / "NEXE_QDRANT_HOST":
   ```bash
   grep -rnE "port 6333|binari Qdrant|Qdrant binary|NEXE_QDRANT_HOST|NEXE_QDRANT_PORT|storage/qdrant" knowledge/
   ```
3. Re-córrer auto-ingest del knowledge després dels canvis (es regenera al next boot)
4. Cross-check 21.F + cross-check item 20 (`_filter_rag_injection` que també afecta `ingest_knowledge.py`)

#### Cross-refs

- Pas 21.F del prompt àrea 21
- Cross-check item 20 (ingest_knowledge no aplica filter)
- §5.5 del CONTEXT-POST-REFACTOR-20260408 (cobertura incompleta — només verificava RAG.md + ARCHITECTURE.md)
- Refactor commit `ae30f29` Q5.5

#### Quan

**Pre-release v0.9.0** — abans del push.

---

## Notes generals

- **No-complex:** cap d'aquests ítems requereix refactor gran. Són feines de 30 min - 2h cada una. **(Excepció: ítem 18 substituibilitat Qdrant és cirurgia mitjana 4-8h.)**
- **Crític per acceptació:** la primera impressió d'un usuari DMG fresc depèn d'aquestes coses. Sense icones, GUI+CLI desconnectats, selecció vague de models → percepció amateur.
- **Abans del pre-release v0.9.0:** tots 6 han d'estar ✅ abans del `/dmg-nexe` i `/push` al release.

---

**Signat:** Jordi Goy — via Director mega-test 2026-04-08
