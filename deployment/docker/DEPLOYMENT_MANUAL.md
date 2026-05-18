# Tadgeeg — Docker Deployment Manual

End-to-end guide for deploying Tadgeeg with Docker on a single VPS, covering
three independent environments side-by-side:

| Env  | Domain               | DB volume          | Container names           |
| ---- | -------------------- | ------------------ | ------------------------- |
| live | tadgeeg.com          | mysql_live_data    | web_live, db_live, celery_live |
| dev  | dev.tadgeeg.com      | mysql_dev_data     | web_dev, db_dev, celery_dev    |
| test | test.tadgeeg.com     | mysql_test_data    | web_test, db_test         |

All three share one **nginx** reverse proxy and one **redis** instance.

---

## 1. Prerequisites

### 1.1 Server
- Ubuntu 22.04 / 24.04, x86_64
- Min: 2 vCPU, 4 GB RAM, 40 GB disk (for one env). Add ~1.5 GB RAM and ~10 GB per extra env.
- Public IPv4
- Root or sudo SSH access

### 1.2 DNS
For each environment you want, create an **A record** that points the host name
to the server's IPv4. Example for the test env on Cloudflare/Route53/etc:

```
A    test.tadgeeg.com    →   69.62.115.97
```

> Skip `www.*` records unless you have them — Let's Encrypt will fail otherwise.
> If you want `www`, also add an A record for `www.test.tadgeeg.com`.

### 1.3 Firewall / cloud panel
Open inbound TCP **80** and **443** on the VPS provider's firewall
(Hostinger/Linode/DigitalOcean/AWS Security Group, etc.). `ERR_CONNECTION_TIMED_OUT`
in the browser almost always means these ports are still closed at the provider
level.

### 1.4 Local prerequisites (your laptop)
- `git`, `ssh` configured against the deploy server
- A GitHub account with read access to the repo

---

## 2. Initial server bootstrap

Run these once on a fresh server.

### 2.1 Install Docker (if not present)
```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
  sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

docker --version
docker compose version
```

### 2.2 Remove any host-level nginx
The Docker nginx container binds host ports 80/443. A system-installed nginx
will block it with `address already in use`.

```bash
sudo systemctl stop nginx 2>/dev/null
sudo systemctl disable nginx 2>/dev/null
sudo apt-get remove -y nginx nginx-common nginx-core 2>/dev/null
sudo ss -tlnp | grep -E ':(80|443)\s' || echo "ports 80/443 are free"
```

### 2.3 Clone the repo
```bash
sudo mkdir -p /root/finai-deploy
cd /root/finai-deploy
git clone https://github.com/<owner>/tadgeeg.git .
git checkout main
```

> If you've already been deploying via another path (e.g. `/var/www/test`),
> remove that path so it doesn't conflict.

---

## 3. Configuration

### 3.1 Create the env files
```bash
cd /root/finai-deploy
bash deployment/docker/deploy.sh init-env
```

This copies `*.env.example` → `*.env` for every environment. Edit only the envs
you need (you can leave the others alone — they just sit idle).

### 3.2 Required values per env

Edit each `deployment/docker/env/{env}.env` and set, **at minimum**:

| Variable | Notes |
| --- | --- |
| `DJANGO_SECRET_KEY` | 50+ random chars. `openssl rand -base64 60` |
| `SECRET_KEY` | Same value as above |
| `DEBUG` | `False` in production, `True` only on dev if needed |
| `ALLOWED_HOSTS` | Comma-separated, e.g. `test.tadgeeg.com,www.test.tadgeeg.com`. **Drop `www.*` if no DNS for it.** |
| `CSRF_TRUSTED_ORIGINS` | Comma-separated `https://...` |
| `SERVER_NAMES` | Space-separated. Used by nginx + certbot. **Drop `www.*` if no DNS.** |
| `SITE_URL` | Public HTTPS URL |
| `ENABLE_SECURE_PROXY_SSL_HEADER` | **MUST be `True`** — otherwise you get an infinite redirect loop after HTTPS is enabled |
| `DB_PASSWORD` | Random strong password |
| `MYSQL_PASSWORD` | **Must equal `DB_PASSWORD`** |
| `MYSQL_ROOT_PASSWORD` | Different random strong password |
| `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` | Gmail app password or SMTP creds — required, app crashes without them |
| `SSL_EMAIL` | Email for Let's Encrypt expiry notices |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Optional, only if Google SSO needed |
| `OPENAI_API_KEY` | Optional, only if AI features enabled |

> **Common trap:** `MYSQL_PASSWORD` and `DB_PASSWORD` must match. They go into
> different containers but describe the same MySQL user. If they don't match,
> the web container loops on `Access denied for user`.

### 3.3 Generate strong secrets quickly
```bash
# Django secret
openssl rand -base64 60 | tr -d '\n='

# DB password (alnum, safe for connection strings)
openssl rand -base64 24 | tr -dc 'A-Za-z0-9' | head -c 28
```

---

## 4. Bring up the stack

### 4.1 Start everything HTTP-only first

```bash
cd /root/finai-deploy
bash deployment/docker/deploy.sh up test     # or: up live / up dev / up all
```

What this does:
1. Builds the web image from the repo's `Dockerfile`.
2. Starts `db_test` (MySQL 8.4) + `redis` + `web_test` + `nginx`.
3. Renders an HTTP-only nginx config.
4. Entrypoint inside `web_test` runs migrations, compiles translations, and
   collects static files.

### 4.2 Confirm it's running
```bash
bash deployment/docker/deploy.sh ps
```

Expect (for `test`):
```
db_test     Up (healthy)
redis       Up (healthy)
web_test    Up
nginx       Up    0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
```

If `nginx` PORTS column is empty → another nginx is binding 80/443. Re-run
section 2.2.

### 4.3 Local smoke test (inside the server)
```bash
# Through nginx
curl -i http://127.0.0.1/health/

# Direct to the app
docker compose -f deployment/docker/docker-compose.yml exec web_test \
  curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/health/
```

Both should return 200 (or 301 after HTTPS is enabled).

---

## 5. Enable HTTPS

### 5.1 All environments at once (only when DNS is set for *all* of them)
```bash
cd /root/finai-deploy
bash deployment/docker/enable_https.sh
```

This issues Let's Encrypt certs for live, dev, and test, then re-renders nginx
with `listen 443 ssl` blocks and reloads.

### 5.2 One environment only (recommended for new servers)

If `tadgeeg.com` / `dev.tadgeeg.com` DNS doesn't point at this server yet,
running `enable_https.sh` fails on those domains. Issue only the env you need:

```bash
# Replace 'test' with 'live' or 'dev' as needed
cd /root/finai-deploy
docker compose -f deployment/docker/docker-compose.yml run --rm certbot certonly \
  --webroot -w /var/www/certbot \
  --email admin@tadgeeg.com \
  --agree-tos --no-eff-email \
  --cert-name test.tadgeeg.com \
  -d test.tadgeeg.com

# If you also want www, add: -d www.test.tadgeeg.com (DNS for www must exist)
```

Then stub out the missing certs so nginx can still start in HTTPS mode:
```bash
cd /root/finai-deploy/deployment/docker/certbot/conf/live/
sudo ln -sfn test.tadgeeg.com tadgeeg.com
sudo ln -sfn test.tadgeeg.com dev.tadgeeg.com
cd /root/finai-deploy

bash deployment/docker/render_nginx_config.sh https
docker compose -f deployment/docker/docker-compose.yml restart nginx
```

### 5.3 Verify
```bash
curl -I https://test.tadgeeg.com/health/       # expect HTTP/2 200
curl -I http://test.tadgeeg.com/               # expect 301 → https
```

> **If `https://...` returns 301 to itself** → an infinite redirect loop.
> Cause: `ENABLE_SECURE_PROXY_SSL_HEADER=False` in `.env`. Set it to `True`
> and `restart web_test`.

### 5.4 Auto-renewal cron
```bash
# As root
( crontab -l 2>/dev/null; \
  echo "0 3 * * * cd /root/finai-deploy && bash deployment/docker/renew_certs.sh >> /var/log/finai-certbot.log 2>&1" \
) | crontab -
```

---

## 6. Data setup (post-deploy)

### 6.1 Create a Django superuser
```bash
docker compose -f deployment/docker/docker-compose.yml exec web_test \
  python manage.py createsuperuser
```

Then log in at `https://test.tadgeeg.com/admin/`.

### 6.2 Seed reference data
All seed commands are **idempotent** — re-running them won't duplicate rows.

```bash
alias dx='docker compose -f deployment/docker/docker-compose.yml exec web_test python manage.py'

dx seed_billing_plans          # Free Trial, Starter, Business, Professional
dx seed_canonical_fields       # Doc-type schemas
dx seed_document_audit_rules   # 30+ audit rules with AR/EN labels
dx seed_gaap_rule_definitions  # GAAP/IFRS rule defs (V2 pipeline)
dx seed_rule_assignments       # Rule → doc-type mappings
dx create_demo_user            # Demo org + login
```

Skip `seed_gaap_rule_definitions` and `seed_rule_assignments` if you only want
a basic smoke test of the UI.

### 6.3 Verify seeded data
```bash
dx shell -c "
from apps.billing.models import Plan
for p in Plan.objects.all().order_by('sort_order'):
    print(p.code, '|', p.name_ar, '|', p.name_en, '|', p.price)
"
```

---

## 7. Daily operations

### 7.1 Deploy new code
After you `git push` to `main`:

```bash
cd /root/finai-deploy
bash deployment/docker/deploy.sh update test    # or: update live / update dev / update all
```

This pulls `origin/main`, rebuilds the image, restarts containers. Migrations,
`compilemessages`, and `collectstatic` run automatically via the entrypoint.

**Env files survive every redeploy** — `update.sh` snapshots `*.env` to a temp
dir, runs `git reset --hard`, then restores. Secrets won't be wiped.

### 7.2 Run seed / management commands after a deploy
```bash
docker compose -f deployment/docker/docker-compose.yml exec web_test \
  python manage.py <command_name>
```

### 7.3 Logs
```bash
# Follow live
bash deployment/docker/deploy.sh logs web_test
bash deployment/docker/deploy.sh logs nginx

# Last 100 lines (one-shot)
docker compose -f deployment/docker/docker-compose.yml logs --tail=100 web_test
```

### 7.4 Status
```bash
bash deployment/docker/deploy.sh ps
docker stats --no-stream
```

### 7.5 Restart / stop
```bash
bash deployment/docker/deploy.sh restart test   # restart web+celery+db for one env
bash deployment/docker/deploy.sh stop test      # stop without removing
bash deployment/docker/deploy.sh down           # stop ALL envs and the proxy
```

### 7.6 Open a Django shell
```bash
docker compose -f deployment/docker/docker-compose.yml exec web_test \
  python manage.py shell
```

### 7.7 MySQL shell
```bash
docker compose -f deployment/docker/docker-compose.yml exec db_test \
  mysql -u finai_test_user -p finai_test
# Enter the DB_PASSWORD value from env/test.env when prompted
```

---

## 8. Backups

### 8.1 Database dump
```bash
mkdir -p /root/backups
docker compose -f deployment/docker/docker-compose.yml exec -T db_test \
  mysqldump -u root -p"$(grep MYSQL_ROOT_PASSWORD deployment/docker/env/test.env | cut -d= -f2)" \
  finai_test | gzip > /root/backups/finai_test_$(date +%F).sql.gz
```

### 8.2 Restore from dump
```bash
zcat /root/backups/finai_test_2026-05-17.sql.gz | \
  docker compose -f deployment/docker/docker-compose.yml exec -T db_test \
  mysql -u root -p"$ROOT_PWD" finai_test
```

### 8.3 What to back up regularly
- `/root/backups/*.sql.gz` — DB dumps (daily via cron recommended)
- `/root/finai-deploy/deployment/docker/env/*.env` — secrets (manual, encrypted off-server)
- `/root/finai-deploy/deployment/docker/certbot/conf/` — Let's Encrypt certs

### 8.4 Daily DB backup cron
```bash
# Edit root crontab
crontab -e

# Add (rotates last 14 days):
0 2 * * * cd /root/finai-deploy && bash deployment/docker/backup_db.sh test >> /var/log/finai-backup.log 2>&1
```
(Create `backup_db.sh` if it doesn't exist using the dump command from 8.1.)

---

## 9. Troubleshooting

### 9.1 `bind 0.0.0.0:80/tcp: address already in use`
Host nginx (or apache) still running. Fix:
```bash
sudo systemctl stop nginx
sudo apt-get remove -y nginx nginx-common nginx-core
sudo ss -tlnp | grep ':80 '   # nothing
bash deployment/docker/deploy.sh up test
```

### 9.2 Browser shows `ERR_CONNECTION_TIMED_OUT`
Cloud-firewall blocking ports. Open 80 + 443 in the VPS provider panel.
Different from `Connection refused` (that means nginx isn't running).

### 9.3 502 Bad Gateway from nginx
Web container isn't serving:
```bash
docker compose -f deployment/docker/docker-compose.yml logs --tail=80 web_test
```
Common causes:
- `Access denied for user`: `DB_PASSWORD` ≠ `MYSQL_PASSWORD`.
  Fix the env, then **wipe the DB volume** so MySQL re-initialises:
  ```bash
  docker compose -f deployment/docker/docker-compose.yml stop web_test db_test
  docker volume rm finai-multi-env_mysql_test_data
  bash deployment/docker/deploy.sh up test
  ```
- `OPENAI_API_KEY is not set`: just a warning, ignore unless you need AI.
- `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`: must be set, app refuses to start
  without them.
- App is still running migrations on first boot — wait 1–2 minutes and retry.

### 9.4 HTTPS works but page loops 301 → itself
`ENABLE_SECURE_PROXY_SSL_HEADER=False` in env. Set to `True` and:
```bash
docker compose -f deployment/docker/docker-compose.yml up -d --force-recreate web_test
```

### 9.5 `certbot` 404 on `/.well-known/acme-challenge/...`
DNS for the domain doesn't point at this server, **or** the temporary HTTP
nginx isn't serving the challenge path.

Check from your laptop:
```bash
dig +short test.tadgeeg.com
curl -I http://test.tadgeeg.com/
```

The first must equal the server's public IP; the second must reach nginx.

### 9.6 `NXDOMAIN looking up A for www.test.tadgeeg.com`
You requested a cert for `www.*` but no DNS record exists. Either:
- Add the DNS A record, or
- Reissue without `www.*`:
  ```bash
  docker compose -f deployment/docker/docker-compose.yml run --rm certbot certonly \
    --webroot -w /var/www/certbot \
    --email admin@tadgeeg.com --agree-tos --no-eff-email \
    --cert-name test.tadgeeg.com \
    -d test.tadgeeg.com
  ```
- Also update `env/test.env`:
  ```
  SERVER_NAMES=test.tadgeeg.com
  ALLOWED_HOSTS=test.tadgeeg.com
  CSRF_TRUSTED_ORIGINS=https://test.tadgeeg.com
  ```
  Then `bash deployment/docker/render_nginx_config.sh https` and restart nginx.

### 9.7 `populate() isn't reentrant` floods the web log
The app is waiting for MySQL to finish initialising. It's recoverable —
entrypoint retries until DB is ready. Wait 30–60 s. If it never recovers,
go to 9.3.

### 9.8 Old code keeps showing after `update`
Caches:
```bash
# Force a clean rebuild
docker compose -f deployment/docker/docker-compose.yml build --no-cache web_test
docker compose -f deployment/docker/docker-compose.yml up -d --force-recreate web_test
```

### 9.9 Disk filling up
```bash
docker system df
docker image prune -af
docker volume ls    # check finai-multi-env_* volumes are still in use
```
DB volumes are kept on `docker compose down` — only `docker volume rm` deletes
them. Don't run `docker volume prune` without checking.

---

## 10. Architecture reference

### 10.1 Container topology
```
Internet  →  nginx (host 80/443)
                ├── live  → web_live:8000    → db_live:3306
                ├── dev   → web_dev:8000     → db_dev:3306
                └── test  → web_test:8000    → db_test:3306
                                         ↘ redis:6379 (shared)
```

### 10.2 Key file paths

| Path | What |
| --- | --- |
| `deployment/docker/docker-compose.yml` | Service definitions for all envs |
| `deployment/docker/deploy.sh` | Front-end CLI (ps, up, restart, update, logs…) |
| `deployment/docker/update.sh` | Code-pull + rebuild + restart (called by `deploy.sh update`) |
| `deployment/docker/enable_https.sh` | Issues certs for live+dev+test then switches nginx to HTTPS |
| `deployment/docker/render_nginx_config.sh` | Renders `nginx/generated/default.conf` from a template |
| `deployment/docker/nginx/http.conf.template` | HTTP-only template |
| `deployment/docker/nginx/https.conf.template` | HTTPS template (uses cert paths) |
| `deployment/docker/env/{env}.env` | Per-environment secrets (gitignored) |
| `deployment/docker/env/{env}.env.example` | Tracked templates |
| `deployment/docker/certbot/conf/` | Issued Let's Encrypt certs (persisted) |
| `docker/entrypoint.sh` | Container entrypoint: migrate + collectstatic + gunicorn |
| `Dockerfile` | Builds the web image |

### 10.3 What `update.sh` actually does

1. **Snapshot** `deployment/docker/env/*.env` → temp dir (so secrets survive).
2. `git fetch origin main`
3. `git reset --hard origin/main`
4. **Restore** the env-file snapshot.
5. Re-render nginx config if missing.
6. `docker compose build --pull <web services>` for the target env.
7. `docker compose up -d <all services>` for the target env.
8. Tail logs of the web container for sanity.

### 10.4 What the entrypoint does on every container boot
1. Wait for the DB to accept connections.
2. `python manage.py migrate --noinput`
3. `python manage.py compilemessages`
4. `python manage.py collectstatic --noinput --clear`
5. `gunicorn finai_backend.wsgi --bind 0.0.0.0:8000 --workers $GUNICORN_WORKERS`

---

## 11. Repeatable end-to-end deploy checklist

For a brand-new test environment, this is the **complete** sequence:

```bash
# 1. DNS — add A record test.tadgeeg.com → <server IP>
# 2. Firewall — open TCP 80, 443 in VPS panel

# 3. On the server, as root:
ssh root@<server IP>

# 4. Install Docker (section 2.1)
# ...

# 5. Remove host nginx (section 2.2)
sudo systemctl stop nginx 2>/dev/null
sudo apt-get remove -y nginx nginx-common nginx-core 2>/dev/null

# 6. Clone the repo
mkdir -p /root/finai-deploy && cd /root/finai-deploy
git clone https://github.com/<owner>/tadgeeg.git .

# 7. Create env files and edit deployment/docker/env/test.env
bash deployment/docker/deploy.sh init-env
nano deployment/docker/env/test.env
# Set: DJANGO_SECRET_KEY, DB_PASSWORD, MYSQL_PASSWORD (same), MYSQL_ROOT_PASSWORD,
#      EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, ENABLE_SECURE_PROXY_SSL_HEADER=True
#      drop www.* from SERVER_NAMES if no DNS for it

# 8. Bring up the stack on HTTP
bash deployment/docker/deploy.sh up test
bash deployment/docker/deploy.sh ps
curl -I http://test.tadgeeg.com/health/      # expect 200 or 301

# 9. Issue cert and switch to HTTPS
docker compose -f deployment/docker/docker-compose.yml run --rm certbot certonly \
  --webroot -w /var/www/certbot \
  --email admin@tadgeeg.com --agree-tos --no-eff-email \
  --cert-name test.tadgeeg.com -d test.tadgeeg.com
cd deployment/docker/certbot/conf/live/
sudo ln -sfn test.tadgeeg.com tadgeeg.com
sudo ln -sfn test.tadgeeg.com dev.tadgeeg.com
cd /root/finai-deploy
bash deployment/docker/render_nginx_config.sh https
docker compose -f deployment/docker/docker-compose.yml restart nginx
curl -I https://test.tadgeeg.com/health/     # expect 200

# 10. Seed data + create users
docker compose -f deployment/docker/docker-compose.yml exec web_test python manage.py seed_billing_plans
docker compose -f deployment/docker/docker-compose.yml exec web_test python manage.py seed_canonical_fields
docker compose -f deployment/docker/docker-compose.yml exec web_test python manage.py seed_document_audit_rules
docker compose -f deployment/docker/docker-compose.yml exec web_test python manage.py createsuperuser

# 11. Smoke test in browser
# Open: https://test.tadgeeg.com/
# Open: https://test.tadgeeg.com/admin/

# 12. Schedule cert renewal
( crontab -l 2>/dev/null; \
  echo "0 3 * * * cd /root/finai-deploy && bash deployment/docker/renew_certs.sh >> /var/log/finai-certbot.log 2>&1" \
) | crontab -
```

Done.

---

## 12. Quick command reference

```bash
# From /root/finai-deploy

bash deployment/docker/deploy.sh ps                  # status
bash deployment/docker/deploy.sh up test             # start
bash deployment/docker/deploy.sh restart test        # restart
bash deployment/docker/deploy.sh stop test           # stop
bash deployment/docker/deploy.sh down                # stop ALL
bash deployment/docker/deploy.sh logs web_test       # tail logs
bash deployment/docker/deploy.sh update test         # pull + rebuild + restart
bash deployment/docker/enable_https.sh               # all envs → HTTPS
bash deployment/docker/renew_certs.sh                # renew certs

# Inside a running container
DC="docker compose -f deployment/docker/docker-compose.yml"
$DC exec web_test python manage.py migrate
$DC exec web_test python manage.py createsuperuser
$DC exec web_test python manage.py shell
$DC exec web_test python manage.py seed_billing_plans
$DC exec db_test  mysql -u root -p finai_test
```
