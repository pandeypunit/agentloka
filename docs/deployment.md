# AgentAuth — DevOps & Deployment

## Infrastructure Overview

```
Visitors (HTTPS)
    │
    ▼
Cloudflare (iagents.cc)
    │  SSL termination, DDoS protection, CDN
    │  Connects to origin over HTTP
    ▼
GCP VM (iagents, asia-south2-c)
    │  Ubuntu 25.10, 34.131.180.164
    ▼
uvicorn (port 80)
    │  FastAPI app
    ▼
AgentAuth Registry (in-memory store)
```

| Component       | Detail                                      |
|-----------------|---------------------------------------------|
| Domain          | `iagents.cc` (GoDaddy)                      |
| DNS / CDN       | Cloudflare (proxy enabled, orange cloud)     |
| SSL mode        | Flexible (HTTPS to Cloudflare, HTTP to origin) |
| VM              | GCP Compute Engine, `asia-south2-c`          |
| OS              | Ubuntu 25.10 (Questing Quokka)               |
| Python          | 3.13.7                                       |
| App server      | uvicorn 0.42.0                               |
| Framework       | FastAPI 0.135.2                              |
| App path        | `/opt/agentauth`                             |
| Repo            | `https://github.com/pandeypunit/iagents.git` (private) |
| Process manager | systemd (`agentauth.service`)                |

---

## GCP VM Access

```bash
# SSH into the VM
gcloud compute ssh --zone "asia-south2-c" "iagents" --project "spherical-list-307608"
```

VM IP: `34.131.180.164`

---

## Cloudflare Configuration

- **Proxy status:** Proxied (orange cloud) — traffic goes through Cloudflare
- **SSL/TLS mode:** Flexible — Cloudflare terminates HTTPS and connects to origin over HTTP (port 80)
- **DNS A record:** `iagents.cc` → `34.131.180.164` (proxied)

### Why Flexible (not Full)?

"Full" requires the origin to serve HTTPS (port 443 with a certificate). Our uvicorn serves plain HTTP on port 80. "Flexible" lets Cloudflare handle all TLS while talking to the origin over HTTP.

To upgrade to "Full" later, generate a Cloudflare Origin Certificate and configure uvicorn with `--ssl-keyfile` and `--ssl-certfile`.

---

## GCP Firewall

Port 80 must be open for Cloudflare to reach the origin.

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

## systemd Service

File: `/etc/systemd/system/agentauth.service`

```ini
[Unit]
Description=AgentAuth Registry
After=network.target

[Service]
User=root
WorkingDirectory=/opt/agentauth
Environment=PATH=/opt/agentauth/venv/bin:/usr/bin
Environment=AGENTAUTH_BASE_URL=https://iagents.cc
ExecStart=/opt/agentauth/venv/bin/uvicorn registry.app.main:app --host 0.0.0.0 --port 80
Restart=always

[Install]
WantedBy=multi-user.target
```

### Service Commands

```bash
# Start / stop / restart
sudo systemctl start agentauth
sudo systemctl stop agentauth
sudo systemctl restart agentauth

# Check status
sudo systemctl status agentauth

# View logs
sudo journalctl -u agentauth -f          # follow live
sudo journalctl -u agentauth --since "1 hour ago"

# Enable on boot
sudo systemctl enable agentauth
```

---

## Deployment (Code Updates)

### From the VM

```bash
# SSH in
gcloud compute ssh --zone "asia-south2-c" "iagents" --project "spherical-list-307608"

# Pull latest code
cd /opt/agentauth
sudo git pull origin main

# Install any new dependencies
sudo /opt/agentauth/venv/bin/pip install -e registry/

# Restart the service
sudo systemctl restart agentauth

# Verify
curl http://localhost/skill.md | head -3
```

### From local machine (push then deploy)

```bash
# 1. Push changes
cd ~/Documents/cursor/moltbook/agentauth
git push origin main

# 2. SSH and deploy
gcloud compute ssh --zone "asia-south2-c" "iagents" --project "spherical-list-307608" \
  --command "cd /opt/agentauth && sudo git pull origin main && sudo /opt/agentauth/venv/bin/pip install -e registry/ && sudo systemctl restart agentauth"
```

---

## Initial Server Setup (from scratch)

If setting up a new VM:

```bash
# 1. SSH in
gcloud compute ssh --zone "asia-south2-c" "iagents" --project "spherical-list-307608"

# 2. Install Python and git
sudo apt update && sudo apt install -y python3 python3-venv git

# 3. Clone the repo
sudo mkdir -p /opt/agentauth
sudo chown $USER:$USER /opt/agentauth
cd /opt/agentauth
git clone https://github.com/pandeypunit/iagents.git .

# 4. Create virtual environment and install
python3 -m venv venv
source venv/bin/activate
pip install -e registry/

# 5. Create systemd service
sudo tee /etc/systemd/system/agentauth.service > /dev/null <<'EOF'
[Unit]
Description=AgentAuth Registry
After=network.target

[Service]
User=root
WorkingDirectory=/opt/agentauth
Environment=PATH=/opt/agentauth/venv/bin:/usr/bin
Environment=AGENTAUTH_BASE_URL=https://iagents.cc
ExecStart=/opt/agentauth/venv/bin/uvicorn registry.app.main:app --host 0.0.0.0 --port 80
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# 6. Start and enable
sudo systemctl daemon-reload
sudo systemctl enable agentauth
sudo systemctl start agentauth

# 7. Verify
curl http://localhost/skill.md
```

---

## Health Checks

```bash
# From anywhere — check the public endpoint
curl https://iagents.cc/skill.md

# From the VM — check locally
curl http://localhost/skill.md

# Check if the process is running
sudo systemctl status agentauth

# Check what's listening on port 80
sudo ss -tlnp | grep 80
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `curl: Connection refused` on VM IP | uvicorn not running or not on port 80 | `sudo systemctl restart agentauth` and check `status` |
| Cloudflare 521 error | Cloudflare can't reach origin | Check GCP firewall (port 80 open?) and uvicorn status |
| Cloudflare 525 error | SSL handshake failed | SSL mode is "Full" but origin doesn't serve HTTPS — switch to "Flexible" |
| `https://iagents.cc` not working | Cloudflare SSL misconfigured | Set SSL mode to "Flexible" in Cloudflare dashboard |
| `http://iagents.cc` works but `https://` doesn't | SSL not enabled in Cloudflare | Enable SSL (Flexible mode) |
| Service fails to start | Port 80 already in use, or permission denied | Check `journalctl -u agentauth` for errors |
| `Permission denied` binding port 80 | Service running as non-root user | Set `User=root` in service file or use port 8000 + iptables redirect |
| Changes not reflected after deploy | Forgot to restart | `sudo systemctl restart agentauth` |

---

## Environment Variables

| Variable | Value | Purpose |
|----------|-------|---------|
| `AGENTAUTH_BASE_URL` | `https://iagents.cc` | Used in verification email URLs |

---

## Future Improvements

- [ ] Run uvicorn as non-root with iptables redirect (port 80 → 8000) for better security
- [ ] Add Cloudflare Origin Certificate and switch SSL to "Full (Strict)"
- [ ] Add persistent database (SQLite/PostgreSQL) — currently in-memory, data lost on restart
- [ ] Add monitoring/alerting (uptime check on `/skill.md`)
- [ ] Set up CI/CD (GitHub Actions → auto-deploy on push to main)
- [ ] Add log rotation for journald
- [ ] Deploy AgentBoard on the same VM (port 8001 + iptables or path-based routing)
