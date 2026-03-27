# === METADATA RAG ===
versio: "1.1"
data: 2026-03-27
id: nexe-security-guide

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Documentació de seguretat de server-nexe 0.8.2. Cobreix autenticació API dual-key amb rotació, rate limiting (6 nivells), 6 detectors d'injecció (XSS, SQL, NoSQL, comandes, path traversal, LDAP), 69 patrons de jailbreak, capçaleres de seguretat OWASP (CSP, HSTS), logging d'auditoria RFC5424, sanitització d'entrada amb paràmetre context, logging d'IP real. Inclou resultats de les auditories consultoria v1+v2 (73+12 troballes, grau A) i checklist de seguretat."
tags: [seguretat, autenticació, api-key, dual-key, rate-limiting, capçaleres, csp, injecció, jailbreak, sanititzador, auditoria, logging, rfc5424, consultoria]
chunk_size: 800
priority: P1

# === OPCIONAL ===
lang: ca
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# Seguretat — server-nexe 0.8.2

server-nexe està dissenyat per a entorns locals de confiança. Totes les dades queden al dispositiu. Sense telemetria, sense crides externes.

## Autenticació

**Sistema dual-key** amb suport de rotació:
- `NEXE_PRIMARY_API_KEY` — sempre activa, configurada a `.env`
- `NEXE_SECONDARY_API_KEY` — clau amb període de gràcia per a rotació
- Seguiment d'expiració: `NEXE_PRIMARY_KEY_EXPIRES`, `NEXE_SECONDARY_KEY_EXPIRES`
- Validació: `secrets.compare_digest()` (comparació segura contra timing attacks)
- Capçalera: `X-API-Key`

**Bootstrap token:** Token d'ús únic generat a l'arrencada. 128 bits d'entropia, persistent a SQLite, TTL de 30 minuts. Regeneració només des de localhost.

## Rate Limiting

6 nivells configurables via `.env`:

| Nivell | Per defecte | Endpoints |
|--------|-------------|-----------|
| NEXE_RATE_LIMIT_CHAT | 60/min | /v1/chat/completions |
| NEXE_RATE_LIMIT_MEMORY | 30/min | /v1/memory/* |
| NEXE_RATE_LIMIT_RAG | 30/min | /v1/rag/* |
| NEXE_RATE_LIMIT_UPLOAD | 10/min | /ui/upload |
| NEXE_RATE_LIMIT_DEFAULT | 120/min | Tots els altres endpoints |
| NEXE_RATE_LIMIT_GLOBAL | 100/min | Límit global |

Implementació: `RateLimitTracker` a `plugins/security/core/rate_limiting.py`.

## Capçaleres de seguretat (OWASP)

Aplicades via `core/security_headers.py` i middleware:

- `Content-Security-Policy`: script-src 'self' (sense scripts inline — i18n usa l'atribut `data-nexe-lang` en comptes)
- `Strict-Transport-Security`: max-age=31536000
- `X-Content-Type-Options`: nosniff
- `X-Frame-Options`: DENY
- `X-XSS-Protection`: 0 (obsolet, s'usa CSP en comptes)
- `Referrer-Policy`: strict-origin-when-cross-origin
- `Permissions-Policy`: restringit

## Validació d'entrada i detecció d'injeccions

**6 detectors d'injecció** a `plugins/security/core/injection_detectors.py`:
1. Detector XSS
2. Detector d'injecció SQL
3. Detector d'injecció NoSQL
4. Detector d'injecció de comandes
5. Detector de path traversal
6. Detector d'injecció LDAP

**Sanitització conscient del context:** `validate_string_input()` accepta un paràmetre `context` (p. ex., `context="chat"`) que desactiva els detectors d'injecció de comandes i LDAP per a missatges de xat (massa falsos positius en conversa normal).

**69 patrons de jailbreak** a `plugins/security/sanitizer/`: Coincidència de patrons multilingüe per a intents d'injecció de prompt.

**Límit de mida de petició:** 100 MB de cos de petició màxim (protecció contra DoS).

## Logging d'auditoria

**Conforme a RFC5424** logging d'events de seguretat via `plugins/security/security_logger/`:
- Ruta de logs: `storage/system-logs/security/`
- Events: errors d'autenticació, activacions de rate limit, intents d'injecció, accions d'administració
- Logging d'IP real: `request.client.host` (corregit a la troballa F-013 de la consultoria, abans loguejava un placeholder)

## Privacitat

- Zero telemetria, zero crides a APIs externes
- Totes les dades (converses, documents, embeddings, models) emmagatzemades localment
- Vectors de Qdrant emmagatzemats sense encriptar al disc (acceptable per a dispositiu local de confiança)
- Sense cookies, sense seguiment, sense analítiques

## Auditories de seguretat

### Consultoria v1 (març 2026)
- 73 troballes en 11 àrees
- 40 correccions implementades
- Grau: B+ a A-

### Consultoria v2 (març 2026)
- 12 troballes addicionals
- Totes resoltes
- 229 tests fallant a 0
- Grau: A

### Correccions clau de les auditories
- Prefix del router establert al constructor (era codi mort després del constructor — bug de FastAPI)
- Logging d'IP real en errors d'autenticació (F-013)
- Paràmetre context del sanititzador per reduir falsos positius al xat (F-005)
- `repr(e)` en comptes de `str(e)` per a excepcions httpx (bug de cadena buida)
- Docker USER no-root (F-030)
- Eliminació de codi mort (F-006, F-007)

## Riscos acceptats

- **Qdrant sense encriptar:** Vectors emmagatzemats en text pla al disc. Mitigació: accés només local, encriptació de disc (FileVault/LUKS).
- **Limitacions dels models locals:** Els models poden seguir instruccions d'injecció de prompt. Mitigació: sanititzador + patrons de jailbreak.
- **Disseny mono-usuari:** Sense aïllament multi-usuari. Una API key = accés complet.
- **Sense TLS per defecte:** HTTP a localhost. Usa un reverse proxy (nginx/caddy) per HTTPS si exposes a la xarxa.

## Checklist de seguretat

- [ ] Fitxer `.env` amb permisos restringits (chmod 600)
- [ ] API keys fortes (32+ caràcters hexadecimals)
- [ ] Port de Qdrant (6333) no exposat a la xarxa
- [ ] Port del servidor (9119) enllaçat a 127.0.0.1 (no 0.0.0.0)
- [ ] Encriptació de disc activada (FileVault a macOS, LUKS a Linux)
- [ ] Rate limiting configurat adequadament
- [ ] Actualitzacions regulars aplicades
- [ ] Logs de seguretat revisats periòdicament

## Reportar vulnerabilitats

Reporta problemes de seguretat via GitHub: https://github.com/jgoy-labs/server-nexe/security/advisories
