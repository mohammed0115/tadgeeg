# FinAI — Server Setup TODO List

**Server:** `root@72.62.239.220`
**OS:** Ubuntu 22.04 LTS

> **Everything from Phase 2 onwards is automated by `server_init.sh`.**
> You only need to do Phase 1 manually (DNS), then run one command.

---

## PHASE 1 — Before Touching the Server (Manual)

### [ ] 1.1 — Point DNS Records

Go to your DNS provider and add these **A records**:

```
tadgeeg.com          →  72.62.239.220
www.tadgeeg.com      →  72.62.239.220
dev.tadgeeg.com      →  72.62.239.220
www.dev.tadgeeg.com  →  72.62.239.220
test.tadgeeg.com     →  72.62.239.220
www.test.tadgeeg.com →  72.62.239.220
```

> Wait 10–30 minutes for DNS to propagate. SSL will fail if DNS is not ready.

### [ ] 1.2 — Prepare These Credentials

Have these ready before running the script:

| Item | Example |
|------|---------|
| GitHub Personal Access Token | `ghp_xxxxxxxxxxxx` (needs `repo` scope) |
| OpenAI API Key | `sk-proj-xxxx` |
| MySQL root password | new strong password |
| DB password for LIVE | `Str0ng!LivePass` |
| DB password for DEV | `Str0ng!DevPass` |
| DB password for TEST | `Str0ng!TestPass` |
| Django superuser username | `admin` |
| Django superuser password | strong password |

---

## PHASE 2 — Run the Init Script (Fully Automated)

Everything below is handled automatically by `server_init.sh`:
- System update
- MySQL install + secure + create DBs & users
- Clone repo → write env configs → write `.secret.env` files
- Full deployment: dev → test → live (9 steps each)
- Django superuser creation
- UFW firewall setup
- Git auto-deploy daemon (optional)

### [ ] 2.1 — SSH into the Server

```bash
ssh root@72.62.239.220
```

### [ ] 2.2 — Install Git (if not present)

```bash
git --version || apt-get install -y git
```

### [ ] 2.3 — Copy the Script to the Server

From your **local machine**:
```bash
scp deployment/server_init.sh root@72.62.239.220:/root/
```

### [ ] 2.4 — Run It

Back on the **server**:
```bash
bash /root/server_init.sh
```

The script asks for all inputs **once at the start**, then runs everything automatically.

**Prompts you will see:**

| Prompt | Value |
|--------|-------|
| GitHub repo URL | `https://github.com/mohammed0115/tadgeeg.git` |
| GitHub token | your `ghp_xxx` token |
| Server IP | `72.62.239.220` *(Enter for default)* |
| Alert email | `admin@tadgeeg.com` *(Enter for default)* |
| OpenAI API key | `sk-proj-...` |
| MySQL root password | choose a strong password |
| DB password LIVE / DEV / TEST | your 3 DB passwords |
| Django SECRET_KEY × 3 | press Enter to auto-generate |
| Superuser username / email / password | your admin credentials |
| Install auto-deploy daemon? | `y` or `N` |
| Environments to deploy | `dev,test,live` *(Enter for default)* |
| Final confirm | type `yes` |

**What runs automatically after you type `yes`:**

| Step | What happens |
|------|-------------|
| 1 | `apt update && upgrade`, installs git, ufw, fail2ban |
| 2 | Installs MySQL, secures it, creates 3 databases + 3 users |
| 3 | Clones repo → `/root/finai-deploy/` |
| 4 | Writes `config/live.env`, `dev.env`, `test.env` |
| 5 | Writes `/var/www/{live,dev,test}/.secret.env` (chmod 600) |
| 6 | Runs `deploy_finish.sh dev` → `test` → `live` (9 sub-steps each) |
| 7 | Creates Django superuser non-interactively |
| 8 | Installs git auto-deploy daemon (if chosen) |
| 9 | Configures UFW firewall (SSH + 80 + 443 only) |

Each `deploy_finish.sh` run executes:

| Sub-step | Script | What it does |
|----------|--------|-------------|
| 1 | `00_env_check.sh` | Checks OS, RAM ≥ 2GB, disk ≥ 10GB, internet |
| 2 | `01_git_sync.sh` | Clones/pulls code to `/var/www/<env>` |
| 3 | `02_system_setup.sh` | Installs Nginx, Python 3.12, Redis, venv, pip |
| 4 | `03_ocr_setup.sh` | Installs Tesseract (ara+eng), poppler, OpenCV, OpenAI SDK |
| 5 | `04_gunicorn_service.sh` | Runs migrations, collectstatic, creates 3 systemd services |
| 6 | `05_nginx_setup.sh` | Configures Nginx with rate limiting, HTTPS, WebSocket |
| 7 | `06_ssl_setup.sh` | Issues Let's Encrypt SSL, sets auto-renewal cron |
| 8 | `07_monitoring.sh` | Health check every 5 min, logrotate 14-day retention |
| 9 | `08_notifications.sh` | Email alerts on service failure |

**Total time:** ~25–40 minutes for all 3 environments.

**Log file:** `/var/log/finai_server_init.log`

---

## PHASE 3 — Verify Everything Works

Run these checks after the script finishes.

### [ ] 3.1 — Check All Services

```bash
systemctl status finai_live finai_live_celery finai_live_celerybeat
systemctl status finai_dev  finai_dev_celery  finai_dev_celerybeat
systemctl status finai_test finai_test_celery finai_test_celerybeat
systemctl status nginx redis-server
```

All should show `active (running)`.

### [ ] 3.2 — Smoke Test URLs

```bash
curl -sk -o /dev/null -w "%{http_code}" https://tadgeeg.com/health/
curl -sk -o /dev/null -w "%{http_code}" https://dev.tadgeeg.com/health/
curl -sk -o /dev/null -w "%{http_code}" https://test.tadgeeg.com/health/
```

Expected: `200` for all three.

### [ ] 3.3 — Verify in Browser

| URL | Expected |
|-----|----------|
| `https://tadgeeg.com` | Site loads |
| `https://tadgeeg.com/health/` | 200 OK |
| `https://tadgeeg.com/admin/` | Django admin login |
| `https://dev.tadgeeg.com` | Dev site loads |
| `https://test.tadgeeg.com` | Test site loads |

### [ ] 3.4 — Check SSL Certificates

```bash
certbot certificates
```

Should show valid certificates for all 3 domains with expiry dates.

### [ ] 3.5 — Check Logs for Errors

```bash
tail -50 /var/log/finai/live/error.log
journalctl -u finai_live -n 30 --no-pager
```

---

## PHASE 4 — Optional: Git Auto-Deploy

*(Skip if you answered `y` during `server_init.sh`)*

```bash
cd /root/finai-deploy/deployment
bash git_.sh install
bash git_.sh status
```

**Branch → Environment mapping:**

| Push to branch | Auto-deploys |
|----------------|-------------|
| `master` | live (`tadgeeg.com`) |
| `dev` | dev (`dev.tadgeeg.com`) |
| `test` | test (`test.tadgeeg.com`) |

---

## PHASE 5 — Ongoing Maintenance

### After code changes (auto-deploy enabled)
```bash
git push origin master   # deploys to live automatically
git push origin dev      # deploys to dev automatically
```

### Manual refresh after code changes
```bash
bash /root/finai-deploy/deployment/refresh.sh live
bash /root/finai-deploy/deployment/refresh.sh dev
```

### Check health
```bash
systemctl status finai_live
curl -sk https://tadgeeg.com/health/
tail -f /var/log/finai/live/health.log
```

### Force SSL renewal
```bash
certbot renew --force-renewal && systemctl reload nginx
```

---

## Quick Reference — Common Commands

```bash
# Restart all live services
systemctl restart finai_live finai_live_celery finai_live_celerybeat

# Reload Nginx config (zero downtime)
nginx -t && systemctl reload nginx

# View live application errors
journalctl -u finai_live -f

# Django shell
cd /var/www/live && source venv/bin/activate && python manage.py shell

# Check disk space
df -h /var/www

# Check Gunicorn socket
ls -la /run/finai_live.sock

# View init log
cat /var/log/finai_server_init.log
```

---

## Checklist Summary

```
PHASE 1 — Local prep (manual)
  [ ] DNS A records set for all 6 domains
  [ ] Credentials ready: GitHub token, OpenAI key, MySQL + DB + superuser passwords

PHASE 2 — Automated (server_init.sh)
  [ ] SSH into server
  [ ] git installed
  [ ] scp deployment/server_init.sh root@72.62.239.220:/root/
  [ ] bash /root/server_init.sh  →  type 'yes'  →  wait ~30 min

PHASE 3 — Verify
  [ ] All systemd services: active (running)
  [ ] curl /health/ returns 200 for live, dev, test
  [ ] All URLs load in browser
  [ ] SSL certificates valid (certbot certificates)
  [ ] No errors in /var/log/finai/live/error.log

PHASE 4 — Auto-deploy (optional, if not done in init)
  [ ] bash git_.sh install

PHASE 5 — Done 🎉
```
