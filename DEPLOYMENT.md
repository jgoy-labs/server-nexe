# Guia de Deployment Segur - Nexe Server 0.8

## Índex

- [Introducció](#introducció)
- [Configuració de Secrets](#configuració-de-secrets)
- [Deployment Local](#deployment-local)
- [Deployment amb Docker](#deployment-amb-docker)
- [Accés Remot Segur](#accés-remot-segur)
- [Reverse Proxy](#reverse-proxy)
- [Monitorització i Alertes](#monitorització-i-alertes)
- [Backup i Recuperació](#backup-i-recuperació)
- [Checklist de Seguretat](#checklist-de-seguretat)

---

## Introducció

Nexe Server està dissenyat per a execució **local i segura**. Per defecte, el servidor només és accessible des de `localhost` i requereix autenticació via API key.

**⚠️ IMPORTANT:** No exposeu Nexe directament a Internet sense:
1. ✅ Configurar un reverse proxy (nginx, Caddy)
2. ✅ Habilitar HTTPS amb certificats vàlids
3. ✅ Configurar un firewall
4. ✅ O utilitzar una VPN (Tailscale, WireGuard)

---

## Configuració de Secrets

### 1. Generar Secrets

Nexe requereix secrets criptogràficament segurs en mode producció:

```bash
# Opció 1: Usar el script proporcionat
./scripts/generate_secrets.sh

# Opció 2: Generar manualment
NEXE_PRIMARY_API_KEY=$(openssl rand -hex 32)
NEXE_CSRF_SECRET=$(openssl rand -hex 32)

echo "NEXE_PRIMARY_API_KEY=${NEXE_PRIMARY_API_KEY}"
echo "NEXE_CSRF_SECRET=${NEXE_CSRF_SECRET}"
```

### 2. Configurar .env

```bash
# Copiar plantilla
cp .env.example .env

# Editar amb els secrets generats
nano .env  # o vim, code, etc.
```

### 3. Verificar Permisos

```bash
# Assegurar que només l'usuari pot llegir .env
chmod 600 .env
ls -la .env  # Hauria de mostrar: -rw------- (600)
```

### 4. Variables Obligatòries en Producció

Quan `NEXE_ENV=production`, aquestes variables són **obligatòries**:

- `NEXE_PRIMARY_API_KEY` - API key principal
- `NEXE_CSRF_SECRET` - Secret per protecció CSRF
- `NEXE_APPROVED_MODULES` - Llista de mòduls autoritzats

El servidor **no iniciarà** sense aquestes variables en mode producció.

---

## Deployment Local

### Execució Directa (Desenvolupament)

```bash
# 1. Activar entorn virtual
source venv/bin/activate

# 2. Configurar mode desenvolupament
export NEXE_ENV=development

# 3. Iniciar servidor
python -m core.cli go
```

### Execució com a Servei (Producció)

#### systemd (Linux)

```bash
# Crear fitxer de servei
sudo nano /etc/systemd/system/nexe.service
```

```ini
[Unit]
Description=Nexe Server 0.8
After=network.target

[Service]
Type=simple
User=nexe
Group=nexe
WorkingDirectory=/opt/nexe
EnvironmentFile=/opt/nexe/.env
ExecStart=/opt/nexe/venv/bin/python -m core.cli go
Restart=on-failure
RestartSec=5s

# Security hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/nexe/storage

[Install]
WantedBy=multi-user.target
```

```bash
# Activar i iniciar
sudo systemctl daemon-reload
sudo systemctl enable nexe
sudo systemctl start nexe
sudo systemctl status nexe
```

#### launchd (macOS)

```bash
# Crear plist
nano ~/Library/LaunchAgents/net.jgoy.nexe.plist
```

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>net.jgoy.nexe</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/YOUR_USER/nexe/venv/bin/python</string>
        <string>-m</string>
        <string>core.cli</string>
        <string>go</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/YOUR_USER/nexe</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>NEXE_ENV</key>
        <string>production</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
```

```bash
# Carregar i iniciar
launchctl load ~/Library/LaunchAgents/net.jgoy.nexe.plist
launchctl start net.jgoy.nexe
```

---

## Deployment amb Docker

### 1. Build de la Imatge

```bash
# Build amb usuari no-root (SEGUR)
docker build -t nexe-server:0.8 .

# Verificar que s'executa com a usuari 'nexe'
docker run --rm nexe-server:0.8 whoami
# Output esperat: nexe
```

### 2. Executar amb Docker Compose

```bash
# Iniciar (ports restringits a localhost)
docker-compose up -d

# Verificar logs
docker-compose logs -f

# Aturar
docker-compose down
```

### 3. Configuració de Producció

El `docker-compose.yml` ja està configurat amb seguretat:

```yaml
services:
  nexe:
    ports:
      - "127.0.0.1:9119:9119"  # ✅ Només localhost
    networks:
      - nexe-internal  # ✅ Network privada

  qdrant:
    ports:
      - "127.0.0.1:6333:6333"  # ✅ Només localhost
    networks:
      - nexe-internal  # ✅ Network privada
```

**NO canvieu `127.0.0.1:9119:9119` a `9119:9119`** sense configurar un reverse proxy!

---

## Accés Remot Segur

Si necessiteu accedir a Nexe remotament, utilitzeu **VPN** (recomanat) o **reverse proxy amb HTTPS**.

### Opció 1: VPN amb Tailscale (Recomanat)

Tailscale crea una xarxa privada zero-config amb encriptació WireGuard.

```bash
# 1. Instal·lar Tailscale
curl -fsSL https://tailscale.com/install.sh | sh

# 2. Connectar
sudo tailscale up

# 3. Obtenir IP de Tailscale
tailscale ip -4
# Exemple: 100.101.102.103

# 4. Accedir des d'un altre dispositiu a la VPN
# http://100.101.102.103:9119
```

**Avantatges:**
- ✅ Encriptació end-to-end
- ✅ Zero-config, no cal obrir ports
- ✅ Multi-plataforma (macOS, Linux, Windows, iOS, Android)
- ✅ Autenticació integrada (SSO)

### Opció 2: WireGuard

```bash
# Server (màquina amb Nexe)
sudo apt install wireguard

# Generar claus
wg genkey | tee server_private.key | wg pubkey > server_public.key
wg genkey | tee client_private.key | wg pubkey > client_public.key

# Configurar /etc/wireguard/wg0.conf
[Interface]
PrivateKey = <server_private.key>
Address = 10.0.0.1/24
ListenPort = 51820

[Peer]
PublicKey = <client_public.key>
AllowedIPs = 10.0.0.2/32

# Iniciar
sudo wg-quick up wg0
```

### Opció 3: SSH Tunneling (ràpid per testing)

```bash
# Des del client
ssh -L 9119:localhost:9119 user@server.com

# Accedir a http://localhost:9119 al client
```

---

## Reverse Proxy

Si exposeu Nexe a Internet, **sempre** utilitzeu un reverse proxy amb HTTPS.

### Nginx

```nginx
# /etc/nginx/sites-available/nexe
server {
    listen 443 ssl http2;
    server_name nexe.example.com;

    # SSL/TLS
    ssl_certificate /etc/letsencrypt/live/nexe.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/nexe.example.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    # Security Headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;

    # Rate limiting
    limit_req_zone $binary_remote_addr zone=nexe_limit:10m rate=10r/s;
    limit_req zone=nexe_limit burst=20 nodelay;

    location / {
        proxy_pass http://127.0.0.1:9119;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;

        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
}

# Redirect HTTP to HTTPS
server {
    listen 80;
    server_name nexe.example.com;
    return 301 https://$host$request_uri;
}
```

```bash
# Activar
sudo ln -s /etc/nginx/sites-available/nexe /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### Caddy (més senzill)

```caddyfile
# /etc/caddy/Caddyfile
nexe.example.com {
    reverse_proxy localhost:9119

    # Headers de seguretat (automàtics amb Caddy)
    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
        X-Frame-Options "SAMEORIGIN"
        X-Content-Type-Options "nosniff"
    }

    # Rate limiting
    rate_limit {
        zone static {
            key {remote_host}
            events 10
            window 1s
        }
    }
}
```

```bash
# Caddy obté certificats SSL automàticament!
sudo systemctl reload caddy
```

---

## Monitorització i Alertes

### Health Check

```bash
# Endpoint de salut
curl http://localhost:9119/health

# Resposta esperada
{
  "status": "ok",
  "version": "0.8",
  "modules": {
    "qdrant": "ok",
    "memory": "ok"
  }
}
```

### Prometheus Metrics

```bash
# Metrics disponibles
curl http://localhost:9119/metrics

# Configuració Prometheus
# prometheus.yml
scrape_configs:
  - job_name: 'nexe'
    static_configs:
      - targets: ['localhost:9119']
```

### Alertes amb Grafana

```yaml
# alerts.yml
groups:
  - name: nexe
    interval: 30s
    rules:
      - alert: NexeDown
        expr: up{job="nexe"} == 0
        for: 1m
        annotations:
          summary: "Nexe Server is down"

      - alert: HighMemoryUsage
        expr: process_resident_memory_bytes{job="nexe"} > 4e9
        for: 5m
        annotations:
          summary: "Nexe using >4GB RAM"
```

---

## Backup i Recuperació

### Què cal fer backup?

```
/opt/nexe/
├── .env                    # ⚠️  SECRETS (backup segur!)
├── storage/
│   ├── qdrant/            # ✅ Vectors (RAG)
│   ├── *.db               # ✅ SQLite databases
│   └── logs/              # ⚙️  Opcional
├── knowledge/             # ✅ Documents ingerits
└── personality/           # ✅ Configuració personalitzada
```

### Script de Backup

```bash
#!/bin/bash
# backup_nexe.sh

BACKUP_DIR="/backups/nexe"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
NEXE_DIR="/opt/nexe"

mkdir -p "${BACKUP_DIR}"

# Backup
tar -czf "${BACKUP_DIR}/nexe_${TIMESTAMP}.tar.gz" \
  --exclude="${NEXE_DIR}/venv" \
  --exclude="${NEXE_DIR}/storage/logs" \
  "${NEXE_DIR}"

# Rotar backups (mantenir últims 7 dies)
find "${BACKUP_DIR}" -name "nexe_*.tar.gz" -mtime +7 -delete

echo "✅ Backup completat: ${BACKUP_DIR}/nexe_${TIMESTAMP}.tar.gz"
```

```bash
# Programar amb cron (diari a les 3am)
crontab -e
0 3 * * * /opt/nexe/scripts/backup_nexe.sh
```

### Recuperació

```bash
# 1. Restaurar backup
cd /opt
tar -xzf /backups/nexe/nexe_20260209_030000.tar.gz

# 2. Recrear venv
cd /opt/nexe
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Reiniciar servei
sudo systemctl restart nexe
```

---

## Checklist de Seguretat

### Pre-Deployment

- [ ] Secrets rotats i configurats (`.env`)
- [ ] `.env` **NO** està al repositori Git
- [ ] Permisos de `.env` configurats a 600
- [ ] `NEXE_ENV=production` configurat
- [ ] `NEXE_APPROVED_MODULES` definit
- [ ] Dependencies actualitzades (`pip-audit`)
- [ ] Docker amb usuari no-root (`USER nexe`)
- [ ] Ports restringits a localhost (`127.0.0.1:9119:9119`)

### Post-Deployment

- [ ] Health check funciona (`/health`)
- [ ] Autenticació API key funciona
- [ ] CSRF protection activa
- [ ] Rate limiting actiu
- [ ] Logs configurats i rotats
- [ ] Backups configurats
- [ ] Monitorització activa
- [ ] Alertes configurades

### Si Exposat a Internet

- [ ] Reverse proxy configurat (nginx/Caddy)
- [ ] HTTPS amb certificats vàlids
- [ ] Security headers configurats
- [ ] Firewall actiu (ufw, iptables)
- [ ] Fail2ban configurat
- [ ] Rate limiting reforçat
- [ ] Logs d'accés monitoritzats
- [ ] Intrusion detection (OSSEC, Wazuh)

---

## Contacte i Suport

- **Documentació:** `README.md`, `SECURITY.md`
- **Issues:** [GitHub Issues](https://github.com/YOUR_ORG/nexe/issues)
- **Seguretat:** security@jgoy.net (reportar vulnerabilitats)

---

**Recomanació final:** Per a ús personal/local, utilitzeu **Tailscale** per accés remot segur. És la manera més senzilla i segura d'accedir a Nexe des de qualsevol lloc sense exposar ports a Internet.
