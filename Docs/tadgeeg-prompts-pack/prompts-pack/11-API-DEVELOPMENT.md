# 🔌 11 — تطوير API (Django REST Framework)

> Prompts لتطوير الـ API endpoints و drf-spectacular

---

## 🎯 Prompt 11.1 — بناء API Endpoint جديد

```
في مشروع Tadgeeg AI، أحتاج إنشاء API endpoint جديد:

# المثال: Endpoint لإحصائيات المستخدم

## المطلوب:

### 1. الـ Serializer:
```python
# apps/analytics/serializers.py
from rest_framework import serializers

class UserStatsSerializer(serializers.Serializer):
    total_invoices = serializers.IntegerField()
    invoices_this_month = serializers.IntegerField()
    pending_review = serializers.IntegerField()
    accuracy_rate = serializers.FloatField()
    risk_distribution = serializers.DictField()
    top_vendors = serializers.ListField()
    timeline = serializers.ListField()

class InvoiceListSerializer(serializers.ModelSerializer):
    vendor_name = serializers.CharField(source='vendor.name', read_only=True)
    risk_color = serializers.SerializerMethodField()
    
    class Meta:
        model = Invoice
        fields = [
            'id', 'invoice_number', 'vendor_name', 'invoice_date',
            'total_amount', 'status', 'risk_level', 'risk_color',
            'audit_score', 'created_at',
        ]
    
    def get_risk_color(self, obj):
        colors = {
            'low': 'green',
            'medium': 'yellow',
            'high': 'orange',
            'critical': 'red',
        }
        return colors.get(obj.risk_level, 'gray')
```

### 2. الـ ViewSet:
```python
# apps/analytics/views.py
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiParameter
from .serializers import UserStatsSerializer, InvoiceListSerializer

class AnalyticsViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]
    
    @extend_schema(
        summary="إحصائيات المستخدم",
        description="إحصائيات شاملة للمستخدم الحالي",
        responses={200: UserStatsSerializer},
        tags=['Analytics'],
    )
    @action(detail=False, methods=['get'])
    def my_stats(self, request):
        org = request.user.organization
        invoices = Invoice.objects.filter(organization=org)
        
        data = {
            'total_invoices': invoices.count(),
            'invoices_this_month': invoices.filter(
                created_at__gte=timezone.now().replace(day=1)
            ).count(),
            'pending_review': invoices.filter(status='pending_review').count(),
            'accuracy_rate': calc_accuracy(invoices),
            'risk_distribution': calc_risk_distribution(invoices),
            'top_vendors': get_top_vendors(invoices, limit=5),
            'timeline': get_timeline_data(invoices, days=30),
        }
        
        serializer = UserStatsSerializer(data)
        return Response(serializer.data)
    
    @extend_schema(
        summary="قائمة الفواتير",
        parameters=[
            OpenApiParameter('status', str, OpenApiParameter.QUERY),
            OpenApiParameter('risk', str, OpenApiParameter.QUERY),
            OpenApiParameter('date_from', str, OpenApiParameter.QUERY),
            OpenApiParameter('date_to', str, OpenApiParameter.QUERY),
        ],
        responses={200: InvoiceListSerializer(many=True)},
    )
    @action(detail=False, methods=['get'])
    def invoices(self, request):
        qs = Invoice.objects.filter(organization=request.user.organization)
        
        # Apply filters
        if status := request.query_params.get('status'):
            qs = qs.filter(status=status)
        if risk := request.query_params.get('risk'):
            qs = qs.filter(risk_level=risk)
        # ... etc
        
        # Pagination
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = InvoiceListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = InvoiceListSerializer(qs, many=True)
        return Response(serializer.data)
```

### 3. الـ URL:
```python
# apps/analytics/urls.py
from rest_framework.routers import DefaultRouter
from .views import AnalyticsViewSet

router = DefaultRouter()
router.register('analytics', AnalyticsViewSet, basename='analytics')

urlpatterns = router.urls
```

### 4. الـ Test:
```python
# tests/test_api_endpoints.py
import pytest
from rest_framework.test import APIClient

@pytest.mark.django_db
def test_my_stats_endpoint(authenticated_user):
    client = APIClient()
    client.force_authenticate(user=authenticated_user)
    
    response = client.get('/api/v1/analytics/my_stats/')
    
    assert response.status_code == 200
    assert 'total_invoices' in response.data
    assert 'risk_distribution' in response.data

@pytest.mark.django_db
def test_invoices_filtered(authenticated_user):
    client = APIClient()
    client.force_authenticate(user=authenticated_user)
    
    InvoiceFactory(organization=authenticated_user.organization, status='pending')
    InvoiceFactory(organization=authenticated_user.organization, status='approved')
    
    response = client.get('/api/v1/analytics/invoices/?status=pending')
    
    assert response.status_code == 200
    assert len(response.data['results']) == 1
```

# نقاط مهمة:
1. **Multi-tenant**: دائماً فلتر بـ `organization=request.user.organization`
2. **Pagination**: استخدم DRF pagination
3. **Permissions**: استخدم `IsAuthenticated` على الأقل
4. **Documentation**: استخدم `@extend_schema` لـ Swagger
5. **Validation**: استخدم Serializers للتحقق
6. **Caching**: استخدم `@cache_page` للـ queries الثقيلة
7. **Rate Limiting**: استخدم throttling

أعطني الكود الكامل + tests.
```

---

## 🎯 Prompt 11.2 — JWT Authentication API

```
في مشروع Tadgeeg AI، أحتاج JWT auth APIs:

# المطلوب:

## Endpoints:
- POST /api/v1/auth/login/ → access + refresh tokens
- POST /api/v1/auth/refresh/ → new access token
- POST /api/v1/auth/logout/ → blacklist refresh token
- POST /api/v1/auth/register/ → create user + send verification
- POST /api/v1/auth/verify-email/ → verify email with token
- POST /api/v1/auth/forgot-password/ → send reset link
- POST /api/v1/auth/reset-password/ → set new password
- GET /api/v1/auth/me/ → current user info
- POST /api/v1/auth/mfa/setup/ → start MFA setup
- POST /api/v1/auth/mfa/verify/ → verify MFA code
- POST /api/v1/auth/mfa/disable/ → disable MFA

## Implementation:

```python
# apps/authentication/views.py
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.tokens import RefreshToken
from drf_spectacular.utils import extend_schema

class LoginView(TokenObtainPairView):
    """
    POST /api/v1/auth/login/
    
    Body: { email, password, mfa_code? }
    Returns: { access, refresh, user }
    """
    
    @extend_schema(
        request=LoginSerializer,
        responses={200: TokenResponseSerializer},
    )
    def post(self, request, *args, **kwargs):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        user = authenticate(
            email=serializer.validated_data['email'],
            password=serializer.validated_data['password']
        )
        
        if not user:
            return Response({'error': 'Invalid credentials'}, status=401)
        
        # MFA Check
        if user.mfa_enabled:
            mfa_code = request.data.get('mfa_code')
            if not mfa_code:
                return Response({
                    'mfa_required': True,
                    'mfa_token': generate_mfa_token(user),
                }, status=200)
            
            if not verify_mfa(user, mfa_code):
                return Response({'error': 'Invalid MFA code'}, status=401)
        
        # Generate tokens
        refresh = RefreshToken.for_user(user)
        
        # Log login
        LoginAttempt.objects.create(
            user=user,
            email=user.email,
            ip_address=get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
            success=True,
            mfa_used=user.mfa_enabled,
        )
        
        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'user': UserSerializer(user).data,
        })


class MeView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        return Response(UserSerializer(request.user).data)
    
    def patch(self, request):
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
```

# Settings JWT:
```python
# settings.py
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=15),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=30),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'AUTH_HEADER_TYPES': ('Bearer',),
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
    'AUTH_TOKEN_CLASSES': ('rest_framework_simplejwt.tokens.AccessToken',),
}

# Token blacklist
INSTALLED_APPS += ['rest_framework_simplejwt.token_blacklist']
```

أعطني:
1. الـ Views (Login, Logout, Register, etc.)
2. الـ Serializers
3. الـ URLs
4. الـ Tests الشاملة
5. توثيق Swagger
```

---

## 🎯 Prompt 11.3 — Rate Limiting & Throttling

```
في مشروع Tadgeeg AI، أحتاج تطبيق Rate Limiting شامل:

# المطلوب:

## 1. Throttle Classes:
```python
# core/throttles.py
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle, ScopedRateThrottle

class StrictAnonThrottle(AnonRateThrottle):
    rate = '10/min'

class LoginThrottle(ScopedRateThrottle):
    scope = 'login'
    # rate set in settings: '5/min'

class RegisterThrottle(ScopedRateThrottle):
    scope = 'register'
    # rate: '3/hour'

class APIKeyThrottle(UserRateThrottle):
    """Different rates based on subscription plan"""
    
    def get_rate(self):
        request = self.request
        if not request.user.is_authenticated:
            return '100/hour'
        
        org = request.user.organization
        plan = org.subscription.plan if hasattr(org, 'subscription') else 'free'
        
        rates = {
            'free': '100/hour',
            'starter': '1000/hour',
            'professional': '10000/hour',
            'enterprise': '100000/hour',
        }
        return rates.get(plan, '100/hour')
```

## 2. Settings:
```python
# settings.py
REST_FRAMEWORK = {
    # ... other settings
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/hour',
        'user': '1000/hour',
        'login': '5/min',
        'register': '3/hour',
        'password_reset': '3/hour',
        'mfa_verify': '5/min',
        'upload': '50/hour',
    }
}
```

## 3. Custom IP-based Rate Limiter (Redis):
```python
# core/rate_limiter.py
import redis
from django.conf import settings
from django.http import HttpResponse

r = redis.from_url(settings.REDIS_URL)

class IPRateLimiter:
    def __init__(self, key_prefix, limit, window):
        self.key_prefix = key_prefix
        self.limit = limit
        self.window = window  # seconds
    
    def is_allowed(self, ip):
        key = f"rl:{self.key_prefix}:{ip}"
        current = r.incr(key)
        if current == 1:
            r.expire(key, self.window)
        return current <= self.limit, current

# Middleware
class IPRateLimitMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.limiter = IPRateLimiter('global', limit=1000, window=60)
    
    def __call__(self, request):
        ip = self.get_client_ip(request)
        allowed, count = self.limiter.is_allowed(ip)
        
        if not allowed:
            response = HttpResponse('Rate limit exceeded', status=429)
            response['Retry-After'] = '60'
            response['X-RateLimit-Limit'] = str(self.limiter.limit)
            response['X-RateLimit-Remaining'] = '0'
            return response
        
        response = self.get_response(request)
        response['X-RateLimit-Limit'] = str(self.limiter.limit)
        response['X-RateLimit-Remaining'] = str(self.limiter.limit - count)
        return response
    
    def get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR')
```

## 4. على الـ Views:
```python
class LoginView(TokenObtainPairView):
    throttle_classes = [LoginThrottle]
    throttle_scope = 'login'

class FileUploadView(APIView):
    throttle_classes = [UserRateThrottle]
    throttle_scope = 'upload'
```

أعطني:
1. الـ Throttle classes
2. الـ Middleware
3. الـ Settings
4. Tests للـ rate limiting
5. انظر `Docs/RATE_LIMITING_IMPLEMENTATION.md` للمرجع
```

---

## 🎯 Prompt 11.4 — drf-spectacular Documentation

```
في مشروع Tadgeeg AI، يستخدم drf-spectacular للتوثيق التلقائي.

# المطلوب: تحسين توثيق API:

## 1. Settings:
```python
# settings.py
SPECTACULAR_SETTINGS = {
    'TITLE': 'Tadgeeg AI API',
    'DESCRIPTION': """
    منصة الذكاء الاصطناعي للتدقيق المالي
    AI Financial Auditing Platform
    
    ## Authentication
    استخدم Bearer token في الـ Authorization header:
    `Authorization: Bearer <your_token>`
    
    احصل على token من `/api/v1/auth/login/`
    """,
    'VERSION': '1.0.0',
    'CONTACT': {
        'name': 'Tadgeeg Support',
        'email': 'support@tadgeeg.com',
        'url': 'https://tadgeeg.com/support',
    },
    'LICENSE': {
        'name': 'Proprietary',
    },
    'SERVERS': [
        {'url': 'http://localhost:8000', 'description': 'Local'},
        {'url': 'https://api.tadgeeg.com', 'description': 'Production'},
    ],
    'TAGS': [
        {'name': 'Authentication', 'description': 'Login, register, MFA'},
        {'name': 'Invoices', 'description': 'Invoice management'},
        {'name': 'Documents', 'description': 'Other documents'},
        {'name': 'Reports', 'description': 'Reports generation'},
        {'name': 'Compliance', 'description': 'ZATCA & compliance'},
        {'name': 'Analytics', 'description': 'Statistics & analytics'},
    ],
    'COMPONENT_SPLIT_REQUEST': True,
    'SCHEMA_PATH_PREFIX': '/api/v1',
    'POSTPROCESSING_HOOKS': [
        'drf_spectacular.hooks.postprocess_schema_enums',
    ],
    'SWAGGER_UI_SETTINGS': {
        'deepLinking': True,
        'persistAuthorization': True,
        'displayOperationId': False,
    },
}
```

## 2. مثال على Schema decorations:
```python
# apps/invoices/views.py
from drf_spectacular.utils import (
    extend_schema, extend_schema_view,
    OpenApiParameter, OpenApiExample, OpenApiResponse
)

@extend_schema_view(
    list=extend_schema(
        summary='قائمة الفواتير',
        description='احصل على قائمة الفواتير مع فلاتر متعددة',
        parameters=[
            OpenApiParameter('status', str, description='Filter by status', 
                           enum=['pending', 'processed', 'approved', 'rejected']),
            OpenApiParameter('risk', str, description='Filter by risk level',
                           enum=['low', 'medium', 'high', 'critical']),
            OpenApiParameter('date_from', str, description='Start date (YYYY-MM-DD)'),
            OpenApiParameter('date_to', str, description='End date (YYYY-MM-DD)'),
        ],
        examples=[
            OpenApiExample(
                'مثال: فواتير عالية المخاطر',
                value={'status': 'processed', 'risk': 'high'},
            ),
        ],
        tags=['Invoices'],
    ),
    create=extend_schema(
        summary='إنشاء فاتورة جديدة',
        description='ارفع ملف فاتورة لتحليله',
        request={
            'multipart/form-data': {
                'type': 'object',
                'properties': {
                    'file': {'type': 'string', 'format': 'binary'},
                    'audit_session_id': {'type': 'string', 'format': 'uuid'},
                },
                'required': ['file'],
            }
        },
        responses={
            201: InvoiceSerializer,
            400: OpenApiResponse(description='Invalid file or data'),
            413: OpenApiResponse(description='File too large'),
        },
    ),
)
class InvoiceViewSet(viewsets.ModelViewSet):
    serializer_class = InvoiceSerializer
    # ...
```

## 3. URLs:
```python
# urls.py
from drf_spectacular.views import (
    SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView
)

urlpatterns += [
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='docs'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
]
```

## 4. Custom Schema Generator:
لإضافة معلومات إضافية مثل rate limits:
```python
# core/schema.py
from drf_spectacular.openapi import AutoSchema

class CustomAutoSchema(AutoSchema):
    def get_operation(self, path, path_regex, path_prefix, method, registry):
        operation = super().get_operation(path, path_regex, path_prefix, method, registry)
        
        # Add rate limit info
        view = self.view
        if hasattr(view, 'throttle_scope'):
            scope = view.throttle_scope
            rates = settings.REST_FRAMEWORK.get('DEFAULT_THROTTLE_RATES', {})
            rate = rates.get(scope, 'N/A')
            operation['description'] = (operation.get('description') or '') + f"\n\n**Rate Limit:** {rate}"
        
        return operation
```

أعطني:
1. الـ settings الكاملة
2. أمثلة على decorations لكل ViewSet
3. الـ Custom schema
4. تحسينات للـ Swagger UI
```

---

## ✅ Checklist

- [ ] API endpoints موثّقة بالكامل
- [ ] JWT authentication يعمل
- [ ] MFA support في الـ login API
- [ ] Rate limiting مطبّق على endpoints حساسة
- [ ] Swagger UI متاح على /api/docs/
- [ ] ReDoc متاح على /api/redoc/
- [ ] OpenAPI schema على /api/schema/
- [ ] Tests شاملة في `test_api_endpoints.py`
- [ ] Permissions صحيحة (multi-tenant)
- [ ] Pagination مطبّق

---

**📌 انتقل لـ `12-DJANGO-MODELS.md`**
