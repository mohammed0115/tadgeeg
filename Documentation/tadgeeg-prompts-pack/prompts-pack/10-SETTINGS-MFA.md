# ⚙️ 10 — الإعدادات والمصادقة الثنائية (Settings & MFA)

> Prompts لتطوير `templates/settings/*` و `apps/organization_settings/`

---

## 🎯 Prompt 10.1 — صفحة الإعدادات الرئيسية

```
في مشروع Tadgeeg AI، ملف `templates/settings/index.html`:

المطلوب: صفحة إعدادات شاملة بهوية تدقيق.

# الهيكل: Sidebar Tabs على اليسار + Content على اليمين

## Tabs:
1. الملف الشخصي (Profile)
2. المنظمة (Organization)
3. الفريق (Team)
4. الأمان والمصادقة (Security & MFA)
5. الإشعارات (Notifications)
6. التكاملات (Integrations)
7. الفوترة والاشتراك (Billing)
8. التخصيص (Customization)
9. API & Webhooks
10. اللغة والمنطقة (Language & Region)

## Tab 1: الملف الشخصي
- صورة (avatar) + زر تغيير
- الاسم الكامل
- البريد الإلكتروني (read-only)
- رقم الهاتف
- الوظيفة
- الجنسية
- اللغة المفضلة
- زر "حفظ التغييرات"

## Tab 2: المنظمة
- شعار المنظمة + زر رفع
- اسم المنظمة (عربي + English)
- VAT Number
- العنوان
- الدولة + المدينة
- الموقع الإلكتروني
- البريد الرسمي
- رقم الهاتف
- نوع الشركة (LLC, Sole Proprietorship, ...)
- حجم الشركة

## Tab 3: الفريق
- جدول الأعضاء
- زر "+ دعوة عضو"
- الاسم، البريد، الدور، الحالة، Actions
- الأدوار: Admin, Auditor, Reviewer, Viewer
- صلاحيات قابلة للتخصيص لكل دور

## Tab 4: الأمان والمصادقة
- تغيير كلمة المرور
- MFA toggle + setup
- Recovery Codes
- Active Sessions (مع زر تسجيل خروج من جميع الأجهزة)
- Login History (آخر 10 محاولات)
- IP Whitelist (للـ Enterprise)

## Tab 5: الإشعارات
- Email notifications (toggles):
  • تنبيهات الفواتير
  • تقارير دورية
  • تحديثات النظام
  • تنبيهات الأمان
- In-app notifications
- SMS notifications (اختياري)
- Notification frequency

## Tab 6: التكاملات
بطاقات للتكاملات المتاحة:
- ZATCA (مفعّل)
- ERP Systems (SAP, Oracle, ...)
- Accounting Software
- Slack
- Microsoft Teams
- Email (SMTP)
- Webhooks

## Tab 7: الفوترة
- الخطة الحالية + تفاصيل
- استخدام الفترة (X/Y)
- الترقية للخطة الأعلى
- سجل الفواتير
- طريقة الدفع
- الفواتير الضريبية

## Tab 8: التخصيص
- ألوان أساسية (للـ white-label)
- شعار مخصص في التقارير
- Email templates
- Subdomain custom

## Tab 9: API & Webhooks
- API Keys (إنشاء، حذف، rotate)
- Webhooks (URL + events)
- Rate Limits
- Documentation links

## Tab 10: اللغة والمنطقة
- اللغة الافتراضية
- المنطقة الزمنية
- العملة الافتراضية
- صيغة التاريخ
- صيغة الأرقام (decimal separator)

# Backend في `apps/organization_settings/views.py`:
```python
class SettingsView(LoginRequiredMixin, TemplateView):
    template_name = 'settings/index.html'
    
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        org = self.request.user.organization
        ctx.update({
            'organization': org,
            'team_members': User.objects.filter(organization=org),
            'active_sessions': self.get_active_sessions(),
            'login_history': self.get_login_history()[:10],
            'integrations': self.get_integrations(org),
            'subscription': org.subscription if hasattr(org, 'subscription') else None,
            'api_keys': APIKey.objects.filter(organization=org),
            'webhooks': Webhook.objects.filter(organization=org),
        })
        return ctx
```

أعطني:
1. الـ template الكامل (settings/index.html)
2. الـ partials لكل tab
3. الـ Views لكل tab (Update profile, organization, etc.)
4. الـ Forms (Django Forms)
```

---

## 🎯 Prompt 10.2 — MFA Settings المتقدمة

```
في مشروع Tadgeeg AI، ملف `templates/settings/mfa_settings.html`:

# المطلوب:
صفحة كاملة لإدارة MFA:

## الحالة الحالية:
- Badge: "MFA مفعّل" (أخضر) أو "MFA معطّل" (أحمر)
- نوع MFA المفعّل (Authenticator/Email/SMS)
- آخر تعديل

## إذا MFA معطّل:
- زر كبير "تفعيل المصادقة الثنائية" (#10B981)
- شرح فوائد MFA
- توصية بشدة

## إذا MFA مفعّل:
- المعلومات الحالية
- زر "تغيير الطريقة"
- زر "تعطيل MFA" (يتطلب كلمة المرور)
- Recovery Codes:
  • "تبقى لديك 8 من 10 أكواد"
  • زر "إعادة توليد"
  • زر "عرض الأكواد"

## Backup Methods:
يمكن إضافة أكثر من طريقة:
- Authenticator App (الأساسي)
- Backup: Email
- Backup: SMS
- Backup: Recovery Codes

## Trusted Devices:
- قائمة الأجهزة الموثوقة
- "تخطّى MFA على هذا الجهاز لمدة 30 يوم"
- زر "إزالة" لكل جهاز

## Login History:
- جدول آخر 10 محاولات دخول
- التاريخ، IP، الموقع، الجهاز، الحالة (نجح/فشل)
- إذا تم تخطّي MFA: badge

## Models المطلوبة:
```python
# apps/authentication/models.py
class MFADevice(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='mfa_devices')
    name = models.CharField(max_length=100)  # "iPhone Personal"
    type = models.CharField(max_length=20)  # totp/email/sms/recovery
    secret = models.CharField(max_length=200, blank=True)  # encrypted
    is_primary = models.BooleanField(default=False)
    is_confirmed = models.BooleanField(default=False)
    last_used = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

class RecoveryCode(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    code_hash = models.CharField(max_length=128)  # bcrypt hash
    used_at = models.DateTimeField(null=True)

class TrustedDevice(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    device_id = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=200)
    user_agent = models.TextField()
    ip_address = models.GenericIPAddressField()
    last_used = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField()

class LoginAttempt(models.Model):
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    email = models.EmailField()
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField()
    success = models.BooleanField()
    mfa_used = models.BooleanField(default=False)
    mfa_type = models.CharField(max_length=20, blank=True)
    failure_reason = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
```

## Backend:
```python
class MFADeviceListView(LoginRequiredMixin, ListView):
    model = MFADevice
    template_name = 'settings/mfa_settings.html'
    context_object_name = 'devices'
    
    def get_queryset(self):
        return MFADevice.objects.filter(user=self.request.user)

class MFADeviceDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        # Require password confirmation
        if not request.user.check_password(request.POST.get('password', '')):
            return JsonResponse({'error': 'Invalid password'}, status=403)
        
        device = get_object_or_404(MFADevice, pk=pk, user=request.user)
        device.delete()
        
        # Log activity
        log_activity(request.user, 'mfa_device_removed', {'name': device.name})
        
        # Send security email
        send_security_email(request.user, 'mfa_device_removed', device)
        
        return JsonResponse({'success': True})
```

أعطني:
1. الـ template الكامل
2. الـ Models + Migrations
3. الـ Views (List, Add, Confirm, Delete, Regenerate Recovery)
4. Service لإرسال security emails عند تغيير MFA
5. Tests شاملة
6. انظر `Documentation/MFA_TOTP_IMPLEMENTATION_GUIDE.md` للمرجع
```

---

## 🎯 Prompt 10.3 — API Keys & Webhooks Management

```
في `templates/settings/api_keys.html` (جديد):

# المطلوب:
صفحة لإدارة API Keys و Webhooks:

## API Keys Section:
- جدول الـ keys:
  • الاسم
  • الـ key (مخفي: tg_xxxx...xxx)
  • الصلاحيات (read, write, admin)
  • آخر استخدام
  • تاريخ الإنشاء + الانتهاء
  • Actions: Copy, Rotate, Delete
- زر "+ إنشاء API Key جديد"

عند إنشاء key جديد:
- اسم وصفي
- الصلاحيات (checkboxes)
- مدة الصلاحية (30/60/90 days, never)
- IP whitelist (optional)
- بعد الإنشاء: عرض الـ key مرة واحدة فقط مع تحذير

## Webhooks Section:
- جدول الـ webhooks:
  • الاسم
  • URL
  • الأحداث (events)
  • الحالة (active/disabled)
  • معدل النجاح
  • Actions
- زر "+ إنشاء Webhook"

الأحداث المتاحة:
- invoice.created
- invoice.processed
- invoice.high_risk_detected
- invoice.approved
- invoice.rejected
- batch.completed
- compliance.violation
- user.login
- mfa.enabled

## Webhook Test:
زر "اختبار" لكل webhook:
- يرسل sample payload
- يعرض الـ response
- نجح/فشل + الوقت

## Webhook Logs:
- آخر 100 طلب
- التاريخ، الحدث، الـ status code، الوقت
- زر "إعادة المحاولة" للفاشلة

# Models:
```python
class APIKey(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    name = models.CharField(max_length=100)
    key_prefix = models.CharField(max_length=10)  # "tg_live_"
    key_hash = models.CharField(max_length=128)  # bcrypt
    last_4 = models.CharField(max_length=4)
    permissions = models.JSONField(default=list)  # ['read', 'write']
    ip_whitelist = models.JSONField(default=list)
    last_used_at = models.DateTimeField(null=True)
    expires_at = models.DateTimeField(null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    @classmethod
    def generate(cls, organization, user, name, **kwargs):
        import secrets, bcrypt
        raw_key = f"tg_live_{secrets.token_urlsafe(32)}"
        return cls.objects.create(
            organization=organization,
            created_by=user,
            name=name,
            key_prefix=raw_key[:8],
            key_hash=bcrypt.hashpw(raw_key.encode(), bcrypt.gensalt()).decode(),
            last_4=raw_key[-4:],
            **kwargs
        ), raw_key  # raw_key returned ONCE

class Webhook(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    url = models.URLField()
    events = models.JSONField(default=list)  # ['invoice.created', ...]
    secret = models.CharField(max_length=64)  # for HMAC signing
    is_active = models.BooleanField(default=True)
    success_rate = models.FloatField(default=100.0)
    
class WebhookDelivery(models.Model):
    webhook = models.ForeignKey(Webhook, on_delete=models.CASCADE)
    event = models.CharField(max_length=50)
    payload = models.JSONField()
    response_status = models.IntegerField(null=True)
    response_body = models.TextField(blank=True)
    duration_ms = models.IntegerField(null=True)
    success = models.BooleanField()
    created_at = models.DateTimeField(auto_now_add=True)
```

# Webhook Sender (Celery Task):
```python
@shared_task(bind=True, max_retries=5)
def send_webhook(self, webhook_id, event, payload):
    webhook = Webhook.objects.get(id=webhook_id)
    if not webhook.is_active or event not in webhook.events:
        return
    
    import hmac, hashlib, json, time
    
    body = json.dumps(payload)
    signature = hmac.new(
        webhook.secret.encode(),
        body.encode(),
        hashlib.sha256
    ).hexdigest()
    
    headers = {
        'Content-Type': 'application/json',
        'X-Tadgeeg-Signature': signature,
        'X-Tadgeeg-Event': event,
        'X-Tadgeeg-Timestamp': str(int(time.time())),
    }
    
    start = time.time()
    delivery = WebhookDelivery.objects.create(
        webhook=webhook,
        event=event,
        payload=payload,
        success=False,
    )
    
    try:
        response = requests.post(webhook.url, data=body, headers=headers, timeout=10)
        delivery.response_status = response.status_code
        delivery.response_body = response.text[:1000]
        delivery.duration_ms = int((time.time() - start) * 1000)
        delivery.success = 200 <= response.status_code < 300
        delivery.save()
        
        if not delivery.success:
            raise self.retry(countdown=2 ** self.request.retries * 60)
    except Exception as e:
        delivery.response_body = str(e)[:1000]
        delivery.save()
        raise self.retry(exc=e, countdown=60)
```

أعطني template + models + views + Celery task + tests.
```

---

## ✅ Checklist

- [ ] صفحة Settings مع 10 tabs
- [ ] MFA Settings مع Recovery Codes
- [ ] Trusted Devices management
- [ ] Login History tracking
- [ ] API Keys management
- [ ] Webhooks مع HMAC signing
- [ ] Webhook test + logs
- [ ] Notifications preferences
- [ ] Tests في `test_auth_and_permissions.py` تنجح

---

**📌 انتقل لـ `11-API-DEVELOPMENT.md`**
