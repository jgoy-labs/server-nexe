---
id_ressonant: "{{NAT_ID_RESSONANT}}"
versio: "v1.0"
data: 2026-04-08
id: todo-postrelease-server-nexe
abstract: "TODOs post-release v0.9.0 server-nexe. Fitxer separat del TODO-installer-prerelease (que és per BLOCKERs del release). Aquí van les feines arquitectòniques i de deute tècnic que NO bloquegen v0.9.0 però han de fer-se després."
tags: [server-nexe, todo, postrelease, deute-tecnic, plugins-nexe, knowledge]
chunk_size: 800
priority: P2
project: server-nexe
area: dev
type: todo
estat: open
lang: ca
author: "Jordi Goy"
---

# TODO post-release v0.9.0 — server-nexe

↑ [[INDEX]]

**Propòsit:** feines pendents que **NO bloquegen el release v0.9.0** però que cal fer després per mantenir la salut arquitectònica del projecte. Separat de [[TODO-installer-prerelease]] (que és només per BLOCKERs del release).

**Quan obrir aquestes feines:** un cop el release v0.9.0 estigui out al món, abans de començar v0.9.1.

---

## 1. 🔌 Sincronitzar fàbrica `plugins-nexe` ← `server-nexe` (5 plugins normalitzats)

**Origen:** revisió profunda àrea 11 mega-test, vigilant Director Repàs 2026-04-08.

### El problema

El BUS normalització 2026-04-06 va aplicar **al server-nexe directament** (amb permís explícit Jordi) tots aquests canvis als 5 plugins de pre-release:

- **Decapitació `ollama_module`** 510→195L + 4 fitxers nous a `core/` (chat.py, client.py, models.py, errors.py) + parent binding pattern + FIXMEs Gemini documentats
- **`api/routes.py` extret** del `module.py` monolític a `mlx_module` (59L) i `llama_cpp_module`
- **`create_lazy_manifest`** propagat als manifests
- **Cas B `extra_attrs`** preservats a `security/`
- **Refactor B.3-B.8** `nexe_web_ui` → `personal_memory` a `web_ui_module/` (TOTS els `routes_*.py` afectats)
- **Cirurgia Q1.2** fix `Path.cwd()` removal a `mlx_module`
- **Cirurgia Q4.x** 0 hardcodes 9119/127.0.0.1 a tots els plugins

Aquests canvis **mai es van propagar** a `nat/dev/plugins-nexe/plugins/`. Els 5 auditors interns + 2 externs (Codex + Gemini, rondes 1+2) **no van detectar** la divergència — van validar el codi a server-nexe però mai van comparar contra plugins-nexe com a referència.

### Estat verificat empíricament 2026-04-08

| Plugin | Què li falta a `plugins-nexe/plugins/` |
|---|---|
| `ollama_module` | NO té `core/chat.py` ni `core/client.py` (la decapitació no hi va arribar) |
| `mlx_module` | `core/config.py` divergent (Q1.2 fix no aplicat) + `cli/main.py` legacy |
| `llama_cpp_module` | `manifest.py` + `__main__.py` divergents |
| `security` | `web_security_check.py` + `auth_dependencies.py` divergents |
| `web_ui_module` | TOTS els `routes_*.py` divergents (refactor B.3-B.8 personal_memory mai propagat) |

**Mtimes confirmen:** plugins-nexe estàtic des del 2026-04-04 (4 dies enrere de la cirurgia + refactor del server-nexe).

### Per què NO bloca v0.9.0

- El release només porta `server-nexe` → els plugins que s'envien al DMG **estan ben normalitzats**
- L'usuari final no toca `plugins-nexe/`
- Cap risc de seguretat ni funcional al release

### Per què cal arreglar-ho post-release

1. **`plugins-nexe` és la "fàbrica" long-term** — patró arquitectònic de referència
2. Si queda enrere, **futurs plugins forks heretaran patrons obsolets** (pre-decapitació, pre-personal_memory, pre-Q1.2)
3. **`audit_dependencies.py` viu només a `plugins-nexe/architecture/`** — i si l'estructura ha divergit, l'auditor podria fallar contra els plugins moderns del server
4. **Confusió cognitiva**: dos llocs amb "el mateix plugin" en estats diferents

### Acció proposada

**Opció A — Quick copy** (5 min, brut):
```bash
for P in ollama_module mlx_module llama_cpp_module security web_ui_module; do
  rsync -av --delete \
    /Users/jgoy/AI/nat/dev/server-nexe/plugins/$P/ \
    /Users/jgoy/AI/nat/dev/plugins-nexe/plugins/$P/
done
```
**⚠️ Risc:** perdre `diari/` i `cli/main.py` legacy de plugins-nexe.

**Opció B — Smart merge** (~1h, segur): cas per cas, copiar només els fitxers BUS-touched, preservar coses només-plugins-nexe (`diari/`, `cli/main.py` factory, etc.).

**Opció C — BUS dedicat** (sessió completa): un BUS multi-agent amb auditor per fer la sincronia formalment, validant cada plugin amb pytest + `audit_dependencies.py`.

**Recomanació:** Opció B per equilibri. Però decisió de Jordi quan arribi el moment.

### Quan

Post-release v0.9.0 — abans de començar feina seriosa a v0.9.1 (per evitar que els nous plugins forquin del baseline obsolet).

---

## 2. 📚 Reescriure `knowledge/{ca,es,en}/PLUGINS.md` des de zero

**Origen:** mateixa revisió profunda àrea 11.

### El problema

`knowledge/ca/PLUGINS.md` (407L, 11 seccions h2) està **parcialment actualitzada** — la BUS Fase 4 hi va afegir 2 seccions ("Activació sistema dual" + "Arquitectura del ModuleManager") però **0 mencions** dels 4 patrons concrets nous:

| Patró post-BUS | Mencionat a knowledge actual? |
|---|---|
| Decapitació ollama + parent binding `_parent()` + FIXME Gemini | ❌ 0 hits |
| `api/routes.py` extret del module.py monolític | ❌ 0 hits |
| `personal_memory` rename (refactor B.3-B.8 2026-04-08) | ❌ 0 hits |
| Q1.2 fix `Path.cwd()` removal | ❌ 0 hits |

### Per què NO bloca v0.9.0

- El knowledge és contingut RAG/docs, no entry-point per crear plugins
- L'usuari final pot fer chat sobre plugins i obtindrà info OK general, només falten els detalls dels 4 patrons concrets

### Per què cal arreglar-ho

- **Quan es faci el run real del mega-test**, els Devs llegiran aquesta knowledge per entendre l'estat actual dels plugins. Si està enrere, faran assumpcions errònies
- L'AI del propi server-nexe respon preguntes basant-se en aquesta knowledge — si està enrere, dóna informació desactualitzada

### Acció proposada

**Reescriptura sencera (no parches)** dels 3 documents `ca/`, `es/`, `en/PLUGINS.md` en una sola passada, alineats al canonical actual de `server-nexe/plugins/`. Decisió Jordi: *"el knowledge s'ha de fer nou, no parches, reescriure de nou amb les regles dels plugins"*.

**Cobertura nova:**
- Protocol NexeModule + variants (igual)
- manifest.toml format (igual)
- Estructura fitxers (igual)
- Cicle de vida (igual)
- ModuleManager + activació dual (ja afegit BUS Fase 4)
- **5 plugins amb estat real post-BUS:**
  - ollama_module decapitat + parent binding + FIXMEs
  - mlx_module routes extret + Q1.2 fix
  - llama_cpp_module routes + create_lazy_manifest
  - security extra_attrs Cas B + validate_string_input + 3 stubs specialists
  - web_ui_module post-personal_memory + i18n Codex P1 + monolit routes_chat tech debt
- Com crear plugin nou (alineat patrons actuals)
- 0 hardcodes 9119 (post-Q4)
- Errors comuns post-BUS

**Sincronia 3 idiomes** en una sola passada.

**Mida:** ~2-4h de feina seriosa.

### Quan

Pot fer-se entre el repàs del mega-test acabat i el run real del mega-test, com a tasca preflight. O bé com a tasca post-release amb la resta. Decisió Jordi.

---

## 2.bis 🧠 MEM_DELETE granular — split+rewrite per fets multi-fact

**Origen:** smoke test empíric install neta v0.9.9 2026-04-15 (Jordi).

### El problema

El model (especialment Gemma-4 e4b-it-4bit) de vegades desobeeix la "REGLA ATÒMICA" del prompt i guarda **dos fets combinats en un sol MEM_SAVE**:

```
Input usuari: "Em dic Aran i tinc 8 anys"
Model emet: [MEM_SAVE: L'usuari es diu Aran i té 8 anys]   ← combinat
Qdrant entry: 1 sola doc_id amb text combinat
```

Quan després l'usuari demana oblidar només una part:
```
Input: "Oblida que tinc 8 anys"
delete_from_memory("tinc 8 anys") → match semàntic amb l'entry combinat → esborra SENCER
```

Resultat UX: desapareix també el nom, que l'usuari no volia oblidar.

### Mitigació pre-v1.0 (ja aplicada, commit 98dbb29)

Reforçat server.toml 6 prompts amb "REGLA ATÒMICA" explícita + exemples correctes/incorrectes. Redueix la incidència però el model segueix sense ser 100% disciplinat.

### Solució real post-v1.0 (opcions)

**A) Split+rewrite al delete** (recomanat — menys disrupt):
Al `delete_from_memory`, si l'entry matchat conté el contingut a oblidar + altres fets distinguibles, aleshores:
1. Esborrar l'entry vella
2. Detectar parts sintàctiques no-esborrades ("es diu X", "té N anys", etc.)
3. Re-save les parts que l'usuari NO volia oblidar com a nous MEM_SAVE atòmics

Complexitat: baixa-mitjana. Necessita heurística de split (regex per conjuncions "i"/"y"/"and" + limitació de frases curtes).

**B) Chunker atòmic al save** (més radical):
Al moment de processar `[MEM_SAVE: X i Y i Z]`, el servidor parteix en N entries abans d'enviar a Qdrant. El model ja no necessita ser disciplinat.

Complexitat: mitjana. Afecta la ingesta i pot canviar el format dels payloads existents (retrocompat).

**C) LLM-assisted rewrite** (el model fa el split):
Després d'un delete que només esborra una part, fer una nova crida silent al LLM demanant "reescriu els fets restants de la frase 'X' sense '<part esborrada>'". Més car, depèn del model disponible.

**Recomanació:** A. Low impact, soluciona el 90% dels casos.

### Estimació

~2-3h + tests e2e (extensió de `tests/integration/test_mem_delete_e2e.py`).

### Quan

Post-v1.0, abans d'obrir el MEM_DELETE a nexe_documentation o user_knowledge (actualment només opera a personal_memory, on el risc és menor perquè sol haver-hi poques entries).

---

## 3. 🚀 Workflow engine plugin — APIs internes mòdul-a-mòdul

**Origen:** decisió Jordi 2026-04-08 nit (revisió àrea 17 vigilant Director Repàs)

**Cita Jordi (literal):** *"al final això és modular i un mòdul pot necessitar diferents APIs dels mòduls mateixos... és important perquè sigui modular... vindrà un plugin de workflow engine on es veuran totes les peces. Aquesta sí, una funcionalitat futura."*

### Visió

El server-nexe és **modular per disseny**. En el futur vindrà un plugin **workflow engine** que orquestrarà altres plugins via APIs internes mòdul-a-mòdul. Visió llarg termini, no curt termini.

**Estimació Jordi 2026-04-08 nit:** "ho esperem en 3-4 mesos tenir-ho" — post-release v0.9.0, possiblement v0.9.1 o v0.9.2.

### Estat actual (verificat 2026-04-08)

**Mentrestant**, per al release v0.9.0:
- ✅ `/v1/workflows` declarat als metadata `v1_root` (`core/endpoints/v1.py:36-40`)
- ✅ **Stub 501 Not Implemented** previst com a item 22 del `TODO-installer-prerelease.md` (Opció B Jordi)
- El stub és consistent: declaració metadata + endpoint funcional retornant 501 amb missatge clar

### Què cobrirà el workflow engine real (v0.9.1+)

1. **API contractes formals** — cada plugin exposa una interfície (Protocol/ABC) que documenta què altres plugins poden cridar
2. **Service registry** — mecanisme central perquè un plugin pugui demanar "vull el servei X" sense importar directament del path
3. **Versionat de signatures** — semver intern per detectar canvis breaking
4. **Documentació autogenerada** — extracció APIs internes a doc compatible amb el workflow engine
5. **Orquestració de pipelines** — un workflow encadena crides a múltiples plugins (ex: "ingest PDF → chunk → embed → save → notify")
6. **Persistència de workflows** — workflows guardats com a definicions reutilitzables
7. **UI per visualitzar workflows** — "veure totes les peces"

### Inputs preparats al v0.9.0

- Pas 17.13 de l'àrea 17 fa **inventari + gaps + recomanacions** com a 🟡 PENDENT post-release
- Pas 17.13.A inventari APIs internes exposades per cada plugin
- Pas 17.13.B inventari serveis al `server_state` (singletons globals)
- Stub 501 a `/v1/workflows` (item 22 pre-release)

### Acció post-release

1. Llegir l'output del run real del pas 17.13 (inventari APIs internes + gaps)
2. Decidir si el workflow engine és:
   - (a) Plugin propi a `plugins/workflow_engine/`
   - (b) Component core a `core/workflows/`
3. Implementar Protocol/ABC per a cada plugin existent (ollama, mlx, llama_cpp, security, web_ui)
4. Crear service registry
5. Substituir el stub 501 per la implementació real
6. Cross-ref `core/endpoints/v1.py:36-40` actualitzar metadata `workflows.status` a `"implemented"`

### Quan

**Post-release v0.9.0** — Jordi estima 3-4 mesos. Possiblement v0.9.1 o v0.9.2.

### Memòria

- `project_workflow_engine_futur` — visió llarg termini Jordi
- Cross-ref item 22 `TODO-installer-prerelease.md` (stub 501 pre-release)
- Cross-ref pas 17.13 àrea 17 mega-test (inventari APIs internes)

---

**Última actualització:** 2026-04-08 nit (vigilant Director Repàs Mega-Test, post-revisió profunda àrea 17 + decisió Jordi workflow engine)
