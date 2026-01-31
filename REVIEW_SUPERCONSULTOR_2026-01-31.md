# Informe de Revisio "Super Consultor" - Server Nexe

Data: 2026-01-31
Ruta projecte: /Users/jgoy/NatSytem/Projectes/server-nexe/
Abast: codi core + plugins (seguretat, robustesa, arquitectura, DX, operacions). Sense executar serveis ni tests.

Resum executiu
- Trobat un bug de runtime clar a /api/bootstrap/info (NameError per import faltant).
- Inconsistencia de validacio d'API key en endpoints "opcionales" (ignora clau secundaria en rotacio).
- Diversos riscos operatius/robustesa: request.client pot ser None, tokens i timestamps barrejats (naive vs timezone), i riscos de "auto-start" de serveis externs sense control dur.
- Bona base de seguretat: rate limiting, CSRF, headers, limit de mida, tokens bootstrap persistents, clau dual amb expiracio.

Findings (ordenat per severitat)

[ALT] Runtime error a /api/bootstrap/info per import faltant (timezone)
- Fitxer: core/endpoints/bootstrap.py
- Linies: ~286 (datetime.now(timezone.utc).timestamp())
- Impacte: L'endpoint public /api/bootstrap/info retorna 500 quan hi ha token actiu; afecta UI/clients que depenen d'aquest endpoint.
- Evidencia: no hi ha import de timezone en aquest fitxer; es fa "from datetime import datetime" a la propia funcio.
- Recomanacio: importar timezone a nivell de mòdul o dins la funcio.

[MITJA] optional_api_key ignora clau secundaria (rotacio)
- Fitxer: plugins/security/core/auth_dependencies.py
- Linies: ~221-233
- Impacte: durant la finestra de "grace period", endpoints que usen optional_api_key rebutgen clients amb la clau secundaria, mentre require_api_key si la valida. Inconsistencia funcional i d'operacio.
- Recomanacio: reusar load_api_keys() i acceptar secundaria si es valida (paritat amb require_api_key).

[MITJA] request.client pot ser None en bootstrap (possible 500)
- Fitxer: core/endpoints/bootstrap.py
- Linies: ~109 (client_ip = request.client.host)
- Impacte: entorns amb proxies/tests poden tenir request.client = None; fallaria abans de checks i retornaria 500.
- Recomanacio: defensiu: client_ip = request.client.host if request.client else "unknown", i tratar "unknown" com no permès.

[MITJA] Comparacio timestamps naive vs UTC a bootstrap
- Fitxer: core/endpoints/bootstrap.py
- Linies: ~152 (datetime.now().timestamp() > info["expires"])
- Impacte: "now" naive vs expiracions guardades amb timezone.utc a DB pot crear inconsistencies subtils si el sistema te TZ offset.
- Recomanacio: usar datetime.now(timezone.utc).timestamp() per coherencia.

[MITJA] Auto-start de serveis externs (Qdrant/Ollama) sense control granular
- Fitxer: core/lifespan.py
- Linies: ~27-142
- Impacte: en entorns restringits, el servidor intenta arrencar binaris externs i pot bloquejar recursos; en infra compartida pot ser inesperat.
- Recomanacio: afegir flags config/env per desactivar auto-start per servei, i log clar amb el motiu.

[BAIX] CORS strict: falla dur si cors_origins buit
- Fitxer: core/middleware.py
- Linies: ~115-155
- Impacte: en desplegaments sense config, l'app peta al boot amb ValueError; pot ser intencional en mode air-gapped, pero dura en dev.
- Recomanacio: fer fallback en desenvolupament o especificar clar a README/server.toml.

[BAIX] CLI client i Web UI fan servir Authorization Bearer + x-api-key, pero servidor valida x-api-key
- Fitxer: core/cli/utils/api_client.py, plugins/web_ui_module/module.py
- Impacte: si algun endpoint espera Authorization Bearer i no x-api-key, podria fallar; al moment sembla consistent, pero no hi ha validacio centralitzada del header Authorization.
- Recomanacio: clarificar en docs quins headers son acceptats, i considerar validar Bearer de forma equivalent (si necessari).

Observacions d'arquitectura i operacio
- El pattern factory amb cache (core/server/factory.py) es correcte; atencio si es fa reload en multi-thread, pero hi ha lock + double-check.
- Lifespan fa molta feina (auto-start serveis, auto-ingest, bootstrap, auto-clean). Aquesta concentracio pot fer el boot fràgil. Potser convindria modularitzar fases o fer-les opcionals per config.
- Bootstrap tokens: bon reforc amb DB persistent i single-use atomic update. Falten tests al voltant de "validate_master_bootstrap".
- Rate limiting: hi ha tasca de cleanup en loop; no hi ha gestio de shutdown per cancel·lar el task.
- Request size limiter: robust i defensiu, reconstrueix body; be en termes de DoS, tot i que acumula body a memòria (limit alt 100MB).

Gap de tests (recomanat afegir)
- Test per /api/bootstrap/info amb token actiu (hauria fallat amb timezone missing).
- Test per optional_api_key acceptant clau secundaria quan primary expirada o absent.
- Test per request.client None en bootstrap (retorni 400/403, no 500).
- Test per auto-start disabled via env (si s'afegeix).

Accions recomanades (prioritat)
1) Fix import timezone + timestamp UTC a bootstrap.
2) Unificar validacio de keys a optional_api_key (acceptar secundaria valida).
3) Hardening de request.client None a bootstrap.
4) Fer flags d'auto-start per serveis externs.
5) Afegir tests minims pels punts anteriors.

Notes
- Informe generat sense executar el servidor ni tests.
- No s'han revisat els binaris ni fitxers dins venv.

Addendum - Revisio mes a fons (a primera vista ampliada)

Nous punts detectats

[BAIX] Metadata desactualitzada a endpoints publics
- Fitxer: core/endpoints/system.py
- Linies: ~287 (version "0.7.1")
- Impacte: el health mostra versio antiga; pot confondre monitors o UI.
- Recomanacio: actualitzar a 0.8.x o llegir de config/const.

[BAIX] Dates "expected_date" ja vencudes a /v1
- Fitxer: core/endpoints/v1.py
- Linies: ~33-60 (expected_date "2025-12-15")
- Impacte: API public retorna dates passades (avui es 2026-01-31); pot generar confusio.
- Recomanacio: actualitzar dates o eliminar-les si no son fiables.

[BAIX] ssl_enabled pot ser fals negatiu darrere proxy TLS
- Fitxer: core/endpoints/bootstrap.py
- Linies: ~296 (ssl_enabled = request.url.scheme == "https")
- Impacte: en infra amb TLS terminat per proxy, scheme pot ser "http" i la UI rep info incorrecta.
- Recomanacio: confiar en headers X-Forwarded-Proto amb middleware de proxy si s'usa.

[BAIX] VPN_ALLOWED_IPS no fa strip d'espais
- Fitxer: core/endpoints/bootstrap.py
- Linies: ~45 (split(','))
- Impacte: valors "1.2.3.4, 5.6.7.8" deixen espai i fallen a la whitelist.
- Recomanacio: aplicar strip a cada IP.

[BAIX] Token bootstrap es genera i persisteix fins i tot en produccio
- Fitxer: core/lifespan.py
- Linies: ~420-468
- Impacte: encara que el bootstrap es bloqueja si NEXE_ENV != development, el token segueix existint a la DB. Si algú configura NEXE_ENV per error, el token ja hi es.
- Recomanacio: condicionar generacio/persistencia a development o a un flag explicit.

[BAIX] CSP connect-src "self" pot trencar UI en domini diferent
- Fitxer: core/security_headers.py
- Linies: ~31-47
- Impacte: si la UI consumeix API en un altre host/port (p. ex. reverse proxy), el navegador bloquejara requests.
- Recomanacio: fer CSP configurable o documentar la limitacio.

[BAIX] Task de neteja rate-limit no es cancel·la en shutdown
- Fitxer: plugins/security/core/rate_limiting.py + core/lifespan.py
- Linies: ~329 (loop) i ~498 (create_task)
- Impacte: en tests o shutdown, task queda viu fins que el loop es cancel·la per fora.
- Recomanacio: guardar handle del task i cancel·lar-lo al shutdown.

[BAIX] Descoberta de CLIs via manifest pot executar mòduls no confiats
- Fitxer: core/cli/router.py
- Linies: ~118-180 i ~206-266
- Impacte: si hi ha manifests maliciosos dins del tree, el CLI podria executar moduls arbitraris via subprocess.
- Recomanacio: limitar directoris permesos o whitelist de manifests confiables.

[INFO] Auto-ingest i auto-clean al boot poden allargar startup
- Fitxer: core/lifespan.py
- Linies: ~320-520
- Impacte: en entorns amb molts documents, l'arrencada pot ser lenta o bloquejant.
- Recomanacio: fer aquests processos "on-demand" o amb feature flag per defecte OFF (ja hi ha flags, pero podria reforcar-se).
