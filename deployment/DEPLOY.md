# FinAI — Deployment Guide

**Server IP:** `72.62.239.220`
**Stack:** Django 4.2 · Gunicorn · Nginx · MySQL · Redis · Celery
**OS:** Ubuntu 22.04 LTS

---

## Environments

| Environment | Domain | Branch | Path |
|-------------|--------|--------|------|
| **Live** | `tadgeeg.com` / `www.tadgeeg.com` | `master` | `/var/www/live/` |
| **Dev** | `dev.tadgeeg.com` / `www.dev.tadgeeg.com` | `dev` | `/var/www/dev/` |
| **Test** | `test.tadgeeg.com` / `www.test.tadgeeg.com` | `test` | `/var/www/test/` |

---

## Before You Start

### 1. Point DNS Records

In your DNS provider, create **A records** for all domains pointing to `72.62.239.220`:

```
tadgeeg.com          A  72.62.239.220
www.tadgeeg.com      A  72.62.239.220
dev.tadgeeg.com      A  72.62.239.220
www.dev.tadgeeg.com  A  72.62.239.220
test.tadgeeg.com     A  72.62.239.220
www.test.tadgeeg.com A  72.62.239.220
```

> DNS propagation takes 5–30 minutes. SSL issuance (Step 06) will fail if DNS is not ready.

---

### 2. Run the Setup Script (Recommended)

`setup_server.sh` clones the project, generates all three env config files interactively, and optionally creates the `.secret.env` files — all in one step.

**From your local machine:**
```bash
scp deployment/setup_server.sh root@72.62.239.220:/root/
ssh root@72.62.239.220
bash /root/setup_server.sh
```

The script will prompt you for:
- GitHub repo URL + Personal Access Token
- Server IP and alert email
- Domain names, branches, and web roots per environment
- OpenAI API key, Django secret key, and DB passwords

After it completes, skip to [Full Deployment](#full-deployment).

---

### 3. Manual Setup (Alternative to `setup_server.sh`)

Only follow §3.1–§3.4 if you prefer manual setup instead of `setup_server.sh`.

#### 3.1 Clone the Repository

```bash
# On the server
git clone https://YOUR_TOKEN@github.com/mohammed0115/tadgeeg.git /root/finai-deploy
cd /root/finai-deploy/deployment
chmod +x *.sh
```

#### 3.2 Set Your GitHub Repo URL

Edit each config file and set `REPO_URL` to your actual repository:

```bash
nano deployment/config/live.env   # REPO_URL="https://github.com/mohammed0115/tadgeeg.git"
nano deployment/config/dev.env
nano deployment/config/test.env
```

#### 3.3 Create the Secret Files

Each environment needs a `.secret.env` file on the server. **This file is never committed to Git.**

```bash
# Live
mkdir -p /var/www/live
cat > /var/www/live/.secret.env <<EOF
OPENAI_API_KEY=sk-...
SECRET_KEY=your-django-secret-key
DB_PASSWORD=strong_db_password_here
DB_ROOT_PASSWORD=strong_root_password_here
ALERT_EMAIL=admin@tadgeeg.com
EOF
chmod 600 /var/www/live/.secret.env

# Dev
mkdir -p /var/www/dev
cat > /var/www/dev/.secret.env <<EOF
OPENAI_API_KEY=sk-...
SECRET_KEY=your-dev-secret-key
DB_PASSWORD=dev_db_password
DB_ROOT_PASSWORD=dev_root_password
ALERT_EMAIL=admin@tadgeeg.com
EOF
chmod 600 /var/www/dev/.secret.env

# Test
mkdir -p /var/www/test
cat > /var/www/test/.secret.env <<EOF
OPENAI_API_KEY=sk-...
SECRET_KEY=your-test-secret-key
DB_PASSWORD=test_db_password
DB_ROOT_PASSWORD=test_root_password
ALERT_EMAIL=admin@tadgeeg.com
EOF
chmod 600 /var/www/test/.secret.env
```

#### 3.4 Copy Deployment Scripts to Server

```bash
# From your local machine (if not already cloned)
scp -r deployment/ root@72.62.239.220:/root/finai-deploy/
ssh root@72.62.239.220
cd /root/finai-deploy/deployment
chmod +x *.sh
```

---

## Full Deployment

Run once per environment. Takes ~10–15 minutes per environment.

```bash
cd /root/finai-deploy/deployment

# Live server
bash deploy_finish.sh live

# Dev server
bash deploy_finish.sh dev

# Test server
bash deploy_finish.sh test
```

> Live deployment asks for confirmation before proceeding.

---

## What Each Step Does

### `bash 00_env_check.sh [live|dev|test]`
Verifies the server meets minimum requirements before starting:
- Ubuntu OS
- Root privileges
- Disk space ≥ 10 GB
- RAM ≥ 2 GB
- Internet connectivity
- Checks Python, Git, MySQL, Nginx presence

---

### `bash 01_git_sync.sh [live|dev|test]`
Syncs the application code from GitHub:
- **If repo missing:** clones fresh from `REPO_URL` on the correct branch
- **If repo exists:** fetches + hard-resets to `origin/<branch>` (server is read-only)
- Uses a lock file to prevent concurrent syncs

---

### `bash 02_system_setup.sh [live|dev|test]`
Installs all system dependencies:
- Upgrades apt packages
- Installs: Nginx, Git, curl, build-essential, libmysqlclient-dev, Redis
- Installs Python 3.12 (from deadsnakes PPA if not present)
- Creates virtualenv at `<WEB_ROOT>/app/backend/venv`
- Installs Python packages from `requirements.txt`
- Enables and starts Redis
- Creates directory structure: `<WEB_ROOT>/app`, `static/`, `media/`, `logs/`

---

### `bash 03_ocr_setup.sh [live|dev|test]`
Installs OCR and AI dependencies:
- Tesseract OCR with Arabic (`ara`) and English (`eng`) language packs
- Sets `TESSDATA_PREFIX` in `/etc/environment`
- poppler-utils (PDF → image conversion)
- libmagic (MIME type detection)
- OpenCV system libraries
- Python packages: `pytesseract`, `Pillow`, `opencv-python-headless`, `PyMuPDF`, `pdfplumber`, `python-magic`, `openai`
- Loads `OPENAI_API_KEY` from `.secret.env`

---

### `bash 04_gunicorn_service.sh [live|dev|test]`
Sets up Django application as a systemd service:
- Runs `python manage.py migrate --noinput`
- Runs `python manage.py collectstatic --noinput`
- Copies static files to `<STATIC_ROOT>`
- Creates **3 systemd services**:
  - `finai_<env>` — Gunicorn application server
  - `finai_<env>_celery` — Celery async worker
  - `finai_<env>_celerybeat` — Celery beat scheduler
- Injects secrets from `.secret.env` as `Environment=` entries
- Enables and starts all three services

**Service configuration per environment:**

| | Live | Dev | Test |
|--|------|-----|------|
| Gunicorn workers | 5 | 3 | 2 |
| Timeout | 120s | 180s | 180s |
| Max requests | 1000 | 500 | 200 |
| Redis DB | 0 | 1 | 2 |

---

### `bash 05_nginx_setup.sh [live|dev|test]`
Configures Nginx as reverse proxy:
- Writes site config to `/etc/nginx/sites-available/finai_<env>`
- Enables the site via symlink
- Removes the default Nginx site (first run only)
- Configuration includes:
  - HTTP → HTTPS redirect
  - Rate limiting: 30 req/min for API, 10 req/min for uploads
  - WebSocket proxy (`/ws/`) for Django Channels
  - Static files served directly (30-day cache)
  - Media files with Content-Disposition for documents
  - Security headers (X-Frame-Options, X-Content-Type-Options, X-XSS-Protection)
  - HSTS enabled on live only

---

### `bash 06_ssl_setup.sh [live|dev|test]`
Obtains and manages SSL certificates via Let's Encrypt:
- Installs Certbot if not present
- Checks DNS resolution for the domain
- **If no certificate:** issues new certificate for all domain variants
- **If certificate exists:** checks expiry — renews only if < 30 days remaining
- Sets up auto-renewal cron at 3:00 AM daily
- Runs a dry-run to verify renewal works

---

### `bash 07_monitoring.sh [live|dev|test]`
Sets up health monitoring and log rotation:
- Creates health check script at `/usr/local/bin/finai_health_<env>.sh`
- Installs cron to run health check **every 5 minutes**
- Health check verifies:
  - All systemd services are running (auto-restarts if down)
  - HTTP endpoint returns 2xx/3xx
  - Disk space > 2 GB
  - MySQL connection works
  - Redis responds to ping
  - Gunicorn socket exists
- Configures logrotate: 14-day retention, daily rotation, compressed

---

### `bash 08_notifications.sh [live|dev|test]`
Sets up email alerting:
- Installs mail utilities (mailutils/postfix)
- Creates alert script that emails on health check failures
- Adds `OnFailure=` systemd override for Gunicorn and Celery
- Sends deployment success email to `ALERT_EMAIL`

---

## Quick Refresh (After Code Changes)

Use this instead of a full deployment when only code has changed:

```bash
bash refresh.sh live
bash refresh.sh dev
bash refresh.sh test
```

**What refresh does (8 steps, ~2 minutes):**

1. `git fetch + reset --hard` to latest branch commit
2. `pip install -r requirements.txt` (skips unchanged)
3. `python manage.py migrate --noinput`
4. `python manage.py collectstatic --noinput --clear`
5. Copy static files to web root + fix permissions
6. Restart Gunicorn + Celery + Celerybeat
7. Test Nginx config + reload Nginx
8. HTTP smoke test against `/health/` endpoint

---

## Docker Deployment

For a fully containerised deployment using Docker Compose.

> **Prerequisite:** Config files must exist. Run `setup_server.sh` or §3.1–§3.3 first.

```bash
bash live_deployment.sh live
bash live_deployment.sh dev
bash live_deployment.sh test
```

**What it does:**
- Installs Docker Engine if not present
- Auto-generates `docker-compose.<env>.yml`
- Auto-generates MySQL init SQL
- Builds the Django image
- Starts: `web` · `celery` · `celerybeat` · `db` (MySQL 8) · `redis` · `nginx`
- Waits for DB health before starting the app
- Prunes dangling images on completion

**Docker container names:**

| Container | Live | Dev | Test |
|-----------|------|-----|------|
| Web | `finai_live_web` | `finai_dev_web` | `finai_test_web` |
| Celery | `finai_live_celery` | `finai_dev_celery` | `finai_test_celery` |
| DB | `finai_live_db` | `finai_dev_db` | `finai_test_db` |
| Redis | `finai_live_redis` | `finai_dev_redis` | `finai_test_redis` |

---

## Git Auto-Deploy

Automatically deploys when a branch is pushed to GitHub.

**Install once on the server:**
```bash
cd /root/finai-deploy/deployment
bash git_.sh install
```

**How it works:**
- Runs as a systemd service (`finai_git_autodeploy`)
- Polls all 3 repos every **60 seconds**
- When new commits are detected on a branch → runs `refresh.sh` for that environment
- Prevents concurrent deploys using lock files
- Sends failure email if auto-deploy fails

**Branch → Environment mapping:**

| Branch | Environment | Domain |
|--------|-------------|--------|
| `master` | Live | `tadgeeg.com` |
| `dev` | Dev | `dev.tadgeeg.com` |
| `test` | Test | `test.tadgeeg.com` |

> **Note:** If your live branch is `main` instead of `master`, update `BRANCH="main"` in `deployment/config/live.env` and the mapping in `git_.sh`.

**Manual control:**
```bash
bash git_.sh status    # show daemon status + last 20 log lines
bash git_.sh stop      # stop daemon
bash git_.sh restart   # restart daemon
```

---

## Checking Service Status

```bash
# View all FinAI services
systemctl status finai_live finai_live_celery finai_live_celerybeat

# View live logs
journalctl -u finai_live -f
journalctl -u finai_live_celery -f

# Nginx logs
tail -f /var/log/nginx/finai_live_access.log
tail -f /var/log/nginx/finai_live_error.log

# Application logs
tail -f /var/log/finai/live/error.log
tail -f /var/log/finai/live/health.log
```

---

## File & Directory Structure on Server

```
/root/finai-deploy/               ← Cloned repository (deployment scripts)
└── deployment/
    ├── config/
    │   ├── live.env
    │   ├── dev.env
    │   └── test.env
    ├── setup_server.sh           ← Run first to configure environments
    ├── deploy_finish.sh
    ├── refresh.sh
    └── *.sh

/var/www/
├── live/                         ← Repo cloned here (manage.py at root)
│   ├── manage.py
│   ├── requirements.txt
│   ├── finai_backend/            ← Django project package
│   ├── apps/
│   ├── core/
│   ├── venv/                     ← Python virtualenv
│   ├── staticfiles/              ← collectstatic output
│   ├── media/                    ← User uploaded files
│   ├── deployment/               ← Deployment scripts
│   └── .secret.env               ← Secrets (never in Git)
├── dev/                          ← Same structure (dev branch)
└── test/                         ← Same structure (test branch)

/var/log/finai/
├── live/
│   ├── access.log                ← Gunicorn access log
│   ├── error.log                 ← Gunicorn error log
│   ├── celery.log
│   ├── health.log                ← Health check results
│   ├── git_sync.log
│   └── deployments.log           ← Deployment history
├── dev/
└── test/

/etc/nginx/sites-available/
├── finai_live                    ← Nginx config (live)
├── finai_dev
└── finai_test

/etc/systemd/system/
├── finai_live.service
├── finai_live_celery.service
├── finai_live_celerybeat.service
├── finai_dev.service
├── finai_dev_celery.service
└── ...

/etc/letsencrypt/live/
├── tadgeeg.com/                  ← SSL certificate (live)
├── dev.tadgeeg.com/
└── test.tadgeeg.com/
```

---

## Manual Service Commands

```bash
# Restart application only
systemctl restart finai_live

# Restart everything for an environment
systemctl restart finai_live finai_live_celery finai_live_celerybeat

# Reload Nginx (zero-downtime config reload)
nginx -t && systemctl reload nginx

# Check Gunicorn socket
ls -la /run/finai_live.sock

# Run Django management commands
cd /var/www/live
source venv/bin/activate
python manage.py shell
python manage.py createsuperuser
```

---

## Troubleshooting

### Site shows 502 Bad Gateway
```bash
# Check if Gunicorn is running
systemctl status finai_live

# Check socket exists
ls -la /run/finai_live.sock

# Restart Gunicorn
systemctl restart finai_live

# Check last 50 lines of error log
journalctl -u finai_live -n 50 --no-pager
```

### Static files not loading (404)
```bash
# Re-run collectstatic
cd /var/www/live
source venv/bin/activate
python manage.py collectstatic --noinput --clear

# Copy to web root
cp -r staticfiles/. /var/www/live/staticfiles/
chown -R www-data:www-data /var/www/live/staticfiles/
chmod -R 755 /var/www/live/staticfiles/

# Check admin static
ls -la /var/www/live/staticfiles/admin/
```

### SSL certificate error
```bash
# Check certificate status
certbot certificates

# Force renew
certbot renew --force-renewal

# Reload nginx after renewal
systemctl reload nginx
```

### Database migration error
```bash
cd /var/www/live
source venv/bin/activate

# Show pending migrations
python manage.py showmigrations

# Run manually with verbose output
python manage.py migrate --verbosity 2
```

### OCR not working
```bash
# Check Tesseract
tesseract --version
tesseract --list-langs

# Check TESSDATA path
echo $TESSDATA_PREFIX

# Re-run OCR setup
bash /root/finai-deploy/deployment/03_ocr_setup.sh live
```

### Celery tasks not running
```bash
# Check Celery worker status
systemctl status finai_live_celery

# Check task queue
cd /var/www/live
source venv/bin/activate
celery -A finai_backend inspect active

# Restart Celery
systemctl restart finai_live_celery finai_live_celerybeat
```

### Config files missing after clone
```bash
# Re-run the setup script
bash /root/finai-deploy/deployment/setup_server.sh
```

---

## Environment Config Reference

| Variable | Live | Dev | Test |
|----------|------|-----|------|
| `SERVER_IP` | `72.62.239.220` | `72.62.239.220` | `72.62.239.220` |
| `WEB_ROOT` | `/var/www/live` | `/var/www/dev` | `/var/www/test` |
| `DOMAIN_MAIN` | `tadgeeg.com` | `dev.tadgeeg.com` | `test.tadgeeg.com` |
| `BRANCH` | `master` | `dev` | `test` |
| `GUNICORN_WORKERS` | `5` | `3` | `2` |
| `REDIS_URL` | `redis://...6379/0` | `redis://...6379/1` | `redis://...6379/2` |
| `DB_NAME` | `finai_live` | `finai_dev` | `finai_test` |
| `DEBUG` | `False` | `True` | `True` |
| `PORT` | `8001` | `8002` | `8003` |

---

## Deployment Checklist

Before deploying, verify:

- [ ] DNS A records pointing to `72.62.239.220`
- [ ] `setup_server.sh` has been run **or** config files exist in `deployment/config/`
- [ ] `.secret.env` exists for each environment with real `OPENAI_API_KEY` and `SECRET_KEY`
- [ ] `REPO_URL` set correctly in each `config/<env>.env`
- [ ] MySQL running and credentials correct
- [ ] At least 10 GB disk free on server
- [ ] `master` branch has been tested on `dev` first

After deploying:

- [ ] `https://tadgeeg.com` loads correctly
- [ ] `https://tadgeeg.com/health/` returns 200
- [ ] Admin panel accessible at `https://tadgeeg.com/admin/`
- [ ] Static files loading (check browser dev tools)
- [ ] File upload works end-to-end
- [ ] Check `/var/log/finai/live/error.log` for errors
