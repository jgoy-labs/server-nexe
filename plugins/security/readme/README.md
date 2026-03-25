# Security Module — Server Nexe

Modul de seguretat core per server-nexe.

## Funcionalitats

- **Autenticacio dual-key** — Primary + secondary amb `secrets.compare_digest` (contra timing attacks)
- **6 detectors d'injeccio** — XSS, SQL, NoSQL, command, path traversal, LDAP
- **Rate limiting** — Per IP i per API key via slowapi + RateLimitTracker
- **Sanitizer** — 69 patrons de jailbreak multiidioma (submodul)
- **Security logging** — RFC5424-compliant IRONCLAD (submodul security_logger)
- **Scanning** — Checks automatitzats: auth, web security, rate limiting

## Endpoints

| Metode | Ruta | Auth | Descripcio |
|--------|------|------|------------|
| GET | /security/health | No | Health check |
| GET | /security/info | No | Info del modul |
| POST | /security/scan | Si (2/min) | Scan complet |
| GET | /security/report | Si (10/min) | Ultim informe |
| GET | /security/ui | No | Status page |

## Submoduls

- `sanitizer/` — Deteccio jailbreak i prompt injection
- `security_logger/` — Logging SIEM RFC5424

## CLI

```bash
python -m plugins.security info
python -m plugins.security health
python -m plugins.security test
python -m plugins.security workflow
```

## Estructura

Segueix l'estructura canonica de plugins Nexe (6 fitxers + 10 directoris obligatoris).
Veure GUIA-PLUGINS.md per detalls.
