# Tadgeeg Codebase Reference: MFA & Report Components

**Generated:** March 25, 2026  
**Scope:** Login/Auth views, MFA models/services, Report models/serializers, Templates

---

## 1️⃣ LOGIN VIEW & API

### Location
📁 [apps/authentication/views.py](apps/authentication/views.py) — Lines 134-190

### LoginView Class Implementation

```python
class LoginView(APIView):
    permission_classes = [AllowAny]
    IP_MAX = 20
    IP_LOCK = 900

    def _get_ip(self, request):
        """Extract client IP from request headers."""
        xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
        return xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR", "unknown")

    @extend_schema(
        tags=["Auth"],
        summary="Login and obtain JWT tokens",
        request=LoginSerializer,
        responses={200: {"type": "object", "properties": {
            "access": {"type": "string"},
            "refresh": {"type": "string"},
            "user": {"type": "object"},
        }}},
    )
    def post(self, request):
        # 1. Rate Limit by IP (DoS protection)
        ip = self._get_ip(request)
        ip_key = f"login_ip:{ip}"
        ip_attempts = cache.get(ip_key, 0)
        if ip_attempts >= self.IP_MAX:
            return Response(
                {"error": _("Too many login attempts. Try again in 15 minutes.")},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        # 2. Validate Credentials
        serializer = LoginSerializer(data=request.data)
        if not serializer.is_valid():
            cache.set(ip_key, ip_attempts + 1, self.IP_LOCK)
            raise ValidationError(serializer.errors)
        data = serializer.validated_data
        user = data["user"]

        # 3. Email Verification Check
        if not user.is_email_verified:
            try:
                challenge, sent = issue_email_otp(user, request)
            except EmailOTPError as exc:
                cache.set(ip_key, ip_attempts + 1, self.IP_LOCK)
                return Response(
                    {
                        "verification_required": True,
                        "redirect": reverse("frontend:otp_verify"),
                        "error": exc.message,
                    },
                    status=_otp_error_status(exc),
                )
            # Return 202 Accepted with pending verification payload
            return Response(_otp_pending_payload(user, challenge, sent=sent), status=status.HTTP_202_ACCEPTED)

        # 4. Complete Login (all checks passed, email verified)
        cache.delete(ip_key)
        log_action(request, AuditLog.Action.LOGIN, "user", str(user.id))
        payload = _verified_login_payload(request, user)
        response = Response(payload)
        set_auth_cookies(response, payload["access"], payload["refresh"])
        return response
```

### Password Validation & Failed Attempts (LoginSerializer)

**Location:** [apps/authentication/serializers.py](apps/authentication/serializers.py) — Lines 113-165

```python
class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        email = attrs.get("email")
        password = attrs.get("password")

        # 1. User Lookup
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            raise serializers.ValidationError({"email": _("Invalid credentials.")})

        # 2. Account Lock Check
        if user.is_locked():
            raise serializers.ValidationError(
                {"non_field_errors": _("Account is temporarily locked. Please try again later.")}
            )

        # 3. Password Verification (Django default backend)
        user_auth = authenticate(email=email, password=password)

        # 4. Failed Attempts Tracking (5 attempts → 30 min lock)
        if not user_auth:
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= 5:
                user.locked_until = timezone.now() + timedelta(minutes=30)
            user.save(update_fields=["failed_login_attempts", "locked_until"])
            raise serializers.ValidationError({"non_field_errors": _("Invalid credentials.")})

        # 5. Active Status Check
        if not user_auth.is_active:
            raise serializers.ValidationError({"non_field_errors": _("Account is inactive.")})

        # 6. Reset Failed Attempts on Success
        user_auth.failed_login_attempts = 0
        user_auth.locked_until = None
        user_auth.save(update_fields=["failed_login_attempts", "locked_until"])

        return {
            "user": user_auth,
        }
```

### Token Issuance Pattern

**Location:** [apps/authentication/services/email_otp.py](apps/authentication/services/email_otp.py) — Lines 150-165

```python
def complete_verified_login(request, user: User) -> dict:
    """
    Complete the login flow after all verification checks pass.
    Issues JWT tokens and sets httpOnly cookies.
    """
    # 1. Ensure organization membership
    if not user.organization_id:
        ensure_user_organization(user, promote_owner=True)

    # 2. Update login metadata
    user.last_login_ip = request.META.get("REMOTE_ADDR")
    user.last_login = timezone.now()
    user.failed_login_attempts = 0
    user.locked_until = None
    user.save(update_fields=["last_login_ip", "last_login", "failed_login_attempts", "locked_until"])

    # 3. Create Django session
    django_login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    clear_pending_verification(request)

    # 4. Issue JWT tokens (simplejwt)
    refresh = RefreshToken.for_user(user)
    return {
        "access": str(refresh.access_token),    # Short-lived (~5 min)
        "refresh": str(refresh),                 # Long-lived (~24 hours)
    }
```

### ⚠️ CRITICAL GAP: MFA Not Enforced in LoginView

The current `LoginView` **never checks `user.mfa_enabled`** even though the User model has:
- `mfa_enabled: BooleanField`
- `mfa_secret: CharField`

**Missing Logic:** After password verification but before token issuance, should check:
```python
if user.mfa_enabled and user.mfa_secret:
    # Return 202 with temporary token requiring TOTP verification
    return Response({
        'mfa_required': True,
        'temp_token': temp_mfa_token,
        'mfa_expires_at': ...
    }, status=202)
```

---

## 2️⃣ MFA MODELS

### Location
📁 [apps/authentication/models.py](apps/authentication/models.py)

### User Model MFA Fields

```python
class User(AbstractBaseUser, PermissionsMixin):
    """Custom user model with role-based access control."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=255)
    role = models.CharField(max_length=30, choices=Role.choices, default=Role.JUNIOR_AUDITOR)
    organization = models.ForeignKey(
        "Organization", on_delete=models.SET_NULL, null=True, blank=True, related_name="users"
    )
    
    # ── MFA Fields ────────────────────────────────────────
    mfa_enabled = models.BooleanField(default=False)           # TOTP enabled?
    mfa_secret = models.CharField(max_length=64, blank=True)   # Base32 secret key
    # ──────────────────────────────────────────────────────
    
    # Account Security
    email_verified_at = models.DateTimeField(null=True, blank=True)
    last_login_ip = models.GenericIPAddressField(null=True, blank=True)
    failed_login_attempts = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def is_email_verified(self):
        """Check if email has been verified."""
        return self.email_verified_at is not None

    def is_locked(self):
        """Check if account is temporarily locked after failed attempts."""
        if self.locked_until and self.locked_until > timezone.now():
            return True
        return False
```

### EmailOTPVerification Model

**Purpose:** Single-use email OTP challenges for registration/login verification (NOT TOTP)

```python
class EmailOTPVerification(models.Model):
    """Single-use email OTP challenges for onboarding verification."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="email_otp_verifications",
    )
    otp_code_hash = models.CharField(max_length=255)  # Hashed OTP code
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()               # 10 min default
    is_used = models.BooleanField(default=False)
    used_at = models.DateTimeField(null=True, blank=True)
    attempts_count = models.PositiveSmallIntegerField(default=0)
    resend_count = models.PositiveSmallIntegerField(default=0)
    last_sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "auth_email_otp_verifications"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["user", "is_used"]),
            models.Index(fields=["expires_at"]),
        ]

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at

    @property
    def resend_available_at(self):
        cooldown_seconds = int(getattr(settings, "EMAIL_OTP_RESEND_COOLDOWN_SECONDS", 60))
        return self.last_sent_at + timedelta(seconds=cooldown_seconds)
```

---

## 3️⃣ MFA SERVICES

### Location
📁 [apps/authentication/services/email_otp.py](apps/authentication/services/email_otp.py)

### OTP Configuration

```python
@dataclass(frozen=True)
class OTPConfig:
    length: int                  # 6 digits
    expiry_minutes: int          # 10 min
    resend_cooldown_seconds: int # 60 sec
    max_resend_attempts: int     # 3 times
    max_verify_attempts: int     # 5 attempts

def get_otp_config() -> OTPConfig:
    return OTPConfig(
        length=int(getattr(settings, "EMAIL_OTP_LENGTH", 6)),
        expiry_minutes=int(getattr(settings, "EMAIL_OTP_EXPIRY_MINUTES", 10)),
        resend_cooldown_seconds=int(getattr(settings, "EMAIL_OTP_RESEND_COOLDOWN_SECONDS", 60)),
        max_resend_attempts=int(getattr(settings, "EMAIL_OTP_MAX_RESEND_ATTEMPTS", 3)),
        max_verify_attempts=int(getattr(settings, "EMAIL_OTP_MAX_VERIFY_ATTEMPTS", 5)),
    )
```

### Email OTP Issuance

**Core Logic:** Lines 260-330

```python
def issue_email_otp(user: User, request, *, allow_recent_reuse: bool = True) -> tuple[EmailOTPVerification, bool]:
    """
    Issue or reuse an email OTP challenge.
    
    Returns:
        tuple[EmailOTPVerification, sent: bool] — challenge object and whether newly sent
    """
    if user.is_email_verified:
        clear_pending_verification(request)
        raise EmailOTPError(_("This email address has already been verified."), code="already_verified")

    config = get_otp_config()
    now = timezone.now()
    current = get_latest_pending_challenge(user)  # Get most recent unused challenge
    
    # ── Reuse Recent Challenge (within 60 sec) ────────────────────
    if (
        allow_recent_reuse
        and current is not None
        and not current.is_expired
        and (now - current.last_sent_at).total_seconds() < config.resend_cooldown_seconds
    ):
        remember_pending_verification(request, user)
        return current, False  # Return existing challenge, not newly sent

    # ── Issue New Challenge ────────────────────────────────────────
    resend_count = current.resend_count if current is not None else 0
    _invalidate_unused_challenges(user)  # Mark old ones as used

    otp_code = generate_otp_code(config.length)  # Generate 6-digit code
    challenge = EmailOTPVerification.objects.create(
        user=user,
        otp_code_hash=make_password(otp_code),      # Hash using Django's password hasher
        expires_at=now + timedelta(minutes=config.expiry_minutes),
        resend_count=resend_count,
    )

    try:
        _send_otp_email(user, otp_code, challenge.expires_at, language=getattr(request, "LANGUAGE_CODE", None))
    except Exception as exc:
        challenge.delete()
        raise EmailOTPError(
            _("Unable to send the verification code right now. Please try again shortly."),
            code="send_failed",
        ) from exc

    remember_pending_verification(request, user)
    return challenge, True  # Successfully issued and sent
```

### Email OTP Verification

**Core Logic:** Lines 352-415

```python
def verify_email_otp(user: User, otp_code: str) -> User:
    """
    Verify an OTP code and mark email as verified.
    
    Raises:
        EmailOTPError with codes: missing_otp, otp_expired, attempts_exceeded, otp_invalid
    """
    if user.is_email_verified:
        return user

    config = get_otp_config()
    challenge = get_latest_pending_challenge(user)
    
    # ── Validation Checks ──────────────────────────────────────
    if challenge is None:
        raise EmailOTPError(
            _("There is no active verification code. Resend the code to continue."),
            code="missing_otp",
        )

    # Check expiry
    if challenge.is_expired:
        challenge.is_used = True
        challenge.used_at = timezone.now()
        challenge.save(update_fields=["is_used", "used_at"])
        raise EmailOTPError(
            _("The verification code has expired. Resend a new code to continue."),
            code="otp_expired",
        )

    # Check attempt limit
    if challenge.attempts_count >= config.max_verify_attempts:
        challenge.is_used = True
        challenge.used_at = timezone.now()
        challenge.save(update_fields=["is_used", "used_at"])
        raise EmailOTPError(
            _("You have exceeded the allowed number of attempts. Resend a new code."),
            code="attempts_exceeded",
        )

    # ── Code Verification ──────────────────────────────────────
    normalized_code = (otp_code or "").strip()
    if not check_password(normalized_code, challenge.otp_code_hash):
        challenge.attempts_count += 1
        update_fields = ["attempts_count"]
        
        if challenge.attempts_count >= config.max_verify_attempts:
            challenge.is_used = True
            challenge.used_at = timezone.now()
            update_fields.extend(["is_used", "used_at"])
            
        challenge.save(update_fields=update_fields)
        remaining = config.max_verify_attempts - challenge.attempts_count
        raise EmailOTPError(
            _("The verification code is incorrect. You have %(remaining)s attempts left.") % {"remaining": remaining},
            code="otp_invalid",
        )

    # ── Mark Challenge Used & Email Verified ───────────────────
    challenge.is_used = True
    challenge.used_at = timezone.now()
    challenge.save(update_fields=["is_used", "used_at"])

    user.email_verified_at = timezone.now()
    user.save(update_fields=["email_verified_at"])
    return user
```

### TOTP (Time-based OTP) Views for MFA

**Location:** [apps/authentication/views.py](apps/authentication/views.py) — Lines 785-900

```python
class MFASetupView(APIView):
    """
    GET → Generate TOTP secret and provisioning URI
    POST → Verify TOTP code and enable MFA
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Auth"], summary="Setup TOTP-based MFA")
    def get(self, request):
        try:
            import pyotp
        except ImportError:
            return Response({"error": "pyotp غير متاح."}, status=500)

        secret = pyotp.random_base32()
        request.session["mfa_pending_secret"] = secret

        totp = pyotp.TOTP(secret)
        provisioning_uri = totp.provisioning_uri(
            name=request.user.email,
            issuer_name="Tadgeeg"
        )

        return Response({
            "provisioning_uri": provisioning_uri,
            "secret": secret,
            "qr_code_url": f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={provisioning_uri}",
        })

    def post(self, request):
        try:
            import pyotp
        except ImportError:
            return Response({"error": "pyotp غير متاح."}, status=500)

        secret = request.session.get("mfa_pending_secret")
        code = str(request.data.get("code", "")).strip()
        
        if not secret or not code:
            return Response({"error": "Secret or code missing."}, status=400)

        totp = pyotp.TOTP(secret)
        if not totp.verify(code, valid_window=1):
            return Response({"error": "الرمز غير صحيح أو منتهي الصلاحية."}, status=400)

        user = request.user
        user.mfa_secret = secret
        user.mfa_enabled = True
        user.save(update_fields=["mfa_secret", "mfa_enabled"])
        request.session.pop("mfa_pending_secret", None)

        log_action(request, AuditLog.Action.USER_UPDATED, "user", str(user.id),
                   details={"change": "mfa_enabled"})

        return Response({"success": True, "message": "تم تفعيل المصادقة الثنائية بنجاح."})


class MFAVerifyView(APIView):
    """
    POST → Verify a TOTP code for a user who has MFA enabled.
    Used as a second-factor check after password login.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Auth"], summary="Verify TOTP code (second factor)")
    def post(self, request):
        try:
            import pyotp
        except ImportError:
            return Response({"error": "pyotp غير متاح."}, status=500)

        user = request.user
        if not user.mfa_enabled or not user.mfa_secret:
            return Response({"error": "المصادقة الثنائية غير مفعلة لهذا الحساب."}, status=400)

        code = str(request.data.get("code", "")).strip()
        if not code:
            return Response({"error": "الرمز مطلوب."}, status=400)

        totp = pyotp.TOTP(user.mfa_secret)
        if not totp.verify(code, valid_window=1):
            return Response({"error": "الرمز غير صحيح أو منتهي الصلاحية."}, status=400)

        return Response({"success": True, "message": "تم التحقق من الهوية."})


class MFADisableView(APIView):
    """POST → Verify current TOTP code then disable MFA."""
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["Auth"], summary="Disable MFA (requires valid TOTP code)")
    def post(self, request):
        try:
            import pyotp
        except ImportError:
            return Response({"error": "pyotp غير متاح."}, status=500)

        user = request.user
        if not user.mfa_enabled:
            return Response({"error": "المصادقة الثنائية غير مفعلة."}, status=400)

        code = str(request.data.get("code", "")).strip()
        if not code:
            return Response({"error": "الرمز مطلوب للتحقق قبل إلغاء التفعيل."}, status=400)

        totp = pyotp.TOTP(user.mfa_secret)
        if not totp.verify(code, valid_window=1):
            return Response({"error": "الرمز غير صحيح."}, status=400)

        user.mfa_enabled = False
        user.mfa_secret = ""
        user.save(update_fields=["mfa_enabled", "mfa_secret"])

        log_action(request, AuditLog.Action.USER_UPDATED, "user", str(user.id),
                   details={"change": "mfa_disabled"})

        return Response({"success": True, "message": "تم إلغاء تفعيل المصادقة الثنائية."})
```

---

## 4️⃣ LOGIN TEMPLATES

### Location
📁 [templates/auth/login.html](templates/auth/login.html) — Main login form

Key Structure:
- Alpine.js state management (`x-data="loginPage()"`)
- Async form submission to `{% url "frontend:login" %}`
- Password visibility toggle
- Email/password fields
- Forgot password link

### OTP Verification Template

**Location:** [templates/auth/otp_verify.html](templates/auth/otp_verify.html)

```html
<!-- Email Verification Code Input -->
<div x-data="otpVerifyPage({
  resendCooldown: {{ resend_cooldown_seconds|default:0 }},
  attemptsRemaining: {{ otp_attempts_remaining|default:5 }},
  resendRemaining: {{ otp_resend_remaining|default:3 }},
  initialError: '{{ error_message|default:""|escapejs }}'
})">

  <!-- 6 Individual OTP Digit Boxes -->
  <div class="grid grid-cols-6 gap-2 sm:gap-3" dir="ltr" @paste.prevent="handlePaste">
    <template x-for="(digit, index) in digits" :key="index">
      <input
        type="text"
        inputmode="numeric"
        maxlength="1"
        class="otp-box h-14 rounded-2xl border border-slate-200 bg-slate-50 text-center text-2xl font-extrabold tracking-wider text-slate-900"
        x-model="digits[index]"
        @input="handleInput(index, $event)"
        @keydown="handleKeydown(index, $event)"
        :data-index="index"
      >
    </template>
  </div>

  <!-- Attempt/Resend Counters -->
  <div class="mt-3 flex items-center justify-between text-xs text-slate-500">
    <span>{% trans "Remaining attempts:" %} <span x-text="attemptsRemaining"></span></span>
    <span>{% trans "Remaining resends:" %} <span x-text="resendRemaining"></span></span>
  </div>

  <!-- Verify Button -->
  <button type="submit" @click="submitOtp">
    {% trans "Verify code and sign in" %}
  </button>

  <!-- Resend Cooldown -->
  <button type="button" @click="resendOtp" :disabled="countdown > 0">
    <span x-show="countdown > 0">{% trans "Resend after" %} <span x-text="countdown"></span>s</span>
    <span x-show="countdown === 0">{% trans "Resend code" %}</span>
  </button>
</div>
```

---

## 5️⃣ REPORT MODELS & SERIALIZERS

### Report Model

**Location:** [apps/reports/models.py](apps/reports/models.py)

```python
class Report(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    generated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    
    # Metadata
    title = models.CharField(max_length=255)
    report_type = models.CharField(max_length=50)  # "invoice_audit", "isa700_opinion", etc.
    language = models.CharField(max_length=5, default="en")
    
    # Period
    period_from = models.CharField(max_length=10, blank=True)
    period_to = models.CharField(max_length=10, blank=True)
    
    # Audit Data & Narrative
    data = models.JSONField(default=dict)         # All audit findings/metrics
    narrative = models.JSONField(default=dict)    # Narrative report sections
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "reports"
        ordering = ["-created_at"]

    def __str__(self):
        return self.title
```

### Report JSON Structure (from `data` field)

The `data` field contains comprehensive audit report with:

```python
{
    # Report Header
    "report_header": {...},
    "summary": {
        "total_invoices": 150,
        "compliance_score": 92.5,
        "critical_findings": 2,
        "high_findings": 5,
        ...
    },
    
    # Financial Analysis (IAS 7)
    "ias7_cashflow_classification": [...],
    "ias7_cashflow_statement": {...},
    
    # ISA 701: Key Audit Matters
    "key_audit_matters": [
        {
            "kam_id": "KAM-001",
            "isa_reference": "ISA 701",
            "severity": "high",
            "title_ar": "...", "title_en": "...",
            "description_ar": "...", "description_en": "...",
            "root_cause_ar": "...", "root_cause_en": "...",
            "financial_impact": "250000 SAR",
            "recommendation_ar": "...", "recommendation_en": "...",
            "evidence": ["Invoice #1001", "Voucher #5612", ...],
        },
        ...
    ],
    
    # ISA 700: Comprehensive Auditor Opinion (13 sections)
    "isa700_auditor_opinion": {
        # Section 1: Management Responsibility
        "management_responsibility": {
            "text_ar": "...", "text_en": "..."
        },
        
        # Section 2: Auditor Responsibility
        "auditor_responsibility": {
            "text_ar": "...", "text_en": "..."
        },
        
        # Section 3: Scope & Basis
        "scope_and_basis": {
            "text_ar": "...", "text_en": "..."
        },
        
        # Section 4: Risk Assessment (ISA 315)
        "risk_assessment_summary": {
            "risks": [
                {
                    "risk_category": "duplicate_invoices",
                    "risk_level": "high",
                    "description_ar": "...", "description_en": "..."
                },
                ...
            ]
        },
        
        # Section 5: Compliance Statement
        "compliance_statement": {
            "text_ar": "...", "text_en": "..."
        },
        
        # Section 6: Audit Evidence (ISA 330)
        "audit_evidence_summary": {
            "procedures": [
                {"procedure": "Analytical procedures", "evidence_found": "..."},
                {"procedure": "Detailed testing", "evidence_found": "..."},
                ...
            ]
        },
        
        # Section 7: Opinion Paragraph (4 types: unqualified/qualified/adverse/disclaimer)
        "opinion_paragraph": {
            "text_ar": "...", "text_en": "...",
            "opinion_type": "unqualified|qualified|adverse|disclaimer",
        },
        
        # Section 8: Basis for Opinion
        "basis_for_opinion": {
            "facts": [
                {"metric": "Compliance Rate", "value": "92.5%"},
                {"metric": "Critical Issues", "value": "0"},
                ...
            ]
        },
        
        # Section 9: KAMs Summary (linked to ISA 701)
        "key_audit_matters_summary": {...},
        
        # Section 10: Going Concern (ISA 570)
        "going_concern_assessment": {
            "assessment": "No going concern issues identified"
        },
        
        # Section 11: Subsequent Events (ISA 560)
        "subsequent_events": {
            "events": []
        },
        
        # Section 12: Audit Committee Communication (ISA 260)
        "audit_committee_communications": {
            "text_ar": "...", "text_en": "..."
        },
        
        # Section 13: Auditor Signature Block (ISA 700 A163)
        "auditor_signature_block": {
            "text_ar": "...", "text_en": "...",
            "date": "2026-03-25T10:30:00Z",
            "system_version": "2.0",
        },
        
        # Metadata
        "generated_timestamp": "2026-03-25T10:30:00Z",
        "confidence_percentage": 95,
    },
    
    # Root Cause Analysis (ISA 315)
    "root_cause_analysis": [
        {
            "category": "documentation",
            "instances": 1,
            "root_cause_ar": "...", "root_cause_en": "..."
        },
        ...
    ],
    
    # Actions & Recommendations
    "actions_and_recommendations": [
        {
            "action": "Strengthen validation controls",
            "priority": "high",
            "timeline": "30 days"
        },
        ...
    ],
}
```

### ReportSerializer

**Location:** [apps/reports/serializers.py](apps/reports/serializers.py)

```python
from rest_framework import serializers
from .models import Report

class ReportSerializer(serializers.ModelSerializer):
    generated_by_name = serializers.CharField(source="generated_by.full_name", read_only=True)
    
    class Meta:
        model = Report
        fields = [
            "id",
            "title",
            "report_type",
            "language",
            "period_from",
            "period_to",
            "generated_by",
            "generated_by_name",
            "created_at"
        ]
        read_only_fields = ["id", "created_at"]
```

### ISA 700 Opinion Service

**Location:** [apps/reports/services/isa700_opinion_service.py](apps/reports/services/isa700_opinion_service.py) — 659 lines

```python
class ISA700OpinionService:
    """
    Generates ISA 700 compliant independent auditor's report with full audit evidence,
    risk assessments, and compliance statements.
    """

    OPINION_THRESHOLDS = {
        "unqualified": 90.0,   # compliance >= 90% AND no critical issues
        "qualified": 70.0,     # compliance >= 70% AND some non-pervasive issues
        "adverse": 0.0,        # compliance < 70% OR pervasive critical issues
        "disclaimer": -1.0,    # insufficient evidence
    }

    def generate_opinion(
        self,
        summary: Dict,
        validations: Dict,
        invoices: List,
        kams_list: List,
        compliance_engine: Dict,
        anomalies: Dict,
        scope_limitations: Optional[List[str]] = None,
    ) -> Dict:
        """
        Generate complete ISA 700 auditor opinion report section.
        
        Returns:
            Dict with 13 sections including:
            - opinion_paragraph, basis_for_opinion, risk_assessment_summary
            - audit_evidence_summary, compliance_statement, going_concern_assessment
            - audit_committee_communications, signature_block, metadata
        """
        # Determine opinion type based on thresholds
        opinion_type, opinion_basis = self._determine_opinion_type(summary, validations, invoices)
        
        # Generate all 13 sections...
        return {
            "management_responsibility": {...},
            "auditor_responsibility": {...},
            "scope_and_basis": {...},
            "risk_assessment_summary": {...},
            "compliance_statement": {...},
            "audit_evidence_summary": {...},
            "opinion_paragraph": {
                "opinion_type": opinion_type,
                "text_ar": "...",
                "text_en": "...",
            },
            "basis_for_opinion": {...},
            "key_audit_matters_summary": {...},
            "going_concern_assessment": {...},
            "subsequent_events": {...},
            "audit_committee_communications": {...},
            "auditor_signature_block": {...},
        }
```

### Report Generation Service Integration

**Location:** [apps/reports/services/invoice_audit_service.py](apps/reports/services/invoice_audit_service.py) — Lines 229-280

```python
class InvoiceAuditReportService:
    def build(
        self,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        language: str = "ar",
    ) -> Dict:
        """Build comprehensive audit report with all sections."""
        
        # ... [audit procedures omitted for brevity] ...
        
        # KAMs — ISA 701
        from apps.reports.services.kams_service import KAMsService
        kams = KAMsService(self.org, self.user).build(
            summary=summary,
            validations=validations,
            invoices=invoices,
            anomalies=anomalies,
            compliance=compliance_engine,
            language=language,
        )

        # ISA 700 Opinion — Comprehensive auditor opinion report
        from apps.reports.services.isa700_opinion_service import ISA700OpinionService
        isa700_service = ISA700OpinionService(self.org, self.user)
        isa700_opinion_report = isa700_service.generate_opinion(
            summary=summary,
            validations=validations,
            invoices=invoices,
            kams_list=kams.get("kams", []),
            compliance_engine=compliance_engine,
            anomalies=anomalies,
            scope_limitations=None,
        )

        # Build complete report
        report = {
            "report_header": {...},
            "summary": summary,
            "key_audit_matters": kams.get("kams", []),
            "isa700_auditor_opinion": isa700_opinion_report,  # ISA 700 comprehensive report
            "ias7_cashflow_classification": ias7_classifications,
            "ias7_cashflow_statement": ias7_cashflow_statement,
            "actions_and_recommendations": self._build_recommendations(summary, validations),
        }
        return _safe(report)
```

---

## 6️⃣ AUTHENTICATION URLS

**Location:** [apps/authentication/urls.py](apps/authentication/urls.py)

```python
urlpatterns = [
    # Basic auth
    path("register/", views.RegisterView.as_view(), name="register"),
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    
    # Email OTP (registration & email verification)
    path("otp/verify/", views.EmailOTPVerifyView.as_view(), name="otp-verify"),
    path("otp/resend/", views.EmailOTPResendView.as_view(), name="otp-resend"),
    
    # JWT tokens
    path("token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    
    # User profile
    path("me/", views.MeView.as_view(), name="me"),
    path("me/change-password/", views.ChangePasswordView.as_view(), name="change-password"),
    
    # User management (admin)
    path("users/", views.UserListView.as_view(), name="user-list"),
    path("users/<uuid:pk>/", views.UserDetailView.as_view(), name="user-detail"),
    path("users/<uuid:pk>/set-password/", views.SetPasswordView.as_view(), name="set-password"),
    
    # MFA (TOTP-based)
    path("mfa/setup/", views.MFASetupView.as_view(), name="mfa-setup"),
    path("mfa/verify/", views.MFAVerifyView.as_view(), name="mfa-verify"),
    path("mfa/disable/", views.MFADisableView.as_view(), name="mfa-disable"),
    
    # Google OAuth
    path("google/", views.GoogleLoginView.as_view(), name="google-login"),
]
```

---

## 📊 Implementation Patterns Summary

### Password Validation Flow
1. Email lookup via Django ORM
2. Account lock check (5 failed attempts → 30 min lock)
3. Password hash check via `authenticate()`
4. Failed attempt tracking with exponential backoff
5. Reset counters on success

### Email OTP Flow
1. Generate 6-digit code
2. Hash using Django's PBKDF2 hasher
3. Create EmailOTPVerification record with 10-min expiry
4. Send via HTML email template
5. Store challenge in session
6. User enters code → compare hashes
7. Enforce: 5 attempts max, 60-sec resend cooldown, 3 resends max

### JWT Token Issuance
- Uses `rest_framework_simplejwt.tokens.RefreshToken`
- Access token: ~5 minutes validity
- Refresh token: ~24 hours validity
- Stored in HttpOnly cookies (XSS protection)

### Report Generation Pipeline
1. Collect audit findings (InvoiceAuditReportService)
2. Validate against rules (compliance_engine)
3. Generate KAMs (ISA 701) — KAMsService
4. Generate ISA 700 opinion — ISA700OpinionService
5. Generate IAS 7 cash flow classification
6. Compile root cause analysis
7. Create recommendations
8. Return as JSON in Report.data field

### Missing: MFA Second Factor in LoginView
**Current Gap:** After password validation, should check `user.mfa_enabled` and:
- If true: Issue temporary token + require TOTP verification
- If false: Proceed to full token issuance
- This creates a two-step login: password → TOTP → access
