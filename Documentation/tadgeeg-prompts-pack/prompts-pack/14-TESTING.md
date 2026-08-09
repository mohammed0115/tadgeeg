# 🧪 14 — الاختبارات (Testing with pytest)

> Prompts لكتابة وصيانة الاختبارات في `tests/`

---

## 🎯 Prompt 14.1 — كتابة Tests للـ Models

```
في مشروع Tadgeeg AI، أحتاج tests شاملة للـ models:

# المطلوب:

## 1. الـ Factories:
```python
# tests/factories.py
import factory
from factory.django import DjangoModelFactory
from faker import Faker

fake = Faker(['ar_SA', 'en_US'])

class OrganizationFactory(DjangoModelFactory):
    class Meta:
        model = 'authentication.Organization'
    
    name = factory.Faker('company')
    name_ar = factory.LazyAttribute(lambda o: f"شركة {fake.last_name()}")
    vat_number = factory.LazyFunction(lambda: f"3{fake.numerify('############')}3")
    is_active = True

class UserFactory(DjangoModelFactory):
    class Meta:
        model = 'authentication.User'
    
    email = factory.Faker('email')
    first_name = factory.Faker('first_name')
    last_name = factory.Faker('last_name')
    organization = factory.SubFactory(OrganizationFactory)
    is_active = True
    
    @factory.post_generation
    def password(self, create, extracted, **kwargs):
        password = extracted or 'TestPass123!'
        self.set_password(password)
        self.save()

class InvoiceFactory(DjangoModelFactory):
    class Meta:
        model = 'invoices.Invoice'
    
    organization = factory.SubFactory(OrganizationFactory)
    uploaded_by = factory.SubFactory(UserFactory, organization=factory.SelfAttribute('..organization'))
    invoice_number = factory.Sequence(lambda n: f'INV-{n:06d}')
    vendor_name = factory.Faker('company')
    vendor_vat_number = factory.LazyFunction(lambda: f"3{fake.numerify('############')}3")
    invoice_date = factory.Faker('date_this_year')
    subtotal = factory.LazyFunction(lambda: round(fake.random.uniform(100, 10000), 2))
    
    @factory.lazy_attribute
    def vat_amount(self):
        return round(float(self.subtotal) * 0.15, 2)
    
    @factory.lazy_attribute
    def total_amount(self):
        return round(float(self.subtotal) + float(self.vat_amount), 2)
    
    currency = 'SAR'
    status = 'pending'
```

## 2. Tests للـ Invoice Model:
```python
# tests/test_invoice_model.py
import pytest
from decimal import Decimal
from apps.invoices.models import Invoice
from tests.factories import InvoiceFactory, OrganizationFactory

@pytest.mark.django_db
class TestInvoiceModel:
    
    def test_create_invoice(self):
        invoice = InvoiceFactory()
        assert invoice.id is not None
        assert invoice.status == 'pending'
        assert invoice.total_amount > 0
    
    def test_vat_calculation_correct(self):
        invoice = InvoiceFactory(subtotal=Decimal('100.00'))
        assert invoice.vat_amount == Decimal('15.00')
        assert invoice.total_amount == Decimal('115.00')
    
    def test_soft_delete(self):
        invoice = InvoiceFactory()
        invoice_id = invoice.id
        invoice.delete()
        
        # Should not appear in normal query
        assert not Invoice.objects.filter(id=invoice_id).exists()
        
        # Should appear in all_objects
        assert Invoice.all_objects.filter(id=invoice_id).exists()
        
        # is_deleted should be True
        deleted_invoice = Invoice.all_objects.get(id=invoice_id)
        assert deleted_invoice.is_deleted is True
        assert deleted_invoice.deleted_at is not None
    
    def test_organization_isolation(self):
        org1 = OrganizationFactory()
        org2 = OrganizationFactory()
        
        InvoiceFactory(organization=org1)
        InvoiceFactory(organization=org2)
        
        # Each org sees only their own
        assert Invoice.objects.filter(organization=org1).count() == 1
        assert Invoice.objects.filter(organization=org2).count() == 1
    
    def test_status_choices(self):
        invoice = InvoiceFactory()
        valid_statuses = ['pending', 'processing', 'validated', 'flagged', 'approved', 'rejected']
        
        for status in valid_statuses:
            invoice.status = status
            invoice.save()
            assert invoice.status == status
    
    @pytest.mark.parametrize('subtotal,vat,total', [
        (Decimal('100.00'), Decimal('15.00'), Decimal('115.00')),
        (Decimal('1000.00'), Decimal('150.00'), Decimal('1150.00')),
        (Decimal('33.33'), Decimal('5.00'), Decimal('38.33')),
    ])
    def test_vat_calculations(self, subtotal, vat, total):
        invoice = InvoiceFactory(
            subtotal=subtotal,
            vat_amount=vat,
            total_amount=total
        )
        assert invoice.subtotal == subtotal
        assert invoice.total_amount == total
```

أعطني:
1. الـ factories الكاملة
2. Tests شاملة للـ Invoice model
3. Tests للـ Organization, User
4. Tests للـ relationships
```

---

## 🎯 Prompt 14.2 — Tests للـ API Endpoints

```
في مشروع Tadgeeg AI، أحتاج Tests شاملة للـ API:

# المطلوب:

## 1. Conftest:
```python
# tests/conftest.py
import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken
from tests.factories import UserFactory, OrganizationFactory, InvoiceFactory

@pytest.fixture
def api_client():
    return APIClient()

@pytest.fixture
def organization():
    return OrganizationFactory()

@pytest.fixture
def user(organization):
    return UserFactory(organization=organization)

@pytest.fixture
def admin_user(organization):
    return UserFactory(
        organization=organization,
        is_staff=True,
        is_superuser=True
    )

@pytest.fixture
def authenticated_client(api_client, user):
    """Client with JWT token"""
    refresh = RefreshToken.for_user(user)
    api_client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')
    return api_client

@pytest.fixture
def admin_client(api_client, admin_user):
    refresh = RefreshToken.for_user(admin_user)
    api_client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')
    return api_client

@pytest.fixture
def invoice(organization, user):
    return InvoiceFactory(organization=organization, uploaded_by=user)
```

## 2. Tests للـ Authentication API:
```python
# tests/test_auth_api.py
import pytest
from rest_framework import status

@pytest.mark.django_db
class TestLoginAPI:
    
    def test_login_success(self, api_client, user):
        response = api_client.post('/api/v1/auth/login/', {
            'email': user.email,
            'password': 'TestPass123!',
        })
        
        assert response.status_code == status.HTTP_200_OK
        assert 'access' in response.data
        assert 'refresh' in response.data
        assert response.data['user']['email'] == user.email
    
    def test_login_invalid_password(self, api_client, user):
        response = api_client.post('/api/v1/auth/login/', {
            'email': user.email,
            'password': 'WrongPassword',
        })
        
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
    
    def test_login_nonexistent_user(self, api_client):
        response = api_client.post('/api/v1/auth/login/', {
            'email': 'nobody@example.com',
            'password': 'somepassword',
        })
        
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
    
    def test_login_rate_limit(self, api_client, user):
        # 5 failed attempts in a minute should trigger rate limit
        for _ in range(5):
            api_client.post('/api/v1/auth/login/', {
                'email': user.email,
                'password': 'wrong',
            })
        
        response = api_client.post('/api/v1/auth/login/', {
            'email': user.email,
            'password': 'TestPass123!',
        })
        
        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    
    def test_login_with_mfa(self, api_client, user):
        # Enable MFA
        user.mfa_enabled = True
        user.mfa_secret = 'TESTSECRET'
        user.save()
        
        # First request without MFA code
        response = api_client.post('/api/v1/auth/login/', {
            'email': user.email,
            'password': 'TestPass123!',
        })
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data.get('mfa_required') is True

@pytest.mark.django_db
class TestProtectedEndpoints:
    
    def test_unauthenticated_request(self, api_client):
        response = api_client.get('/api/v1/auth/me/')
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
    
    def test_authenticated_request(self, authenticated_client, user):
        response = authenticated_client.get('/api/v1/auth/me/')
        assert response.status_code == status.HTTP_200_OK
        assert response.data['email'] == user.email
```

## 3. Tests للـ Multi-Tenant:
```python
# tests/test_multitenant_isolation.py
@pytest.mark.django_db
class TestMultiTenantIsolation:
    
    def test_user_only_sees_own_org_invoices(self, api_client):
        org1 = OrganizationFactory()
        org2 = OrganizationFactory()
        
        user1 = UserFactory(organization=org1)
        user2 = UserFactory(organization=org2)
        
        InvoiceFactory.create_batch(3, organization=org1)
        InvoiceFactory.create_batch(2, organization=org2)
        
        # Login as user1
        client1 = APIClient()
        client1.force_authenticate(user1)
        
        response = client1.get('/api/v1/invoices/')
        assert response.status_code == 200
        assert len(response.data['results']) == 3  # only org1 invoices
        
        # Login as user2
        client2 = APIClient()
        client2.force_authenticate(user2)
        
        response = client2.get('/api/v1/invoices/')
        assert len(response.data['results']) == 2
    
    def test_user_cant_access_other_org_invoice(self, api_client):
        org1 = OrganizationFactory()
        org2 = OrganizationFactory()
        
        invoice_org1 = InvoiceFactory(organization=org1)
        user_org2 = UserFactory(organization=org2)
        
        client = APIClient()
        client.force_authenticate(user_org2)
        
        response = client.get(f'/api/v1/invoices/{invoice_org1.id}/')
        assert response.status_code == status.HTTP_404_NOT_FOUND
```

أعطني tests شاملة للـ:
1. Authentication endpoints
2. Invoice CRUD
3. Multi-tenant isolation
4. Permissions
5. Rate limiting
```

---

## 🎯 Prompt 14.3 — Fix Failing Tests

```
في مشروع Tadgeeg AI، عندي tests فاشلة بعد التعديلات.

# الخطوات لتشخيص وإصلاح Tests:

## 1. شغّل الـ tests وحدد الفاشلة:
```bash
pytest tests/ -v --tb=short

# أو فقط ملف معين:
pytest tests/test_invoice_and_rules.py -v

# أو فقط test معين:
pytest tests/test_invoice_and_rules.py::test_invoice_creation -v

# مع coverage:
pytest --cov=apps --cov-report=html tests/
```

## 2. صنّف الأخطاء:
- ImportError → import محذوف أو مغيّر
- ObjectDoesNotExist → factory أو fixture محذوف
- AssertionError → السلوك تغيّر
- IntegrityError → constraint جديد
- AttributeError → method/field مغيّر

## 3. الإصلاحات الشائعة:

### فشل بسبب field جديد required:
```python
# قبل
invoice = Invoice.objects.create(
    organization=org,
    invoice_number='INV-001',
)

# بعد إضافة required field
invoice = Invoice.objects.create(
    organization=org,
    invoice_number='INV-001',
    uploaded_by=user,  # field جديد
)
```

### فشل بسبب تغيير URL:
```python
# قبل
response = client.get('/api/invoices/')

# بعد
response = client.get('/api/v1/invoices/')
```

### فشل بسبب تغيير serializer field:
```python
# قبل
assert response.data['amount'] == 100

# بعد - الحقل أصبح اسمه total_amount
assert response.data['total_amount'] == 100
```

## 4. مشاكل DB في Tests:
```python
# إذا فشلت بسبب unique constraint:
@pytest.mark.django_db(transaction=True)
def test_with_real_transactions():
    pass

# لتسريع tests:
@pytest.fixture(scope='session')
def django_db_setup(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        # Setup data once for all tests
        pass
```

## 5. مشاكل Celery في Tests:
```python
# settings/test.py
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
```

## 6. مشاكل OpenAI/External Services:
```python
# Mock external services
from unittest.mock import patch, MagicMock

@patch('apps.auditing.services.gpt_extractor.OpenAI')
def test_extraction(mock_openai):
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content='{"vendor_name": "Test"}'))]
    mock_openai.return_value.chat.completions.create.return_value = mock_response
    
    result = GPT4oVisionExtractor().extract('test.png')
    assert result['vendor_name'] == 'Test'
```

# المطلوب الآن:
أرفق رسائل الخطأ من pytest، وأنا سأعطيك:
1. تشخيص الخطأ
2. الإصلاح المقترح
3. الكود المعدّل
4. أي migration أو fixture محتاج
```

---

## 🎯 Prompt 14.4 — CI/CD Tests Pipeline

```
في مشروع Tadgeeg AI، أحتاج إعداد CI/CD لتشغيل الـ tests:

# المطلوب:

## 1. GitHub Actions:
```yaml
# .github/workflows/tests.yml
name: Tests

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    
    services:
      redis:
        image: redis:7
        ports: ['6379:6379']
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    
    strategy:
      matrix:
        python-version: ['3.11']
    
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
          cache: 'pip'
      
      - name: Install Tesseract
        run: |
          sudo apt-get update
          sudo apt-get install -y tesseract-ocr tesseract-ocr-ara tesseract-ocr-eng
      
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install -r requirements-test.txt
      
      - name: Set up environment
        run: |
          cp .env.example .env
          echo "DEBUG=True" >> .env
          echo "SECRET_KEY=test-key-only-for-ci" >> .env
          echo "REDIS_URL=redis://localhost:6379/0" >> .env
          echo "OPENAI_API_KEY=test-key" >> .env
      
      - name: Run migrations
        run: python manage.py migrate
      
      - name: Run tests
        run: |
          pytest tests/ -v --cov=apps --cov-report=xml --cov-report=term-missing
      
      - name: Upload coverage
        uses: codecov/codecov-action@v4
        with:
          files: ./coverage.xml
          fail_ci_if_error: false
      
      - name: Upload test results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: test-results
          path: |
            htmlcov/
            .pytest_cache/
  
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      
      - name: Install linters
        run: |
          pip install black ruff isort
      
      - name: Check formatting
        run: |
          black --check apps/ core/ tests/
          isort --check-only apps/ core/ tests/
      
      - name: Run linter
        run: ruff check apps/ core/ tests/
```

## 2. Pre-commit Hooks:
```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/psf/black
    rev: 24.10.0
    hooks:
      - id: black
        language_version: python3.11
  
  - repo: https://github.com/charliermarsh/ruff-pre-commit
    rev: v0.6.0
    hooks:
      - id: ruff
        args: [--fix]
  
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.5.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files
        args: ['--maxkb=500']
  
  - repo: local
    hooks:
      - id: pytest-fast
        name: Run fast tests
        entry: pytest tests/ -m "not slow" --tb=short
        language: system
        pass_filenames: false
```

## 3. pytest.ini:
```ini
[pytest]
DJANGO_SETTINGS_MODULE = finai_backend.settings
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = 
    --strict-markers
    --reuse-db
    --create-db
    -ra

markers =
    slow: slow tests
    integration: integration tests
    unit: unit tests
    api: API tests
    security: security tests

testpaths = tests
filterwarnings =
    ignore::DeprecationWarning
    ignore::PendingDeprecationWarning
```

أعطني:
1. الـ workflow files
2. pre-commit config
3. pytest configuration
4. coverage configuration
```

---

## ✅ Checklist

- [ ] جميع الـ tests الأساسية تنجح
- [ ] coverage > 70% للـ apps
- [ ] CI/CD يشتغل تلقائياً
- [ ] pre-commit hooks تعمل
- [ ] tests للـ multi-tenant isolation تنجح
- [ ] mocking للـ external services
- [ ] factories لكل model أساسي

---

**📌 انتقل لـ `15-DEPLOYMENT.md`**
