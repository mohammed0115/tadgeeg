# 🔐 03 — صفحات المصادقة (Authentication)

> Prompts لتطوير `templates/auth/*` (تسجيل الدخول، التسجيل، MFA، إعادة تعيين كلمة المرور)

---

## 🎯 Prompt 3.1 — تحديث صفحة تسجيل الدخول

```
في مشروع Tadgeeg AI، ملف `templates/auth/login.html`:

المطلوب: حدّث الصفحة بالكامل لتطابق هوية تدقيق:

# التصميم Split Layout:
- شاشتين متساويتين: 50/50
- الجانب الأيمن (في RTL): الفورم
- الجانب الأيسر (في RTL): لوحة برند داكنة

# الجانب الأيمن (الفورم):
## Header:
- زر "← العودة للرئيسية" أعلى يمين
- اللوقو (دائرة زرقاء + علامة صح خضراء)
- اسم المنصة "تدقيق - Tadgeeg" بخط Cairo

## محتوى الفورم:
- العنوان: "تسجيل الدخول" - Cairo 32px black
- وصف: "مرحباً بك مجدداً! يرجى إدخال بياناتك..."
- حقل البريد الإلكتروني:
  - أيقونة Mail يمين
  - placeholder: name@company.sa
  - validation: required, email
- حقل كلمة المرور:
  - أيقونة Lock يمين
  - زر إظهار/إخفاء (Eye/EyeOff) يسار
  - مع رابط "نسيت كلمة المرور؟" بجانب الـ label
- Checkbox: "تذكرني على هذا الجهاز"
- زر "دخول النظام" (full width, #003366)
- "ليس لديك حساب؟ ابدأ تجربتك المجانية"
- في الأسفل: "🛡️ جميع البيانات مشفرة وفق معايير AES-256 و SOC 2"

# الجانب الأيسر (Branded Panel):
- خلفية: gradient #003366 → #002244
- Pattern: grid dots subtle
- Orbs: 2 blurred circles (واحد أخضر، واحد أزرق فاتح)
- محتوى مركزي:
  - عنوان كبير: "تدقيق مالي مدعوم بالذكاء الاصطناعي لتنطلق أعمالك"
  - "بالذكاء الاصطناعي" بلون #34d399 (أخضر فاتح)
  - شبكة 4 بطاقات إحصائيات:
    • 95% نسبة أتمتة
    • 98% دقة استخراج
    • +2.5M فاتورة معالجة
    • +1.2K منظمة موثوقة
  - بطاقة "انضم لـ 1,200+ منظمة" مع avatars متراكبة

# Animations:
- Form: fadeIn + slideUp 0.5s
- Brand Panel: fadeIn 0.7s
- Orbs: float continuously
- زر الدخول: shimmer effect
- على submit: spinner + "جاري الدخول..." لمدة 1s ثم redirect

# الشروط التقنية:
1. احتفظ بـ `{% load static i18n %}` و `{% csrf_token %}`
2. استخدم Tailwind + Alpine.js
3. الفورم يرسل POST لـ `{% url 'login' %}`
4. أضف validation للحقول قبل الـ submit
5. RTL support
6. Responsive (في الجوال: عمود واحد، اخفِ الـ branded panel)
7. Dark mode support
8. أضف زر تبديل اللغة (عربي ↔ English) أعلى يسار

# Error Handling:
- اعرض رسائل الخطأ من Django messages framework
- استخدم لون أحمر #ef4444 مع أيقونة AlertCircle
- إذا الحقل فيه خطأ: border أحمر + رسالة تحت الحقل

# الكود الحالي:
[ضع محتوى login.html هنا]

أعطني الملف الكامل المعدّل.
```

---

## 🎯 Prompt 3.2 — صفحة التسجيل (Sign Up)

```
في مشروع Tadgeeg AI، أحتاج إضافة صفحة تسجيل جديدة.

المطلوب:

# 1. أنشئ ملف: `templates/auth/register.html`
بنفس تصميم login.html (split layout)، لكن مع فورم أكبر:

## الحقول:
1. الاسم الكامل (Full Name)
2. اسم الشركة (Company Name)
3. البريد الإلكتروني (Email)
4. رقم الهاتف (Phone) - مع +966
5. كلمة المرور (Password) - مع password strength meter
6. تأكيد كلمة المرور (Confirm Password)
7. الدور (Role) - dropdown: مدير مالي، محاسب، مدقق، آخر
8. حجم الشركة (Company Size) - dropdown: 1-10, 11-50, 51-200, 200+
9. Checkbox: "أوافق على الشروط والأحكام وسياسة الخصوصية"
10. Checkbox: "اشترك في النشرة البريدية"

## Password Strength Meter:
- شريط ملون يقيس قوة الكلمة
- يحقق:
  • 8 أحرف على الأقل
  • حرف كبير وصغير
  • رقم
  • رمز خاص
- يعرض: ضعيفة (أحمر) | متوسطة (برتقالي) | جيدة (أخضر) | قوية (أخضر داكن)

## Real-time Validation:
- email: تنسيق صحيح
- phone: يبدأ بـ +966 + 9 أرقام
- passwords match

## بعد الإرسال:
- Loading state
- إذا نجح: redirect لصفحة OTP verification
- إذا فشل: عرض الأخطاء بشكل واضح

# 2. أنشئ View في `apps/authentication/views.py`:
```python
class RegisterView(View):
    template_name = 'auth/register.html'
    
    def get(self, request):
        # إذا مسجل دخول، اذهب للـ dashboard
        if request.user.is_authenticated:
            return redirect('dashboard')
        return render(request, self.template_name)
    
    def post(self, request):
        # validation + create User + Organization
        # send OTP email
        # redirect to /otp-verify/
        pass
```

# 3. أضف URL في `apps/authentication/urls.py`:
path('register/', RegisterView.as_view(), name='register')

# 4. الـ Brand Panel على اليسار:
عرض benefits بدلاً من stats:
- ✓ 14 يوم تجربة مجانية
- ✓ بدون بطاقة ائتمان
- ✓ إعداد في 5 دقائق
- ✓ دعم فني 24/7
- "محل ثقة 1,200+ شركة"

# 5. الترجمة:
- كل النصوص تستخدم {% trans %}
- أضف للملفات locale/ar و locale/en

# 6. الأمان:
- استخدم Django form validation
- CSRF protection
- Rate limiting (5 محاولات في الدقيقة)
- لا تكشف وجود الإيميل في الأخطاء

أعطني:
1. الملف الكامل register.html
2. التحديث على views.py و urls.py
3. الـ form class إذا استخدمت Django Forms
```

---

## 🎯 Prompt 3.3 — صفحة OTP Verification

```
في مشروع Tadgeeg AI، الملف `templates/auth/otp_verify.html`:

المطلوب: حدّث الصفحة لتصميم احترافي بهوية تدقيق.

# التصميم:
صفحة مركزية (مش split) - للتركيز على الكود:

# الهيكل:
## Container متمركز (max-width: 480px):
- اللوقو في الأعلى
- بطاقة بيضاء + shadow + border-radius 24px

## محتوى البطاقة:
- أيقونة دائرية كبيرة (Shield أو Mail)
- خلفية الأيقونة: linear-gradient #003366 → #10B981
- العنوان: "أدخل رمز التحقق"
- الوصف: "أرسلنا رمز مكون من 6 أرقام إلى:"
- البريد الإلكتروني (مخفي جزئياً): u***@e***.com
- 6 صناديق إدخال للرمز:
  - عرض 56px، ارتفاع 64px
  - حدود 2px، border-radius 12px
  - خط Cairo 28px font-weight 800
  - تركيز تلقائي على الصندوق الأول
  - الانتقال التلقائي للصندوق التالي عند الكتابة
  - دعم paste (لصق الكود كاملاً)
  - دعم backspace (الرجوع للصندوق السابق)
  - استخدم Alpine.js لإدارة الحالة
- Timer: "الكود ينتهي خلال 02:30"
  - يبدأ من 5 دقائق ويعد تنازلياً
  - يصبح أحمر في آخر دقيقة
- زر "تحقق" (full width, #10B981)
  - معطّل حتى تكتمل الـ 6 أرقام
- "لم يصلك الكود؟ إعادة إرسال"
  - معطّل لأول 30 ثانية
  - timer: "إعادة الإرسال خلال 30 ثانية"

## في الأسفل:
- "تواجه مشكلة؟ اتصل بالدعم"
- "⏎ العودة لتسجيل الدخول"

# Logic مع Alpine.js:
```javascript
x-data="{
  digits: ['', '', '', '', '', ''],
  timer: 300, // 5 minutes
  resendTimer: 30,
  
  handleInput(index, event) {
    const value = event.target.value;
    if (!/^\d$/.test(value)) {
      this.digits[index] = '';
      return;
    }
    this.digits[index] = value;
    if (index < 5) {
      this.$refs['digit' + (index + 1)].focus();
    }
  },
  
  handlePaste(event) {
    event.preventDefault();
    const paste = (event.clipboardData || window.clipboardData).getData('text');
    if (/^\d{6}$/.test(paste)) {
      this.digits = paste.split('');
      this.$refs.submit.focus();
    }
  },
  
  handleBackspace(index, event) {
    if (event.key === 'Backspace' && !this.digits[index] && index > 0) {
      this.$refs['digit' + (index - 1)].focus();
    }
  },
  
  get code() {
    return this.digits.join('');
  },
  
  get isComplete() {
    return this.code.length === 6;
  },
  
  async submit() {
    if (!this.isComplete) return;
    // POST to /otp-verify/ with code
  },
  
  async resend() {
    if (this.resendTimer > 0) return;
    // POST to /otp-resend/
    this.resendTimer = 30;
  },
  
  init() {
    setInterval(() => {
      if (this.timer > 0) this.timer--;
      if (this.resendTimer > 0) this.resendTimer--;
    }, 1000);
    this.$refs.digit0.focus();
  }
}"
```

# Error States:
- كود خاطئ: shake animation + رسالة حمراء + يمسح الصناديق
- كود منتهي: يطلب إعادة الإرسال
- محاولات كثيرة: lockout 5 دقائق

# الـ View Backend:
```python
class OTPVerifyView(View):
    template_name = 'auth/otp_verify.html'
    
    def get(self, request):
        if not request.session.get('otp_user_id'):
            return redirect('login')
        return render(request, self.template_name, {
            'masked_email': mask_email(request.session.get('email'))
        })
    
    def post(self, request):
        code = request.POST.get('code')
        # verify + create session + redirect
```

أعطني:
1. الـ template الكامل
2. الـ View الكامل
3. helper function لإخفاء البريد جزئياً
```

---

## 🎯 Prompt 3.4 — صفحة Password Reset

```
في مشروع Tadgeeg AI، ملفات `templates/auth/password_reset_*.html`:

المطلوب: حدّث كل صفحات إعادة تعيين كلمة المرور بهوية تدقيق.

# 1. password_reset_form.html (طلب الإعادة):
- صفحة مركزية بسيطة
- العنوان: "نسيت كلمة المرور؟"
- الوصف: "أدخل بريدك الإلكتروني وسنرسل لك رابط إعادة التعيين"
- حقل واحد: البريد الإلكتروني
- زر "إرسال رابط إعادة التعيين" (#10B981)
- رابط "العودة لتسجيل الدخول"

# 2. password_reset_done.html (تأكيد الإرسال):
- أيقونة دائرة خضراء كبيرة + علامة Mail
- العنوان: "تحقق من بريدك"
- الوصف: "أرسلنا تعليمات إعادة تعيين كلمة المرور إلى بريدك الإلكتروني"
- "لم يصلك الإيميل؟ تحقق من مجلد الـ Spam أو حاول مجدداً"
- زر "إعادة الإرسال" (outline)
- زر "العودة لتسجيل الدخول"

# 3. password_reset_confirm.html (تعيين كلمة جديدة):
- العنوان: "أنشئ كلمة مرور جديدة"
- حقل: كلمة المرور الجديدة (مع zxcvbn strength meter)
- حقل: تأكيد كلمة المرور
- متطلبات الكلمة بشكل واضح:
  ✓ 8 أحرف على الأقل
  ✓ حرف كبير
  ✓ حرف صغير
  ✓ رقم
  ✓ رمز خاص
  (تتحول من ✗ إلى ✓ في الوقت الحقيقي)
- زر "تعيين كلمة المرور" (#10B981)
- مفعّل فقط عند استيفاء جميع المتطلبات

# 4. password_reset_complete.html (نجاح):
- أيقونة دائرة خضراء + علامة صح كبيرة (animation)
- العنوان: "تم بنجاح!"
- الوصف: "تم تعيين كلمة المرور الجديدة بنجاح"
- زر "تسجيل الدخول الآن" (#10B981)

# 5. password_reset_email.html (الإيميل):
- ترويسة بهوية تدقيق
- "مرحباً [الاسم]،"
- "تلقينا طلباً لإعادة تعيين كلمة المرور..."
- زر كبير "إعادة تعيين كلمة المرور" (background: #10B981)
- "أو انسخ الرابط: [URL]"
- "هذا الرابط ينتهي خلال 60 دقيقة"
- "لم تطلب هذا؟ تجاهل هذا الإيميل"
- توقيع: "فريق تدقيق"

# الشروط:
- نفس النمط البصري لصفحات auth
- استخدم Django's PasswordResetView و forms
- احتفظ بـ {% csrf_token %}
- ترجمة كاملة {% trans %}
- Alpine.js للـ password strength meter
- استخدم zxcvbn-js للتحقق من القوة (CDN)

أعطني الـ 5 ملفات كاملة.
```

---

## 🎯 Prompt 3.5 — صفحة MFA Setup (إعداد المصادقة الثنائية)

```
في مشروع Tadgeeg AI، الملف `templates/settings/mfa_settings.html` 
يدير إعدادات MFA. أحتاج تطوير شاشة إعداد محسّنة.

المطلوب:

# 1. أنشئ template جديد: `templates/auth/mfa_setup.html`
لإعداد TOTP من الصفر (مرحلة إنشاء الحساب أو من الإعدادات).

# الخطوات (Wizard):

## الخطوة 1: تأكيد الهوية
- "نحتاج للتأكد من هويتك أولاً"
- حقل كلمة المرور
- زر "متابعة"

## الخطوة 2: اختيار طريقة MFA
3 بطاقات:
- 📱 تطبيق المصادقة (Google Authenticator/Authy) [مُوصى به]
- 📧 البريد الإلكتروني
- 💬 الرسائل النصية SMS

## الخطوة 3: مسح QR Code (إذا اختار التطبيق)
- عرض QR code (من Django backend)
- "امسح هذا الرمز باستخدام تطبيق المصادقة"
- زر "لا يمكنني مسح الكود؟" - يُظهر السر النصي للنسخ
- "بمجرد المسح، أدخل الرمز المعروض في التطبيق"
- 6 صناديق إدخال للرمز (مثل OTP)
- زر "تأكيد"

## الخطوة 4: نسخ الـ Recovery Codes
- "احفظ هذه الرموز في مكان آمن"
- شبكة 10 أكواد (8 أحرف each)
- زر "نسخ الكل" + "تحميل كـ TXT" + "طباعة"
- Checkbox: "حفظت الرموز في مكان آمن"
- زر "إنهاء" (مفعّل فقط بعد التشيك)

## الخطوة 5: نجاح
- أيقونة Shield خضراء كبيرة
- "تم تفعيل المصادقة الثنائية!"
- "حسابك أصبح أكثر أماناً"
- زر "العودة للوحة التحكم"

# Progress Indicator:
في الأعلى: 5 نقاط متصلة بخط
- النقاط المكتملة: #10B981 + ✓
- النقطة الحالية: #003366 + رقم
- النقاط القادمة: رمادية + رقم

# Logic مع Alpine.js:
- x-data="{ step: 1, password: '', code: '', secret: '', recoveryCodes: [], copied: false }"
- transitions بين الخطوات (slide left/right)
- تحقق من القوة قبل الانتقال

# Backend Endpoints (في apps/authentication/views.py):
```python
class MFASetupView(LoginRequiredMixin, View):
    template_name = 'auth/mfa_setup.html'
    
    def get(self, request):
        # generate QR code + secret
        # store in session
        return render(request, self.template_name, context)
    
    def post(self, request):
        action = request.POST.get('action')
        if action == 'verify_password':
            ...
        elif action == 'verify_code':
            ...
        elif action == 'confirm_setup':
            # save MFA settings
            # generate recovery codes
            ...
```

# مكتبة TOTP:
استخدم `django-otp` و `qrcode` (موجودين في requirements.txt).

# الـ Recovery Codes:
- 10 أكواد عشوائية (8 أحرف base32)
- مخزّنة hashed في DB
- يمكن استخدام كل واحد مرة واحدة فقط
- يمكن إعادة توليدهم من الإعدادات

أعطني:
1. الـ template كامل
2. الـ Views كاملة
3. الـ Models إذا احتجت تعديل (RecoveryCode model)
4. الـ migrations
```

---

## 🎯 Prompt 3.6 — صفحة Logout مع Confirmation

```
في مشروع Tadgeeg AI، أحتاج صفحة تأكيد لتسجيل الخروج.

المطلوب:

# 1. Modal بدلاً من صفحة كاملة (تجربة أحسن):
عند الضغط على "تسجيل الخروج" في الـ Sidebar، يظهر modal:
- خلفية شبه شفافة + blur
- بطاقة مركزية:
  - أيقونة LogOut بدائرة برتقالية
  - "هل أنت متأكد من تسجيل الخروج؟"
  - "ستحتاج لإعادة تسجيل الدخول للوصول لحسابك"
  - زرين:
    • "إلغاء" (outline)
    • "تأكيد الخروج" (#ef4444)

# 2. Logic:
- عند الضغط على تأكيد:
  - GET request لـ /logout/
  - Django ينهي الـ session
  - Redirect لـ /login/?logged_out=1

# 3. صفحة Login بعد الخروج:
- في الأعلى: شريط أخضر صغير
- "✓ تم تسجيل خروجك بنجاح"
- يختفي بعد 5 ثواني

# 4. Auto-Logout بعد عدم النشاط:
أضف Alpine.js component في base.html:
```javascript
x-data="autoLogout()"
x-init="init()"

function autoLogout() {
  return {
    timeout: 30 * 60 * 1000, // 30 minutes
    timer: null,
    
    init() {
      ['mousemove', 'keypress', 'scroll', 'click'].forEach(event => {
        document.addEventListener(event, () => this.resetTimer());
      });
      this.resetTimer();
    },
    
    resetTimer() {
      clearTimeout(this.timer);
      this.timer = setTimeout(() => {
        this.showWarning();
      }, this.timeout - 60000); // تحذير قبل دقيقة
    },
    
    showWarning() {
      // Modal: "ستخرج تلقائياً خلال 60 ثانية"
      // عداد + زرين: "البقاء" أو "تسجيل الخروج"
    }
  }
}
```

# 5. Backend:
- GET /logout/ → ينهي session ويوجه لـ login
- استخدم Django's LogoutView مع تخصيص next_page

أعطني:
1. الـ Modal HTML (يضاف في base.html)
2. الـ JavaScript للـ auto-logout
3. تحديث urls.py للـ logout view
```

---

## 🎯 Prompt 3.7 — صفحة Email Verification (تأكيد البريد)

```
في مشروع Tadgeeg AI، عند التسجيل أحتاج تأكيد البريد قبل تفعيل الحساب.

المطلوب:

# 1. أنشئ template: `templates/auth/email_verify.html`
صفحة "تحقق من بريدك" تظهر بعد التسجيل:
- أيقونة Mail متحركة (يهتز قليلاً)
- "تحقق من بريدك الإلكتروني"
- "أرسلنا رابط التفعيل إلى: u***@e***.com"
- "اضغط على الرابط في الإيميل لتفعيل حسابك"
- زر "إعادة إرسال الإيميل" (يكون disabled لأول دقيقة)
- "فتح Gmail" (إذا الإيميل @gmail.com)
- "لم يصلك؟ تحقق من مجلد Spam"
- "خطأ في البريد؟ غيّره"

# 2. أنشئ template: `templates/auth/email_verified.html`
صفحة النجاح بعد الضغط على الرابط:
- أيقونة دائرة خضراء + علامة صح كبيرة (animation)
- "تم تفعيل بريدك بنجاح! 🎉"
- "أهلاً بك في عائلة تدقيق"
- "بدأت رحلتك التجريبية لمدة 14 يوم"
- زر "الذهاب للوحة التحكم" (#10B981)
- في الأسفل: 4 خطوات سريعة للبدء
  1. أكمل ملفك الشخصي
  2. ادعُ فريقك
  3. ارفع أول فاتورة
  4. شاهد التقرير

# 3. أنشئ template: `templates/auth/email_verify_failed.html`
صفحة الفشل (الرابط منتهي أو خاطئ):
- أيقونة AlertCircle حمراء
- "الرابط غير صالح أو منتهي"
- "روابط التفعيل تنتهي بعد 24 ساعة"
- زر "إرسال رابط جديد"
- "أو سجّل بإيميل آخر"

# 4. Email Template: `templates/auth/emails/email_verify.html`
- ترويسة بهوية تدقيق
- تحية باسم المستخدم
- "اضغط على الزر للتفعيل:"
- زر كبير "تفعيل حسابي" (#10B981)
- "أو انسخ الرابط: [URL]"
- "ينتهي بعد 24 ساعة"
- توقيع وتذييل

# 5. الـ Backend:

في `apps/authentication/models.py`:
```python
class EmailVerificationToken(SoftDeleteModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    token = models.CharField(max_length=64, unique=True, db_index=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    
    @classmethod
    def generate_for(cls, user):
        token = secrets.token_urlsafe(48)
        return cls.objects.create(
            user=user,
            token=token,
            expires_at=timezone.now() + timedelta(hours=24)
        )
```

في `apps/authentication/views.py`:
```python
class EmailVerifyView(View):
    def get(self, request, token):
        try:
            t = EmailVerificationToken.objects.get(
                token=token,
                used_at__isnull=True,
                expires_at__gt=timezone.now()
            )
            t.user.is_active = True
            t.user.email_verified = True
            t.user.save()
            t.used_at = timezone.now()
            t.save()
            return render(request, 'auth/email_verified.html')
        except EmailVerificationToken.DoesNotExist:
            return render(request, 'auth/email_verify_failed.html')
```

# 6. URLs:
```python
path('email-verify/<str:token>/', EmailVerifyView.as_view(), name='email-verify')
path('email-verify-pending/', EmailVerifyPendingView.as_view(), name='email-verify-pending')
path('resend-verification/', ResendVerificationView.as_view(), name='resend-verification')
```

أعطني:
1. الـ 4 templates الكاملة
2. الـ Models + Migrations
3. الـ Views كاملة
4. الـ URLs
5. الـ task للـ Celery لإرسال الإيميل (إذا مناسب)
```

---

## 🎯 Prompt 3.8 — Social Login (Google OAuth)

```
في مشروع Tadgeeg AI، ملف `templates/auth/google_pending.html` موجود.
أحتاج تكامل Google OAuth صحيح.

المطلوب:

# 1. أضف زر "Continue with Google" في login.html و register.html:
- زر أبيض مع border رمادي
- شعار Google صغير + "متابعة باستخدام Google"
- يظهر تحت زر تسجيل الدخول العادي
- مفصول بـ "أو" بخط أفقي

# 2. الـ Backend Setup:

في `requirements.txt`:
```
django-allauth>=0.55.0
```

في `settings.py`:
```python
INSTALLED_APPS += [
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',
]

AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]

SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'SCOPE': ['profile', 'email'],
        'AUTH_PARAMS': {'access_type': 'online'},
        'OAUTH_PKCE_ENABLED': True,
    }
}

SITE_ID = 1
LOGIN_REDIRECT_URL = '/dashboard/'
```

في `urls.py`:
```python
urlpatterns += [
    path('accounts/', include('allauth.urls')),
]
```

# 3. صفحة google_pending.html (الموجودة):
- يجب تحديثها لتعرض:
  - "نُكمل تسجيل الدخول..."
  - spinner متحرك
  - "إذا استغرق وقتاً طويلاً، اضغط هنا"

# 4. صفحة "اختيار/ربط الحساب":
عند تسجيل الدخول لأول مرة بـ Google:
- "مرحباً [الاسم]!"
- "نحتاج بعض المعلومات الإضافية لإكمال حسابك"
- حقول:
  - اسم الشركة
  - الدور
  - حجم الشركة
  - رقم الهاتف
- زر "إنشاء حساب"

# 5. الإعدادات في .env:
```
GOOGLE_CLIENT_ID=your-client-id
GOOGLE_CLIENT_SECRET=your-client-secret
```

# 6. الإعدادات في Google Cloud Console:
- اقترح خطوات إعداد OAuth 2.0 client
- Authorized redirect URIs: 
  • http://localhost:8000/accounts/google/login/callback/
  • https://tadgeeg.com/accounts/google/login/callback/

# 7. الأمان:
- التحقق من الـ email_verified من Google
- ربط الحساب مع organization
- منع تسجيل الدخول بـ Google لحسابات بـ password (إلا بعد تأكيد)

أعطني:
1. تحديثات على login.html و register.html (الزر فقط)
2. تحديث على google_pending.html
3. صفحة إكمال التسجيل
4. تحديثات settings.py + urls.py
5. خطوات إعداد Google Cloud Console
```

---

## ✅ Checklist بعد تطبيق هذا القسم

- [ ] صفحة `/login/` بهوية تدقيق وsplit layout
- [ ] صفحة `/register/` تعمل وتُنشئ User + Organization
- [ ] صفحة `/otp-verify/` تعمل مع 6 صناديق + paste support
- [ ] صفحات Password Reset الـ 4 محدّثة
- [ ] صفحة MFA Setup wizard كاملة
- [ ] Logout modal + auto-logout بعد عدم النشاط
- [ ] Email verification يعمل بالكامل
- [ ] Google OAuth (اختياري)
- [ ] كل صفحات الـ auth responsive
- [ ] الترجمات `{% trans %}` تعمل
- [ ] الاختبارات في `tests/test_auth_flows.py` تنجح
- [ ] Rate limiting على login/register
- [ ] CSRF protection على كل الـ forms
- [ ] لا توجد ألوان بنفسجية

---

**📌 بعد إكمال هذا القسم، انتقل لـ `04-DASHBOARD.md`**
