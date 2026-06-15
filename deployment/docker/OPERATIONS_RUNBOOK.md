# Tadgeeg — Production Operations Runbook (Docker)

Practical, copy-paste commands for operating the live tadgeeg.com stack.

> **Server:** Hostinger VPS · **Repo dir:** `~/tadgeeg` (i.e. `/root/tadgeeg`)
> **Compose file:** `deployment/docker/docker-compose.yml`
> **App path inside containers:** `/app` · **Django project:** `finai_backend`

---

## 0. Conventions

All commands are run **from the repo root** on the server:

```bash
cd ~/tadgeeg
```

This stack runs **three environments in one compose file**. Service names:

| Domain | Web service | DB service | Celery service |
|---|---|---|---|
| **tadgeeg.com** (live) | `web_live` | `db_live` | `celery_live` |
| dev.tadgeeg.com | `web_dev` | `db_dev` | `celery_dev` |
| test.tadgeeg.com | `web_test` | `db_test` | `celery_test` |
| shared | `nginx`, `redis`, `certbot` | | |

A short alias saves typing the `-f` flag every time:

```bash
alias dc='docker compose -f deployment/docker/docker-compose.yml'
# then: dc ps   /   dc logs web_live   ...
```

(The runbook spells out the full command so it works without the alias.)

---

## 1. Status / health

```bash
# All containers + status + ports
docker compose -f deployment/docker/docker-compose.yml ps

# App health endpoint (from inside nginx → web_live)
curl -sf https://tadgeeg.com/health/ && echo "  OK"

# Disk + memory (cert/log/DB growth)
df -h /
free -h
```

---

## 2. Create a Django superuser (Platform CRM owner)

The `User` model logs in with **email** (not username) and requires **full name**.

**Interactive:**
```bash
docker compose -f deployment/docker/docker-compose.yml exec web_live \
  python manage.py createsuperuser
# prompts: Email address → Full name → Password (x2)
```

**If the container isn't running**, use a one-off:
```bash
docker compose -f deployment/docker/docker-compose.yml run --rm web_live \
  python manage.py createsuperuser
```

**Non-interactive** (env vars, no password prompt):
```bash
docker compose -f deployment/docker/docker-compose.yml exec \
  -e DJANGO_SUPERUSER_EMAIL=admin@tadgeeg.com \
  -e DJANGO_SUPERUSER_PASSWORD='REPLACE_WITH_STRONG_SECRET' \
  -e DJANGO_SUPERUSER_FULL_NAME='Platform Owner' \
  web_live python manage.py createsuperuser --noinput
```

> ⚠️ A superuser is an **implicit Platform CRM owner** (full CRM + `/admin/`). Use a
> strong password and a real `@tadgeeg.com` email.

**Set up the CRM role groups** (one-time, idempotent — safe to re-run):
```bash
docker compose -f deployment/docker/docker-compose.yml exec web_live \
  python manage.py setup_platform_crm_roles
```

---

## 3. Logs

### Application (Django / gunicorn) — live
```bash
docker compose -f deployment/docker/docker-compose.yml logs --tail=200 web_live
docker compose -f deployment/docker/docker-compose.yml logs -f web_live      # follow
```

### Database (MySQL error log → container stdout)
```bash
docker compose -f deployment/docker/docker-compose.yml logs --tail=200 db_live
docker compose -f deployment/docker/docker-compose.yml logs -f db_live
```
> General/slow-query logging is **not** enabled by default. To capture queries you
> must add `--general_log=ON` / `--slow_query_log=ON` to the `db_live` `command:`
> in the compose file and restart that service.

### nginx (TLS / request errors)
```bash
docker compose -f deployment/docker/docker-compose.yml logs --tail=200 nginx
```

### Celery worker — live
```bash
docker compose -f deployment/docker/docker-compose.yml logs --tail=200 celery_live
```

### App log files inside the container (mounted `logs_live` volume)
```bash
docker compose -f deployment/docker/docker-compose.yml exec web_live \
  sh -c 'ls -la /app/logs && tail -n 100 /app/logs/*.log'
```

### Raw host log file for any container
```bash
docker inspect --format='{{.LogPath}}' finai-multi-env-web_live-1
sudo tail -n 200 "$(docker inspect --format='{{.LogPath}}' finai-multi-env-web_live-1)"
```

---

## 4. Deploy / update live code

```bash
# 1) Pull the code you want to release
cd ~/tadgeeg
git fetch origin
git checkout main          # live tracks main/master — confirm your branch
git pull --ff-only

# 2) Rebuild + restart the live web + worker (and any shared infra)
docker compose -f deployment/docker/docker-compose.yml up -d --build web_live celery_live

# 3) Apply DB migrations (live)
docker compose -f deployment/docker/docker-compose.yml exec web_live \
  python manage.py migrate --noinput

# 4) Collect static (if assets changed)
docker compose -f deployment/docker/docker-compose.yml exec web_live \
  python manage.py collectstatic --noinput

# 5) Verify
docker compose -f deployment/docker/docker-compose.yml ps
curl -sf https://tadgeeg.com/health/ && echo OK
```

> There is also a scripted path: `bash deployment/docker/update.sh` (rebuilds,
> brings services up, shows status). Prefer it if you know it matches your setup.

---

## 5. Migrations (safe checks)

```bash
# Show migration state for live
docker compose -f deployment/docker/docker-compose.yml exec web_live \
  python manage.py showmigrations | tail -40

# Dry-run check — should say "No changes detected" if models match migrations
docker compose -f deployment/docker/docker-compose.yml exec web_live \
  python manage.py makemigrations --check --dry-run

# Apply
docker compose -f deployment/docker/docker-compose.yml exec web_live \
  python manage.py migrate --noinput

# Django system check
docker compose -f deployment/docker/docker-compose.yml exec web_live \
  python manage.py check
```

---

## 6. SSL / HTTPS certificates (Let's Encrypt)

Certs auto-expire after **90 days**. Renewal is **not automatic** unless the cron
in step 6.4 is installed.

### 6.1 Check expiry of the live cert
```bash
echo | openssl s_client -servername tadgeeg.com -connect tadgeeg.com:443 2>/dev/null \
  | openssl x509 -noout -dates -subject -issuer
```

### 6.2 Renew + reload nginx
```bash
bash deployment/docker/renew_certs.sh
```
> ⚠️ Known gotcha: that script uses `set -e`, so if **any** domain fails to renew
> (e.g. `test.tadgeeg.com` when `www.test` has no DNS record) the script aborts
> **before** reloading nginx. If that happens, reload manually:
> ```bash
> docker compose -f deployment/docker/docker-compose.yml exec nginx nginx -s reload
> ```

### 6.3 Force-reload nginx to pick up a renewed cert
```bash
docker compose -f deployment/docker/docker-compose.yml exec nginx nginx -s reload
```

### 6.4 Install auto-renewal cron (do this once)
```bash
( crontab -l 2>/dev/null; \
  echo "0 3 * * * cd ~/tadgeeg && bash deployment/docker/renew_certs.sh >> /var/log/finai-certbot.log 2>&1" \
) | crontab -
crontab -l   # verify
```

### 6.5 ACME challenge sanity check (must reach nginx over plain HTTP)
```bash
curl -I http://tadgeeg.com/.well-known/acme-challenge/test   # 404 = OK (path works, no such file)
```

---

## 7. Restart / stop / start services

```bash
# Restart just live web
docker compose -f deployment/docker/docker-compose.yml restart web_live

# Restart nginx (after cert/config changes)
docker compose -f deployment/docker/docker-compose.yml restart nginx

# Bring a stopped service up
docker compose -f deployment/docker/docker-compose.yml up -d web_live

# Stop a service (does NOT delete data)
docker compose -f deployment/docker/docker-compose.yml stop web_live
```

> ⚠️ Avoid `docker compose down -v` — the `-v` flag **deletes volumes**, including
> `mysql_live_data` (your live database). Never use `-v` on production.

---

## 8. Database access & backup

### 8.1 Open a MySQL shell (live)
```bash
docker compose -f deployment/docker/docker-compose.yml exec db_live \
  sh -c 'mysql -u root -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE"'
```

### 8.2 Manual backup (dump) — do this BEFORE risky migrations
```bash
mkdir -p ~/backups
docker compose -f deployment/docker/docker-compose.yml exec db_live \
  sh -c 'mysqldump -u root -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE"' \
  | gzip > ~/backups/tadgeeg-live-$(date +%F-%H%M).sql.gz
ls -lh ~/backups
```

### 8.3 Restore a dump (DANGER — overwrites live data)
```bash
gunzip -c ~/backups/<file>.sql.gz | \
docker compose -f deployment/docker/docker-compose.yml exec -T db_live \
  sh -c 'mysql -u root -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE"'
```

---

## 9. Django shell / one-off commands (live)

```bash
docker compose -f deployment/docker/docker-compose.yml exec web_live \
  python manage.py shell

# Any management command, e.g. expire old subscriptions:
docker compose -f deployment/docker/docker-compose.yml exec web_live \
  python manage.py expire_subscriptions
```

---

## 10. Quick incident triage

| Symptom | First command | Likely fix |
|---|---|---|
| Browser "Not secure" / `ERR_CERT_DATE_INVALID` | §6.1 check expiry | §6.2 renew, then §6.3 reload nginx |
| Site 502 / 503 | `... ps` then `... logs --tail=100 web_live` | `... restart web_live` |
| 500 errors | `... logs --tail=200 web_live` | read traceback; fix + redeploy §4 |
| Can't connect at all | `... ps` (nginx Up? ports 80/443?) | `... up -d nginx` |
| DB connection errors in app | `... logs --tail=100 db_live` | ensure `db_live` healthy; restart |
| Migrations needed after deploy | §5 showmigrations | §5 migrate |

---

## 11. Golden rules

- Always run from `~/tadgeeg` with `-f deployment/docker/docker-compose.yml`.
- **Never** use `down -v` on production (deletes the database).
- **Back up the DB (§8.2) before** migrations or restores.
- Target the **`*_live`** services for tadgeeg.com — don't touch `*_dev` / `*_test`.
- After renewing certs, **always confirm nginx reloaded** (§6.3).
- Keep secrets out of shell history (use env files / a secrets manager for passwords).
