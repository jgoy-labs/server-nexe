# === METADATA RAG ===
versio: "2.0"
data: 2026-03-28
id: nexe-security-guide

# === CONTINGUT RAG (OBLIGATORI) ===
abstract: "Seguridad de server-nexe: autenticacion dual-key, rate limiting, 6 detectores de inyeccion, 47 patrones jailbreak, cabeceras OWASP, logging RFC5424, encriptacion AES-256-GCM en reposo (SQLCipher, sesiones .enc), sanitizacion RAG. Todo local, cero llamadas externas."
tags: [security, authentication, api-key, dual-key, rate-limiting, headers, csp, injection, jailbreak, sanitizer, ai-audit, logging, rfc5424, encryption, crypto, sqlcipher, local, privacy]
chunk_size: 600
priority: P1

# === OPCIONAL ===
lang: es
type: docs
author: "Jordi Goy"
expires: null
---

# Seguridad — server-nexe 0.9.7

server-nexe esta disenado para entornos locales de confianza. Todos los datos permanecen en el dispositivo. Sin telemetria, sin llamadas externas.

## Autenticacion

**Sistema dual-key** con soporte de rotacion:
- `NEXE_PRIMARY_API_KEY` — siempre activa, configurada en `.env`
- `NEXE_SECONDARY_API_KEY` — clave de periodo de gracia para rotacion
- Seguimiento de expiracion: `NEXE_PRIMARY_KEY_EXPIRES`, `NEXE_SECONDARY_KEY_EXPIRES`
- Validacion: `secrets.compare_digest()` (comparacion segura contra timing attacks)
- Cabecera: `X-API-Key`

**Token bootstrap:** Token de configuracion inicial generado al arrancar. Entropia de 256 bits, persistente en SQLite, TTL de 30 minutos. Regeneracion solo desde localhost.

## Rate Limiting

El rate limiting se aplica a **todos los endpoints** — tanto la API (`/v1/*`) como la Web UI (`/ui/*`).

### Endpoints API (configurables via `.env`)

| Variable | Por defecto | Endpoints |
|----------|-------------|-----------|
| NEXE_RATE_LIMIT_CHAT | 20/min | /v1/chat/completions |
| NEXE_RATE_LIMIT_MEMORY | 30/min | /v1/memory/* |
| NEXE_RATE_LIMIT_RAG | 30/min | /v1/rag/* |
| NEXE_RATE_LIMIT_UPLOAD | 5/min | /ui/upload |
| NEXE_RATE_LIMIT_DEFAULT | 120/min | Resto de endpoints |
| NEXE_RATE_LIMIT_GLOBAL | 100/min | Limite global |

**Nota:** Estas variables estan reservadas para implementacion futura. Los limites actuales estan configurados en el codigo fuente.

### Endpoints Web UI (fijos por endpoint)

| Endpoint | Rate limit |
|----------|-----------|
| POST /ui/chat | 20/minuto |
| POST /ui/memory/save | 10/minuto |
| POST /ui/memory/recall | 30/minuto |
| POST /ui/upload | 5/minuto |
| POST /ui/files/cleanup | 5/minuto |
| GET /ui/session/{id} | 30/minuto |
| GET /ui/session/{id}/history | 30/minuto |
| DELETE /ui/session/{id} | 10/minuto |

Implementacion: `slowapi` con decorador `@limiter.limit()` en cada endpoint. `RateLimitTracker` en `plugins/security/core/rate_limiting.py`.

## Cabeceras de seguridad (OWASP)

Aplicadas via `core/security_headers.py` y middleware:

- `Content-Security-Policy`: script-src 'self' (sin scripts inline — i18n usa atributo `data-nexe-lang` en su lugar)
- `Strict-Transport-Security`: max-age=31536000
- `X-Content-Type-Options`: nosniff
- `X-Frame-Options`: DENY
- `X-XSS-Protection`: 0 (deprecado, se usa CSP en su lugar)
- `Referrer-Policy`: strict-origin-when-cross-origin
- `Permissions-Policy`: camera=(), microphone=(), geolocation=(), payment=(), usb=(), magnetometer=(), gyroscope=(), accelerometer=()

## Validacion de entrada

### Pipeline API (/v1/*)

El endpoint API `POST /v1/chat/completions` valida y sanitiza la entrada a traves de su propio pipeline.

### Pipeline Web UI (/ui/*)

**Todos los endpoints de la Web UI** usan `validate_string_input()` para la validacion de entrada:

- `/ui/chat` — valida el contenido del mensaje
- `/ui/memory/save` — valida content, session_id
- `/ui/memory/recall` — valida query, session_id
- `/ui/session/{id}` (GET/DELETE) — valida session_id (proteccion contra path traversal)
- `/ui/upload` — valida filename (proteccion contra path traversal)

`validate_string_input()` acepta un parametro `context`:
- `context="chat"` — desactiva los detectores de inyeccion de comandos y LDAP (demasiados falsos positivos en conversacion normal)
- `context="path"` — validacion estricta para parametros de ruta (session_id, filename)

### Sanitizacion de contexto RAG

`_sanitize_rag_context()` se aplica al contexto RAG antes de inyectarlo en el prompt del LLM via la Web UI. Filtra patrones de inyeccion de documentos recuperados y entradas de memoria, evitando que el contenido almacenado se use como vector de ataque.

**Consistencia del pipeline:** A partir de la v0.9.0, la API y la Web UI comparten las mismas capas de seguridad — validacion de entrada, sanitizacion RAG y rate limiting se aplican de forma consistente en ambas interfaces.

## Deteccion de inyecciones

**6 detectores de inyeccion** en `plugins/security/core/injection_detectors.py`:
1. Detector de XSS
2. Detector de inyeccion SQL
3. Detector de inyeccion NoSQL
4. Detector de inyeccion de comandos
5. Detector de path traversal
6. Detector de inyeccion LDAP

**Normalizacion Unicode:** Los 6 detectores aplican `unicodedata.normalize('NFKC', text)` antes del pattern matching. Esto previene bypasses mediante homoglifos Unicode o variaciones de codificacion (p. ej., caracteres fullwidth, formas compuestas vs descompuestas).

**47 patrones de jailbreak** en `plugins/security/sanitizer/`: Pattern matching multilingue para intentos de inyeccion de prompt.

**Limite de tamano de peticion:** Cuerpo maximo de 100MB (proteccion contra DoS).

**Truncamiento en logs:** Los mensajes de usuario se truncan a 200 caracteres en la salida de logs para prevenir inyeccion de logs y reducir el volumen.

## Logging de auditoria

**Conforme a RFC5424** — logging de eventos de seguridad via `plugins/security/security_logger/`:
- Ruta de logs: `storage/system-logs/security/`
- Eventos: fallos de autenticacion, triggers de rate limit, intentos de inyeccion, acciones de administracion
- Logging de IP real: `request.client.host`
- El logging en tiempo de ejecucion usa `logger.info()` en lugar de `print()` (migrado en v0.9.0)

## Encriptacion en reposo (default `auto`)

**Anadida en v0.9.0, default `auto` desde v0.9.7.** La encriptacion en reposo se activa automaticamente si `sqlcipher3` esta disponible (modo `auto`). Ha sido probada (68 tests) pero aun no ha pasado por uso en produccion con usuarios reales fuera del desarrollo.

### CryptoProvider

- Algoritmo: **AES-256-GCM** con derivacion de claves **HKDF-SHA256**
- Cadena de gestion de claves: OS Keyring (macOS Keychain) -> variable de entorno `NEXE_MASTER_KEY` -> fichero `~/.nexe/master.key` (permisos 600)
- Claves derivadas por proposito: `"sqlite"`, `"sessions"`, `"text_store"`, `"backup"`
- Implementacion: `core/crypto/provider.py`

**Migrar la clave maestra a una nueva máquina:**

Si cambias de ordenador o reinstalas el sistema, debes mover la clave maestra para mantener el acceso a las sesiones `.enc` y la base de datos cifrada. La cadena de fallback es: OS Keyring → variable de entorno → fichero `~/.nexe/master.key`.

```bash
# 1. En la máquina ANTIGUA — exporta la clave
#    Opción A: desde el keychain (si está ahí)
security find-generic-password -s "server-nexe" -w 2>/dev/null | xxd -r -p > master.key.backup

#    Opción B: copia directa del fichero
cp ~/.nexe/master.key master.key.backup

# 2. Transfiere master.key.backup a la nueva máquina (USB, SCP, AirDrop)

# 3. En la máquina NUEVA — coloca la clave
mkdir -p ~/.nexe
cp master.key.backup ~/.nexe/master.key
chmod 600 ~/.nexe/master.key

# 4. Borra el backup
shred -u master.key.backup
```

Sin la clave original, las sesiones `.enc` y la base de datos SQLCipher **no se pueden descifrar**. No hay recuperación posible.

### Que se encripta

| Componente | Metodo | Detalles |
|-----------|--------|---------|
| Base de datos SQLite (memories.db) | SQLCipher | Migracion automatica de texto plano a encriptado |
| Sesiones de chat | .json -> .enc | AES-256-GCM, nonce(12) + ciphertext + tag(16) |
| Texto RAG (documentos) | TextStore | Texto almacenado en SQLite (opcionalmente SQLCipher), no en Qdrant |
| Payloads de Qdrant | Solo vectores | Los payloads solo contienen `entry_type` y `original_id` — sin texto |

### Como activarlo

```bash
# Activar encriptacion
export NEXE_ENCRYPTION_ENABLED=true

# Comprobar estado
./nexe encryption status

# Migrar datos existentes
./nexe encryption encrypt-all

# Exportar clave maestra (para backup)
./nexe encryption export-key
```

### Compatibilidad hacia atras

Todo es compatible hacia atras. Si la encriptacion no esta activada, el comportamiento es identico a versiones anteriores. Cero cambios para usuarios que no la activen.

## Privacidad

- Cero telemetria, cero llamadas a APIs externas
- Todos los datos (conversaciones, documentos, embeddings, modelos) almacenados localmente
- Los payloads de Qdrant ya no contienen texto (solo vectores + IDs)
- Encriptacion en reposo opcional para SQLite, sesiones y texto de documentos
- Sin cookies, sin tracking, sin analiticas

## Auditorias de seguridad

Todas las auditorias de seguridad son realizadas por sesiones autonomas de IA (Claude) como parte del proceso de desarrollo. El desarrollador lanza sesiones de revision dedicadas que analizan el codigo, ejecutan tests y generan informes estructurados con hallazgos. No son auditorias externas de empresas de seguridad.

### Auditoria IA v1 (marzo 2026)
- 73 hallazgos en 11 areas
- 40 correcciones implementadas
- Calificacion: B+ -> A-

### Auditoria IA v2 (marzo 2026)
- 12 hallazgos adicionales
- Todos resueltos
- 229 tests fallidos -> 0
- Calificacion: A

### Mega-Test v1 Pre-Release (marzo 2026)
- Auditoria autonoma de 4 fases: baseline (298 tests, 97.4% cobertura), seguridad (23 hallazgos), funcional (158 tests, 91.1%), GO/NO-GO
- 23 hallazgos (1 critico, 6 altos, 7 medios, 7 bajos)
- Veredicto: **GO CON CONDICIONES**
- Correcciones aplicadas: validacion de entrada UI, sanitizacion de contexto RAG, rate limiting, CVEs de dependencias

### Mega-Test v2 Post-Correcciones (marzo 2026)
- Misma metodologia de 4 fases, re-ejecutada tras aplicar las correcciones de v1
- 10 hallazgos (vs 23 en v1, **57% de reduccion**)
- 7 correcciones adicionales aplicadas: validacion de endpoints de memoria (CRITICO), path traversal en sesiones, validacion de nombres de fichero, rate limiting en todos los endpoints UI, normalizacion Unicode en detectores de inyeccion, migracion print()->logger
- 4665 tests pasados, 0 fallidos
- Veredicto: **GO CON CONDICIONES** (mejorado)

### Correcciones clave de las auditorias
- Validacion de entrada en endpoints de memoria (NF-001 — CRITICO)
- Proteccion contra path traversal en sesiones (NF-002)
- Validacion de nombres de fichero en uploads (NF-003)
- Rate limiting en todos los endpoints UI (NF-004)
- Normalizacion Unicode en los 6 detectores de inyeccion (NF-005/006)
- Prefijo de router establecido en constructor (bug de FastAPI)
- Logging de IP real en fallos de autenticacion (F-013)
- Parametro context en el sanitizer para reducir falsos positivos en chat (F-005)
- `repr(e)` en lugar de `str(e)` para excepciones httpx (bug de string vacio)
- Migracion print() -> logger.info() para codigo en tiempo de ejecucion
- CVEs de dependencias corregidas (pypdf, starlette)

### Nota de honestidad

Estas auditorias IA encuentran muchos problemas pero **no son exhaustivas** — con certeza hay vulnerabilidades y bugs que no han sido detectados. La cobertura de tests (97.4% baseline, 91.1% funcional) es buena pero no del 100%. El sistema de encriptacion es nuevo y no ha sido probado en batalla en produccion con usuarios reales. Este es un proyecto open-source personal revisado por IA, no un producto empresarial auditado formalmente.

## Riesgos aceptados

- **Limitaciones de modelos locales:** Los modelos pueden seguir instrucciones de inyeccion de prompt. Mitigacion: sanitizer + patrones de jailbreak + normalizacion Unicode.
- **Diseno para un solo usuario:** Sin aislamiento multi-usuario. Una API key = acceso completo.
- **Sin TLS por defecto:** HTTP en localhost. Usar reverse proxy (nginx/caddy) para HTTPS si se expone a la red.
- **La encriptacion es `auto` por defecto:** Se activa automaticamente si `sqlcipher3` esta disponible. Se puede forzar con `NEXE_ENCRYPTION_ENABLED=true` o desactivar con `false`.
- **Sistema de encriptacion nuevo:** CryptoProvider ha sido anadido recientemente y no ha pasado por uso en produccion con usuarios externos.

## Checklist de seguridad

- [ ] El fichero `.env` tiene permisos restringidos (chmod 600)
- [ ] Las API keys son fuertes (32+ caracteres hexadecimales)
- [x] Qdrant embedded — ningun puerto de red expuesto (no se necesitan reglas de firewall para Qdrant)
- [ ] El puerto del servidor (9119) esta vinculado a 127.0.0.1 (no 0.0.0.0)
- [ ] Encriptacion de disco activada (FileVault en macOS, LUKS en Linux)
- [ ] Rate limiting configurado adecuadamente
- [ ] Encriptacion en reposo activada si se manejan datos sensibles (`NEXE_ENCRYPTION_ENABLED=true`)
- [ ] Actualizaciones regulares aplicadas
- [ ] Logs de seguridad revisados periodicamente

## Reporte de vulnerabilidades

Reportar problemas de seguridad via GitHub: https://github.com/jgoy-labs/server-nexe/security/advisories
