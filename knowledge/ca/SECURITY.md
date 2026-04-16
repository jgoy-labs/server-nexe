# === METADATA RAG ===
versio: "2.0"
data: 2026-03-28
id: nexe-security-guide
collection: nexe_documentation

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Seguretat de server-nexe: autenticacio dual-key, rate limiting, 6 detectors d'injeccio, 47 patrons jailbreak, capsaleres OWASP, logging RFC5424, encriptacio AES-256-GCM at-rest (SQLCipher, sessions .enc), sanititzacio RAG. Tot local, zero crides externes."
tags: [security, authentication, api-key, dual-key, rate-limiting, headers, csp, injection, jailbreak, sanitizer, ai-audit, logging, rfc5424, encryption, crypto, sqlcipher, local, privacy]
chunk_size: 600
priority: P1

# === OPCIONAL ===
lang: ca
type: docs
author: "Jordi Goy"
expires: null
---

# Seguretat — server-nexe 0.9.7

server-nexe 0.9.7 esta dissenyat per a entorns locals de confiança. Totes les dades es queden al dispositiu. Sense telemetria, sense crides externes.

## Autenticacio

**Sistema dual-key** amb suport per a rotacio:
- `NEXE_PRIMARY_API_KEY` — sempre activa, configurada a `.env`
- `NEXE_SECONDARY_API_KEY` — clau de gracia per a rotacio
- Seguiment d'expiracio: `NEXE_PRIMARY_KEY_EXPIRES`, `NEXE_SECONDARY_KEY_EXPIRES`
- Validacio: `secrets.compare_digest()` (comparacio segura contra timing attacks)
- Capcalera: `X-API-Key`

**Bootstrap token:** Token d'un sol us generat a l'arrencada. Entropia de 256 bits, persistent a SQLite, TTL de 30 minuts. Regeneracio nomes des de localhost.

## Rate Limiting

El rate limiting s'aplica a **tots els endpoints** — tant a l'API (`/v1/*`) com a la Web UI (`/ui/*`).

### Endpoints de l'API (configurables via `.env`)

| Variable | Per defecte | Endpoints |
|----------|---------|-----------|
| NEXE_RATE_LIMIT_CHAT | 20/min | /v1/chat/completions |
| NEXE_RATE_LIMIT_MEMORY | 30/min | /v1/memory/* |
| NEXE_RATE_LIMIT_RAG | 30/min | /v1/rag/* |
| NEXE_RATE_LIMIT_UPLOAD | 5/min | /ui/upload |
| NEXE_RATE_LIMIT_DEFAULT | 120/min | Resta d'endpoints |
| NEXE_RATE_LIMIT_GLOBAL | 100/min | Limit global |

**Nota:** Aquestes variables estan reservades per a implementació futura. Els límits actuals estan configurats al codi font.

### Endpoints de la Web UI (fixats per endpoint)

| Endpoint | Limit |
|----------|-----------|
| POST /ui/chat | 20/minut |
| POST /ui/memory/save | 10/minut |
| POST /ui/memory/recall | 30/minut |
| POST /ui/upload | 5/minut |
| POST /ui/files/cleanup | 5/minut |
| GET /ui/session/{id} | 30/minut |
| GET /ui/session/{id}/history | 30/minut |
| DELETE /ui/session/{id} | 10/minut |

Implementacio: `slowapi` amb decorador `@limiter.limit()` a cada endpoint. `RateLimitTracker` a `plugins/security/core/rate_limiting.py`.

## Capcaleres de seguretat (OWASP)

Aplicades via `core/security_headers.py` i middleware:

- `Content-Security-Policy`: script-src 'self' (sense scripts inline — i18n utilitza l'atribut `data-nexe-lang` en lloc d'inline)
- `Strict-Transport-Security`: max-age=31536000
- `X-Content-Type-Options`: nosniff
- `X-Frame-Options`: DENY
- `X-XSS-Protection`: 0 (obsolet, s'utilitza CSP)
- `Referrer-Policy`: strict-origin-when-cross-origin
- `Permissions-Policy`: camera=(), microphone=(), geolocation=(), payment=(), usb=(), magnetometer=(), gyroscope=(), accelerometer=()

## Validacio d'input

### Pipeline de l'API (/v1/*)

L'endpoint `POST /v1/chat/completions` valida i sanititza l'input a traves del seu propi pipeline.

### Pipeline de la Web UI (/ui/*)

**Tots els endpoints de la Web UI** utilitzen `validate_string_input()` per a la validacio d'input:

- `/ui/chat` — valida el contingut del missatge
- `/ui/memory/save` — valida content, session_id
- `/ui/memory/recall` — valida query, session_id
- `/ui/session/{id}` (GET/DELETE) — valida session_id (proteccio contra path traversal)
- `/ui/upload` — valida el nom del fitxer (proteccio contra path traversal)

`validate_string_input()` accepta un parametre `context`:
- `context="chat"` — desactiva els detectors d'injeccio de comandes i LDAP (massa falsos positius en conversa normal)
- `context="path"` — validacio estricta per a parametres de ruta (session_id, filename)

### Sanititzacio de context RAG

`_sanitize_rag_context()` s'aplica al context RAG abans d'injectar-lo al prompt del LLM via la Web UI. Aixo filtra patrons d'injeccio dels documents recuperats i les entrades de memoria, evitant que contingut emmagatzemat s'utilitzi com a vector d'atac.

**Consistencia del pipeline:** A partir de la v0.9.0, l'API i la Web UI comparteixen les mateixes capes de seguretat — validacio d'input, sanititzacio RAG i rate limiting s'apliquen de manera consistent a les dues interficies.

## Deteccio d'injeccions

**6 detectors d'injeccio** a `plugins/security/core/injection_detectors.py`:
1. Detector de XSS
2. Detector d'injeccio SQL
3. Detector d'injeccio NoSQL
4. Detector d'injeccio de comandes
5. Detector de path traversal
6. Detector d'injeccio LDAP

**Normalitzacio Unicode:** Els 6 detectors apliquen `unicodedata.normalize('NFKC', text)` abans del matching de patrons. Aixo preveu bypasses via homoglifs Unicode o variacions d'encoding (p. ex., caracters fullwidth, formes compostes vs descompostes).

**47 patrons de jailbreak** a `plugins/security/sanitizer/`: Matching de patrons multilingue per a intents d'injeccio de prompts.

**Limit de mida de peticio:** Cos de peticio maxim de 100MB (proteccio contra DoS).

**Truncament de logs:** Els missatges d'usuari es truncen a 200 caracters a la sortida de logs per prevenir injeccio de logs i reduir el volum.

## Logging d'auditoria

Logging d'events de seguretat **compatible amb RFC5424** via `plugins/security/security_logger/`:
- Ruta dels logs: `storage/system-logs/security/`
- Events: errors d'autenticacio, activacions de rate limit, intents d'injeccio, accions d'administrador
- Logging d'IP real: `request.client.host`
- El logging en temps d'execucio utilitza `logger.info()` en lloc de `print()` (migrat a la v0.9.0)

## Encriptacio at-rest (default `auto`)

**Afegida a la v0.9.0, default `auto` des de v0.9.7.** L'encriptacio at-rest s'activa automaticament si `sqlcipher3` es disponible (mode `auto`). S'ha testejat (68 tests) pero encara no ha passat per us en produccio amb usuaris reals fora del desenvolupament.

### CryptoProvider

- Algorisme: **AES-256-GCM** amb derivacio de claus **HKDF-SHA256**
- Cadena de gestio de claus: OS Keyring (macOS Keychain) -> variable d'entorn `NEXE_MASTER_KEY` -> fitxer `~/.nexe/master.key` (permisos 600)
- Claus derivades per proposit: `"sqlite"`, `"sessions"`, `"text_store"`, `"backup"`
- Implementacio: `core/crypto/provider.py`

**Migrar la clau mestra a una nova màquina:**

Si canvies d'ordinador o reinstal·les el sistema, has de moure la clau mestra per mantenir accés a les sessions `.enc` i la base de dades encriptada. La cadena de fallback és: OS Keyring → variable d'entorn → fitxer `~/.nexe/master.key`.

```bash
# 1. A la màquina ANTIGA — exporta la clau
#    Opció A: des del keychain (si hi és)
security find-generic-password -s "server-nexe" -w 2>/dev/null | xxd -r -p > master.key.backup

#    Opció B: còpia directa del fitxer
cp ~/.nexe/master.key master.key.backup

# 2. Transfereix master.key.backup a la nova màquina (USB, SCP, AirDrop)

# 3. A la màquina NOVA — col·loca la clau
mkdir -p ~/.nexe
cp master.key.backup ~/.nexe/master.key
chmod 600 ~/.nexe/master.key

# 4. Esborra el backup
shred -u master.key.backup
```

Sense la clau original, les sessions `.enc` i la base de dades SQLCipher **no es poden desencriptar**. No hi ha recuperació possible.

### Que s'encripta

| Component | Metode | Detalls |
|-----------|--------|---------|
| Base de dades SQLite (memories.db) | SQLCipher | Migracio automatica de text pla a encriptat |
| Sessions de xat | .json -> .enc | AES-256-GCM, nonce(12) + ciphertext + tag(16) |
| Text RAG (documents) | TextStore | Text emmagatzemat a SQLite (opcionalment SQLCipher), no a Qdrant |
| Payloads de Qdrant | Nomes vectors | Els payloads contenen nomes `entry_type` i `original_id` — sense text |

### Com activar-ho

```bash
# Activar encriptacio
export NEXE_ENCRYPTION_ENABLED=true

# Comprovar l'estat
./nexe encryption status

# Migrar dades existents
./nexe encryption encrypt-all

# Exportar la clau mestra (per a copia de seguretat)
./nexe encryption export-key
```

### Compatibilitat enrere

Tot es compatible enrere. Si l'encriptacio no esta activada, el comportament es identic a les versions anteriors. Zero canvis per als usuaris que no l'activin.

## Privacitat

- Zero telemetria, zero crides a APIs externes
- Totes les dades (converses, documents, embeddings, models) emmagatzemades localment
- Els payloads de Qdrant ja no contenen text (nomes vectors + IDs)
- Encriptacio at-rest opcional per a SQLite, sessions i text de documents
- Sense cookies, sense tracking, sense analitiques

## Auditories de seguretat

Totes les auditories de seguretat les realitzen sessions autonomes d'IA (Claude) com a part del proces de desenvolupament. El desenvolupador llanca sessions de revisio dedicades que analitzen codi, executen tests i generen informes estructurats amb troballes. No son auditories externes d'empreses de seguretat.

### Auditoria IA v1 (marc 2026)
- 73 troballes en 11 arees
- 40 correccions implementades
- Nota: B+ -> A-

### Auditoria IA v2 (marc 2026)
- 12 troballes addicionals
- Totes resoltes
- 229 tests fallant -> 0
- Nota: A

### Mega-Test v1 Pre-Release (marc 2026)
- Auditoria autonoma de 4 fases: baseline (298 tests, 97.4% cobertura), seguretat (23 troballes), funcional (158 tests, 91.1%), GO/NO-GO
- 23 troballes (1 critica, 6 altes, 7 mitjanes, 7 baixes)
- Veredicte: **GO WITH CONDITIONS**
- Correccions aplicades: validacio d'input UI, sanititzacio de context RAG, rate limiting, CVEs de dependencies

### Mega-Test v2 Post-Correccions (marc 2026)
- Mateixa metodologia de 4 fases, re-executada despres d'aplicar les correccions de la v1
- 10 troballes (vs 23 a la v1, **57% de reduccio**)
- 7 correccions addicionals aplicades: validacio d'endpoints de memoria (CRITIC), path traversal de sessions, validacio de noms de fitxer, rate limiting a tots els endpoints UI, normalitzacio Unicode als detectors d'injeccio, migracio print()->logger
- 4770 tests passats, 0 fallats
- Veredicte: **GO WITH CONDITIONS** (millorat)

### Correccions clau de les auditories
- Validacio d'input als endpoints de memoria (NF-001 — CRITIC)
- Proteccio contra path traversal a sessions (NF-002)
- Validacio de noms de fitxer a upload (NF-003)
- Rate limiting a tots els endpoints UI (NF-004)
- Normalitzacio Unicode als 6 detectors d'injeccio (NF-005/006)
- Prefix del router establert al constructor (bug de FastAPI)
- Logging d'IP real en errors d'autenticacio (F-013)
- Parametre context al sanitizer per reduir falsos positius al xat (F-005)
- `repr(e)` en lloc de `str(e)` per a excepcions httpx (bug de string buida)
- Migracio print() -> logger.info() per al codi en temps d'execucio
- CVEs de dependencies corregides (pypdf, starlette)

### Nota d'honestedat

Aquestes auditories IA troben molts problemes pero **no son exhaustives** — hi ha sens dubte vulnerabilitats i bugs que no s'han detectat. La cobertura de tests (97.4% baseline, 91.1% funcional) es bona pero no es del 100%. El sistema d'encriptacio es nou i no ha estat provat en batalla en produccio amb usuaris reals encara. Aixo es un projecte personal de codi obert revisat per IA, no un producte empresarial auditat formalment.

## Riscos acceptats

- **Limitacions dels models locals:** Els models poden seguir instruccions d'injeccio de prompts. Mitigacio: sanitizer + patrons de jailbreak + normalitzacio Unicode.
- **Disseny per a un sol usuari:** Sense aillament multi-usuari. Una clau API = acces complet.
- **Sense TLS per defecte:** HTTP a localhost. Utilitza un reverse proxy (nginx/caddy) per a HTTPS si exposes a la xarxa.
- **L'encriptacio es `auto` per defecte:** S'activa automaticament si `sqlcipher3` es disponible. Es pot forcar amb `NEXE_ENCRYPTION_ENABLED=true` o desactivar amb `false`.
- **Sistema d'encriptacio nou:** CryptoProvider s'ha afegit recentment i no ha passat per us en produccio amb usuaris externs.

## Checklist de seguretat

- [ ] El fitxer `.env` te permisos restringits (chmod 600)
- [ ] Les claus API son fortes (32+ caracters hexadecimals)
- [x] Qdrant embedded — cap port de xarxa exposat (no calen regles de firewall per Qdrant)
- [ ] El port del servidor (9119) esta vinculat a 127.0.0.1 (no 0.0.0.0)
- [ ] L'encriptacio de disc esta activada (FileVault a macOS, LUKS a Linux)
- [ ] El rate limiting esta configurat adequadament
- [ ] L'encriptacio at-rest esta activada si es gestionen dades sensibles (`NEXE_ENCRYPTION_ENABLED=true`)
- [ ] Les actualitzacions regulars s'apliquen
- [ ] Els logs de seguretat es revisen periodicament

## Informar de vulnerabilitats

Informeu de problemes de seguretat via GitHub: https://github.com/jgoy-labs/server-nexe/security/advisories
