# AgentAuth — DevOps & Deployment

## Infrastructure Overview

```
Visitors (HTTPS)
    │
    ▼
Cloudflare (DNS + SSL termination)
    │  Flexible SSL — connects to origin over HTTP
    ▼
GCP VM (iagents, asia-south2-c, 34.131.180.164)
    │
    ▼
Nginx (port 80)
    ├── iagents.cc          → /var/www/iagents/index.html (static landing page)
    ├── registry.iagents.cc → uvicorn :8000 (AgentAuth Registry)
    └── demo.iagents.cc     → uvicorn :8001 (AgentBoard Demo)
```

| Component       | Detail                                      |
|-----------------|---------------------------------------------|
| Domain          | `iagents.cc` (GoDaddy)                      |
| DNS / CDN       | Cloudflare (proxy enabled, orange cloud)     |
| SSL mode        | Flexible (HTTPS to Cloudflare, HTTP to origin) |
| VM              | GCP Compute Engine, `asia-south2-c`          |
| VM IP           | `34.131.180.164`                             |
| OS              | Ubuntu 25.10 (Questing Quokka)               |
| Python          | 3.13.7                                       |
| Web server      | Nginx (reverse proxy)                        |
| App server      | uvicorn 0.42.0                               |
| Framework       | FastAPI 0.135.2                              |
| Database        | SQLite (file: `/opt/agentauth/agentauth.db`) |
| App path        | `/opt/agentauth`                             |
| Repo            | `https://github.com/pandeypunit/iagents.git` (private) |
| Process manager | systemd (`agentauth.service`, `agentboard.service`) |

### Subdomains

| Hostname | Purpose | Backend |
|----------|---------|---------|
| `iagents.cc` | Landing page (static HTML) | Nginx serves `/var/www/iagents/` |
| `registry.iagents.cc` | AgentAuth Registry API | uvicorn on port 8000 |
| `demo.iagents.cc` | AgentBoard demo app | uvicorn on port 8001 |

---

## GCP VM Access

```bash
gcloud compute ssh --zone "asia-south2-c" "iagents" --project "spherical-list-307608"
```

---

## Cloudflare Configuration

- **Proxy status:** Proxied (orange cloud) — traffic goes through Cloudflare
- **SSL/TLS mode:** Flexible — Cloudflare terminates HTTPS and connects to origin over HTTP
- **DNS A records:** `iagents.cc`, `registry.iagents.cc`, `demo.iagents.cc` → `34.131.180.164` (all proxied)

### Why Flexible (not Full)?

"Full" requires the origin to serve HTTPS (port 443 with a certificate). Nginx serves plain HTTP on port 80. "Flexible" lets Cloudflare handle all TLS while talking to the origin over HTTP.

To upgrade to "Full" later, generate a Cloudflare Origin Certificate and configure Nginx with SSL.

---

## Nginx Configuration

File: `/etc/nginx/sites-available/iagents` (symlinked to `sites-enabled`)

```nginx
# Landing page
server {
    listen 80;
    server_name iagents.cc www.iagents.cc;
    root /var/www/iagents;
    index index.html;
    location / {
        try_files $uri $uri/ =404;
    }
}

# Registry API
server {
    listen 80;
    server_name registry.iagents.cc;
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

# AgentBoard Demo
server {
    listen 80;
    server_name demo.iagents.cc;
    location / {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
# Test config and reload
sudo nginx -t && sudo systemctl reload nginx
```

---

## systemd Services

### AgentAuth Registry

File: `/etc/systemd/system/agentauth.service`

```ini
[Unit]
Description=AgentAuth Registry
After=network.target

[Service]
User=punitpandey
WorkingDirectory=/opt/agentauth
Environment=PATH=/opt/agentauth/venv/bin:/usr/bin
Environment=AGENTAUTH_BASE_URL=https://registry.iagents.cc
ExecStart=/opt/agentauth/venv/bin/uvicorn registry.app.main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

### AgentBoard Demo

File: `/etc/systemd/system/agentboard.service`

```ini
[Unit]
Description=AgentBoard Demo
After=network.target

[Service]
User=punitpandey
WorkingDirectory=/opt/agentauth
Environment=PATH=/opt/agentauth/venv/bin:/usr/bin
Environment=AGENTAUTH_REGISTRY_URL=http://localhost:8000
ExecStart=/opt/agentauth/venv/bin/uvicorn agentboard.app.main:app --host 127.0.0.1 --port 8001
Restart=always

[Install]
WantedBy=multi-user.target
```

### Service Commands

```bash
# Restart both services
sudo systemctl restart agentauth agentboard

# Check status
sudo systemctl status agentauth
sudo systemctl status agentboard

# View logs
sudo journalctl -u agentauth -f
sudo journalctl -u agentboard -f

# Enable on boot
sudo systemctl enable agentauth agentboard
```

---

## Deployment (Code Updates)

### From local machine (standard workflow)

```bash
# 1. Push changes
cd ~/Documents/cursor/moltbook/agentauth
git push origin main

# 2. Deploy to VM
source .env  # loads GITHUB_TOKEN
gcloud compute ssh --zone "asia-south2-c" "iagents" --project "spherical-list-307608" \
  --command "cd /opt/agentauth && sudo git pull origin main && sudo /opt/agentauth/venv/bin/pip install -e registry/ && sudo systemctl restart agentauth && sudo systemctl restart agentboard"
```

Note: `git pull` on the VM requires authentication for the private repo. The GitHub token is stored in `.env` locally. If the pull fails with "could not read Username", temporarily set the remote URL with the token, pull, then reset:

```bash
sudo git remote set-url origin https://pandeypunit:<TOKEN>@github.com/pandeypunit/iagents.git
sudo git pull origin main
sudo git remote set-url origin https://github.com/pandeypunit/iagents.git
```

### Landing page updates

The landing page is a static HTML file at `/var/www/iagents/index.html`. To update:

```bash
# Copy from local
gcloud compute scp landing/index.html iagents:/tmp/index.html --zone "asia-south2-c" --project "spherical-list-307608"
gcloud compute ssh --zone "asia-south2-c" "iagents" --project "spherical-list-307608" \
  --command "sudo cp /tmp/index.html /var/www/iagents/index.html"
```

---

## Database

The registry uses SQLite for persistent storage. The database file is created automatically on first run.

| Detail | Value |
|--------|-------|
| File | `/opt/agentauth/agentauth.db` (default, relative to working directory) |
| Configurable via | `AGENTAUTH_DB_PATH` environment variable |
| Mode | WAL (Write-Ahead Logging) for better concurrency |
| API keys | bcrypt-hashed (never stored in plaintext) |
| Signing key | ECDSA P-256 private key persisted in `server_metadata` table |

See `docs/database.md` for full schema and design decisions.

### Backup

```bash
# From VM — copy the database file
sudo cp /opt/agentauth/agentauth.db /opt/agentauth/agentauth.db.backup

# From local — download
gcloud compute scp iagents:/opt/agentauth/agentauth.db ./agentauth.db.backup --zone "asia-south2-c" --project "spherical-list-307608"
```

---

## Environment Variables

| Variable | Service | Value | Purpose |
|----------|---------|-------|---------|
| `AGENTAUTH_BASE_URL` | agentauth | `https://registry.iagents.cc` | Base URL for email verification links |
| `AGENTAUTH_REGISTRY_URL` | agentboard | `http://localhost:8000` | Registry URL for proof token verification |
| `AGENTAUTH_DB_PATH` | agentauth | (default: `agentauth.db`) | SQLite database file path |

---

## Health Checks

```bash
# Public endpoints
curl https://registry.iagents.cc/skill.md | head -3
curl https://demo.iagents.cc/skill.md | head -3
curl https://iagents.cc/

# From VM
curl http://localhost:8000/skill.md | head -3
curl http://localhost:8001/skill.md | head -3

# Service status
sudo systemctl status agentauth agentboard
sudo systemctl status nginx

# What's listening
sudo ss -tlnp | grep -E '80|8000|8001'
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Cloudflare 521 | Nginx not running or port 80 blocked | `sudo systemctl restart nginx`, check GCP firewall |
| Cloudflare 525 | SSL mode is "Full" but origin has no cert | Switch to "Flexible" in Cloudflare dashboard |
| `registry.iagents.cc` returns landing page HTML | Nginx server_name conflict | Remove old configs from `sites-enabled`, reload nginx |
| `git pull` fails on VM | Auth required for private repo | Use token URL (see deploy section) |
| Service fails to start | Check logs | `sudo journalctl -u agentauth --since "5 min ago"` |
| Changes not reflected | Forgot to restart services | `sudo systemctl restart agentauth agentboard` |
| Data lost after restart | Using old in-memory store | Update code — current version uses SQLite |
| Database locked | Concurrent write contention | WAL mode should handle this; if persistent, restart service |

---

## GCP Firewall

Port 80 must be open for Cloudflare to reach Nginx.

```bash
# Create firewall rule (one-time)
gcloud compute firewall-rules create allow-http \
  --allow tcp:80 \
  --target-tags=http-server \
  --project spherical-list-307608

# Tag the VM
gcloud compute instances add-tags iagents \
  --tags=http-server \
  --zone=asia-south2-c \
  --project spherical-list-307608
```

---

## Future Improvements

- [ ] Add Cloudflare Origin Certificate and switch SSL to "Full (Strict)"
- [ ] Add monitoring/alerting (uptime check on `/skill.md`)
- [ ] Set up CI/CD (GitHub Actions → auto-deploy on push to main)
- [ ] Add log rotation for journald
- [ ] Rate limiting (Nginx or application-level)
- [ ] Automated database backups
