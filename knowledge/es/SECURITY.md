# === METADATA RAG ===
versio: "1.1"
data: 2026-03-27
id: nexe-security-guide

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Documentacion de seguridad de server-nexe 0.8.2. Cubre autenticacion dual-key con rotacion, rate limiting (6 niveles), 6 detectores de inyeccion (XSS, SQL, NoSQL, comandos, path traversal, LDAP), 69 patrones jailbreak, cabeceras de seguridad OWASP (CSP, HSTS), logging de auditoria RFC5424, sanitizacion de entrada con parametro context, logging de IP real. Incluye resultados de consultoria v1+v2 (73+12 hallazgos, nota A) y checklist de seguridad."
tags: [seguridad, autenticacion, api-key, dual-key, rate-limiting, cabeceras, csp, inyeccion, jailbreak, sanitizer, auditoria, logging, rfc5424, consultoria]
chunk_size: 800
priority: P1

# === OPCIONAL ===
lang: es
type: docs
collection: user_knowledge
author: "Jordi Goy"
expires: null
---

# Seguridad — server-nexe 0.8.2

server-nexe esta disenado para entornos locales de confianza. Todos los datos permanecen en el dispositivo. Sin telemetria, sin llamadas externas.

## Autenticacion

**Sistema dual-key** con soporte de rotacion:
- `NEXE_PRIMARY_API_KEY` — siempre activa, configurada en `.env`
- `NEXE_SECONDARY_API_KEY` — clave en periodo de gracia para rotacion
- Seguimiento de expiracion: `NEXE_PRIMARY_KEY_EXPIRES`, `NEXE_SECONDARY_KEY_EXPIRES`
- Validacion: `secrets.compare_digest()` (comparacion segura contra timing attacks)
- Cabecera: `X-API-Key`

**Bootstrap token:** Token de configuracion inicial generado al arrancar. 128 bits de entropia, persistente en SQLite, TTL de 30 minutos. Regeneracion solo desde localhost.

## Rate Limiting

6 niveles configurables via `.env`:

| Nivel | Por defecto | Endpoints |
|-------|-------------|-----------|
| NEXE_RATE_LIMIT_CHAT | 60/min | /v1/chat/completions |
| NEXE_RATE_LIMIT_MEMORY | 30/min | /v1/memory/* |
| NEXE_RATE_LIMIT_RAG | 30/min | /v1/rag/* |
| NEXE_RATE_LIMIT_UPLOAD | 10/min | /ui/upload |
| NEXE_RATE_LIMIT_DEFAULT | 120/min | Todos los demas endpoints |
| NEXE_RATE_LIMIT_GLOBAL | 100/min | Limite global |

Implementacion: `RateLimitTracker` en `plugins/security/core/rate_limiting.py`.

## Cabeceras de seguridad (OWASP)

Aplicadas via `core/security_headers.py` y middleware:

- `Content-Security-Policy`: script-src 'self' (sin scripts inline — i18n usa el atributo `data-nexe-lang` en su lugar)
- `Strict-Transport-Security`: max-age=31536000
- `X-Content-Type-Options`: nosniff
- `X-Frame-Options`: DENY
- `X-XSS-Protection`: 0 (obsoleto, se usa CSP en su lugar)
- `Referrer-Policy`: strict-origin-when-cross-origin
- `Permissions-Policy`: restringida

## Validacion de entrada y deteccion de inyecciones

**6 detectores de inyeccion** en `plugins/security/core/injection_detectors.py`:
1. Detector de XSS
2. Detector de inyeccion SQL
3. Detector de inyeccion NoSQL
4. Detector de inyeccion de comandos
5. Detector de path traversal
6. Detector de inyeccion LDAP

**Sanitizacion sensible al contexto:** `validate_string_input()` acepta un parametro `context` (p. ej., `context="chat"`) que desactiva los detectores de inyeccion de comandos y LDAP para mensajes de chat (demasiados falsos positivos en conversacion normal).

**69 patrones jailbreak** en `plugins/security/sanitizer/`: Coincidencia de patrones multilingue para intentos de inyeccion de prompt.

**Limite de tamano de peticion:** 100MB maximo por cuerpo de peticion (proteccion DoS).

## Logging de auditoria

Logging de eventos de seguridad **conforme a RFC5424** via `plugins/security/security_logger/`:
- Ruta de logs: `storage/system-logs/security/`
- Eventos: fallos de autenticacion, activaciones de rate limit, intentos de inyeccion, acciones de administracion
- Logging de IP real: `request.client.host` (corregido en hallazgo de consultoria F-013, antes registraba un placeholder)

## Privacidad

- Cero telemetria, cero llamadas a APIs externas
- Todos los datos (conversaciones, documentos, embeddings, modelos) almacenados localmente
- Vectores Qdrant almacenados sin cifrar en disco (aceptable para dispositivo local de confianza)
- Sin cookies, sin tracking, sin analiticas

## Auditorias de seguridad

### Consultoria v1 (marzo 2026)
- 73 hallazgos en 11 areas
- 40 correcciones implementadas
- Nota: B+ → A-

### Consultoria v2 (marzo 2026)
- 12 hallazgos adicionales
- Todos resueltos
- 229 tests fallando → 0
- Nota: A

### Correcciones clave de las auditorias
- Prefijo de router establecido en el constructor (era codigo muerto despues del constructor — bug de FastAPI)
- Logging de IP real en fallos de autenticacion (F-013)
- Parametro context en sanitizer para reducir falsos positivos en chat (F-005)
- `repr(e)` en lugar de `str(e)` para excepciones httpx (bug de cadena vacia)
- Docker USER no-root (F-030)
- Eliminacion de codigo muerto (F-006, F-007)

## Riesgos aceptados

- **Qdrant sin cifrar:** Vectores almacenados en texto plano en disco. Mitigacion: acceso solo local, cifrado de disco (FileVault/LUKS).
- **Limitaciones de modelos locales:** Los modelos pueden seguir instrucciones de inyeccion de prompt. Mitigacion: sanitizer + patrones jailbreak.
- **Diseno de usuario unico:** Sin aislamiento multi-usuario. Una API key = acceso completo.
- **Sin TLS por defecto:** HTTP en localhost. Usar reverse proxy (nginx/caddy) para HTTPS si se expone a la red.

## Checklist de seguridad

- [ ] El fichero `.env` tiene permisos restringidos (chmod 600)
- [ ] Las API keys son fuertes (32+ caracteres hexadecimales)
- [ ] El puerto de Qdrant (6333) no esta expuesto a la red
- [ ] El puerto del servidor (9119) esta vinculado a 127.0.0.1 (no 0.0.0.0)
- [ ] Cifrado de disco activado (FileVault en macOS, LUKS en Linux)
- [ ] Rate limiting configurado adecuadamente
- [ ] Actualizaciones regulares aplicadas
- [ ] Logs de seguridad revisados periodicamente

## Reportar vulnerabilidades

Reportar problemas de seguridad via GitHub: https://github.com/jgoy-labs/server-nexe/security/advisories
