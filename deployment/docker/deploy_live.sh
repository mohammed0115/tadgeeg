#!/usr/bin/env bash
# ============================================================
# نشر tadgeeg.com — إجراء واحد، يتوقّف عند أول شيء لا يطابق المتوقّع.
#
#   bash deployment/docker/deploy_live.sh            # فحص فقط، لا يغيّر شيئًا
#   bash deployment/docker/deploy_live.sh --apply    # ينشر
#
# البنية التي تجعل الفشل غير قادر على إنتاج حلقة إقلاع:
#   بناء الصورة  →  لا يمسّ الحاوية العاملة
#   الهجرة في حاوية --rm  →  الفشل رسالة خطأ، والموقع يخدم
#   up -d  →  نقطة اللاعودة، لا تُبلَغ إلا والمخرَج نظيف
#
# الخلفية والتفصيل: docs/DEPLOY_2026-08-18_MIGRATION_BATCH.md
# ============================================================
set -Eeuo pipefail

LIVE_IP="72.62.239.220"
APPLY=0
[ "${1:-}" = "--apply" ] && APPLY=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
C="docker compose -f $SCRIPT_DIR/docker-compose.yml"

say()  { printf '\n\033[1;34m▸ %s\033[0m\n' "$1"; }
ok()   { printf '\033[1;32m  ✓ %s\033[0m\n' "$1"; }
warn() { printf '\033[1;33m  ! %s\033[0m\n' "$1"; }
die()  { printf '\033[1;31m  ✗ %s\033[0m\n' "$1" >&2; exit 1; }

sql() { $C exec -T db_live sh -c "exec mysql -N -B -uroot -p\"\$MYSQL_ROOT_PASSWORD\" \"\$MYSQL_DATABASE\" -e \"$1\""; }

# ── 0. البوابة: الخادم الصحيح ───────────────────────────────────────────────
# ليست echo. الخوادم الثلاثة تحمل نفس docker-compose.yml وفيه web_live على
# كلٍّ منها، فأمر نشر إنتاج على خادم التدريب لا يفشل ولا يحذّر — يجد منظومة
# اسمها "live" ويعمل عليها. حدث ذلك في 2026-08-18.
say "0/7  الخادم"
IP="$(hostname -I | awk '{print $1}')"
[ "$IP" = "$LIVE_IP" ] || die "الخادم الخطأ: $IP — المتوقّع $LIVE_IP"
ok "$(hostname) · $IP"
cd "$PROJECT_ROOT"

# ── 1. مفاتيح البيئة ────────────────────────────────────────────────────────
# DEBUG=False مع EMAIL_HOST_USER فارغ ⇒ ImproperlyConfigured عند الإقلاع،
# بعد أن تكون الخدمة قد توقّفت. أسقط خادم التدريب في 2026-08-18.
say "1/7  مفاتيح البيئة"
ENV_FILE="$SCRIPT_DIR/env/live.env"
[ -f "$ENV_FILE" ] || die "$ENV_FILE غير موجود"
for key in EMAIL_HOST_USER EMAIL_HOST_PASSWORD SECRET_KEY; do
  value="$(grep -E "^${key}=" "$ENV_FILE" | head -1 | cut -d= -f2-)"
  [ -n "$value" ] || die "$key فارغ في live.env — الإقلاع سيفشل بعد توقّف الخدمة"
  ok "$key مضبوط"          # القيمة لا تُطبع
done

# ── 2. الفحص الوقائي — قراءة فقط ────────────────────────────────────────────
say "2/7  الفحص الوقائي"
$C ps db_live --status running | grep -q db_live || die "db_live لا يعمل — لا يمكن الفحص"

DUPS="$(sql 'SELECT COUNT(*) FROM (SELECT 1 FROM storage_management_filestoragemapping GROUP BY file_id, version_number HAVING COUNT(*)>1) d;')"
[ "$DUPS" = "0" ] || die "قيد التخزين الفريد: $DUPS مجموعة مكرّرة — الهجرة ستفشل"
ok "القيد الفريد: صفر تكرار"

# الهجرة نصف‑المطبَّقة: عمود موجود وهجرته غير مسجَّلة. MySQL يُثبّت DDL فورًا،
# فكل محاولة فاشلة تترك عمودًا يُفشل التالية. شلّت بيئتين في 2026-08-17.
HALF="$(sql 'SELECT (SELECT COUNT(*) FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name="documents_documentcanonicaldata" AND column_name="organization_id") - (SELECT COUNT(*) FROM django_migrations WHERE app="documents" AND name="0013_canonical_data_organization");')"
[ "$HALF" = "0" ] || die "هجرة نصف‑مطبَّقة (فرق=$HALF) — احذف العمود قبل المتابعة، §٦ من الدليل"
ok "لا هجرة نصف‑مطبَّقة"

FORKED="$(sql 'SELECT COUNT(*) FROM (SELECT 1 FROM invoice_audit_events WHERE chain_position IS NOT NULL GROUP BY chain_partition, chain_position HAVING COUNT(*)>1) d;')"
EVENTS_BEFORE="$(sql 'SELECT COUNT(*) FROM invoice_audit_events;')"
ok "سلسلة التدقيق: $FORKED شقًّا · $EVENTS_BEFORE حدثًا"   # الشقوق متوقّعة، 0016 يعالجها

# اتّساق تاريخ الهجرات — الفحص الذي يرفض migrate كليًّا إن فشل
$C run --rm --entrypoint sh web_live -c 'python manage.py migrate --check' >/dev/null 2>&1 \
  && ok "لا هجرات معلّقة (لا شيء لينشر؟ تحقّق من الكود)" \
  || ok "هجرات معلّقة — متوقّع"

if [ "$APPLY" -eq 0 ]; then
  say "فحص فقط. لإجراء النشر: bash $0 --apply"
  exit 0
fi

# ── 3. النسخة الاحتياطية ────────────────────────────────────────────────────
say "3/7  النسخة الاحتياطية"
bash "$SCRIPT_DIR/backup.sh" live
LATEST="$(ls -1dt "$SCRIPT_DIR"/backups/live-* 2>/dev/null | head -1)"
[ -n "$LATEST" ] && [ -s "$LATEST/db.sql.gz" ] || die "النسخة لم تُكتب"
ok "$LATEST ($(du -h "$LATEST/db.sql.gz" | cut -f1))"
warn "انسخها خارج الخادم — نسخة على نفس القرص ليست نسخة"

# ── 4. الكود والصورة — لا تمسّ الحاوية العاملة ──────────────────────────────
say "4/7  الكود والصورة"
git fetch origin
git reset --hard origin/main
git log -1 --format='  HEAD: %h %s'
$C build web_live
ok "الصورة جاهزة · الموقع ما زال يخدم"

# ── 5. الهجرة في حاوية تُرمى — نقطة الفشل الآمنة ────────────────────────────
say "5/7  الهجرة"
warn "من هنا يبدأ التوقّف المعلن (~3 دقائق مقيسة في 2026-08-18)"
$C stop web_live celery_live
LOG=/tmp/live-migrate-$(date +%Y%m%d-%H%M%S).log
if ! $C run --rm --entrypoint sh web_live -c \
      'python manage.py migrate --noinput --fake-initial 2>&1' | tee "$LOG"; then
  warn "الهجرة فشلت — السجلّ: $LOG"
  warn "أعِد الخدمة على النسخة القديمة قبل التشخيص:"
  warn "  git reset --hard <commit القديم> && $C build web_live && $C up -d web_live celery_live"
  die "لم يُعَد تشغيل شيء — القرار لك بعد قراءة السجلّ"
fi
grep -q "Traceback" "$LOG" && die "الهجرة طبعت Traceback رغم نجاح الخروج — $LOG"
ok "الهجرة تمّت · $LOG"

# ── 6. نقطة اللاعودة ────────────────────────────────────────────────────────
say "6/7  إعادة التشغيل"
$C up -d --no-deps web_live celery_live
ok "الحاويتان أُقلعتا"

# ── 7. التحقّق ──────────────────────────────────────────────────────────────
# الإقلاع أطول من الهجرة: 419 ملفًّا ثابتًا ثم بذر الخطط والإضافات والشركاء.
# قياس 2026-08-18: الهجرة 46 ثانية، الإقلاع ~دقيقتان. sleep 25 كان يقول "فشل"
# على نظام سليم.
say "7/7  التحقّق"
for i in $(seq 1 24); do
  CODE="$(curl -sS -o /dev/null -m 10 -w '%{http_code}' https://tadgeeg.com/ 2>/dev/null || echo 000)"
  printf '  %s  HTTP %s\n' "$(date +%H:%M:%S)" "$CODE"
  case "$CODE" in 200|301|302) break ;; esac
  sleep 15
done
case "$CODE" in
  200|301|302) ok "tadgeeg.com يخدم — HTTP $CODE" ;;
  *) warn "$($C logs --tail=40 web_live)"; die "الموقع لا يخدم بعد ست دقائق — HTTP $CODE" ;;
esac

$C run --rm --entrypoint sh web_live -c 'python manage.py migrate --check' >/dev/null 2>&1 \
  && ok "صفر هجرة معلّقة" || die "بقيت هجرات معلّقة بعد النشر"

FORKED_AFTER="$(sql 'SELECT COUNT(*) FROM (SELECT 1 FROM invoice_audit_events WHERE chain_position IS NOT NULL GROUP BY chain_partition, chain_position HAVING COUNT(*)>1) d;')"
EVENTS_AFTER="$(sql 'SELECT COUNT(*) FROM invoice_audit_events;')"
[ "$FORKED_AFTER" = "0" ] || die "بقي $FORKED_AFTER شقًّا في سلسلة التدقيق"
[ "$EVENTS_AFTER" -ge "$EVENTS_BEFORE" ] || die "نقص أحداث التدقيق: $EVENTS_BEFORE ← $EVENTS_AFTER"
ok "السلسلة: صفر شقّ · $EVENTS_AFTER حدثًا (كانت $EVENTS_BEFORE)"

$C ps web_live celery_live

cat <<'DONE'

  ✅ النشر تمّ.

  ويبقى اختبار وظيفي لا يقوم به سكربت — ارفع فاتورة واحدة وتحقّق:
    · فاتورة واحدة لا اثنتان
    · المجموع يظهر
    · مجموع البنود = الإجمالي

  وما لا يصير جاهزًا بهذا النشر ويحتاج مزوّدًا أو اعتمادًا:
    S3/MinIO · Odoo · WhatsApp · البريد الحيّ · حصص API
DONE
