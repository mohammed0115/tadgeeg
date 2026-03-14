# OCR Pipeline Deployment & Operations Guide

**Date:** March 13, 2026  
**Version:** 1.0  
**Status:** Complete

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Docker Compose Setup](#docker-compose-setup)
3. [Environment Configuration](#environment-configuration)
4. [Celery Worker Management](#celery-worker-management)
5. [Monitoring & Health Checks](#monitoring--health-checks)
6. [Performance Tuning](#performance-tuning)
7. [Troubleshooting](#troubleshooting)
8. [Production Deployment](#production-deployment)

---

## Quick Start

### Local Development

```bash
# Clone and setup
cd /home/mohamed/Desktop/tadgeeg

# Copy environment template
cp .env.example .env

# Build and start all services
docker-compose up -d

# Run migrations
docker-compose exec web python manage.py migrate

# Create demo user (optional)
docker-compose exec web python manage.py create_demo_user

# Access application
# Web UI: http://localhost:8000
# API Docs: http://localhost:8000/api/docs/
# Flower (Celery Monitor): http://localhost:5555
# Health Check: http://localhost:8000/health/
```

### Without Docker

```bash
# Setup Python environment
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configure services
redis-server --port 6379 &           # Terminal 1: Redis
celery -A finai_backend worker -l info &  # Terminal 2: Default worker
celery -A finai_backend beat -l info &    # Terminal 3: Beat scheduler
python manage.py runserver              # Terminal 4: Web server

# Flower monitoring (Terminal 5, optional)
celery -A finai_backend flower
```

---

## Docker Compose Setup

### Service Architecture

```
┌─────────────────────────────────────────────────────┐
│                  FinAI OCR Pipeline                 │
├─────────────────────────────────────────────────────┤
│                                                     │
│  Web (Django)          Port 8000                    │
│  ├── API endpoints                                  │
│  ├── Document upload                                │
│  └── Dashboard                                      │
│                                                     │
│  Celery Workers        (4 services)                 │
│  ├── Default (4 concurrency)   → /documents/tasks  │
│  ├── Priority (2 concurrency)  → /priority         │
│  ├── Background (2 concurrency)→ /analytics        │
│  └── Beat Scheduler            → Periodic tasks    │
│                                                     │
│  Redis                 Port 6379                    │
│  ├── Celery broker                                  │
│  ├── Result backend                                 │
│  └── Cache store                                    │
│                                                     │
│  Flower               Port 5555                    │
│  └── Celery monitoring                              │
│                                                     │
└─────────────────────────────────────────────────────┘
```

### Starting Services

```bash
# Start all services
docker-compose up -d

# Start specific service
docker-compose up -d web
docker-compose up -d celery_default

# View logs
docker-compose logs -f web
docker-compose logs -f celery_default
docker-compose logs -f flower

# Stop services
docker-compose down

# Remove volumes (clean slate)
docker-compose down -v
```

---

## Environment Configuration

### Required Environment Variables

Create `.env` file in project root:

```env
# Django
DEBUG=False
SECRET_KEY=your-secret-key-here
ALLOWED_HOSTS=localhost,127.0.0.1,yourdomain.com

# Database (if using separate DB)
DATABASE_URL=postgresql://user:password@localhost:5432/finai_db

# Redis/Celery
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/0

# OpenAI GPT-4o Vision
OPENAI_API_KEY=sk-proj-xxxxx
OPENAI_MODEL=gpt-4o-2024-08-06
OPENAI_MAX_TOKENS=4096

# Tesseract OCR
TESSERACT_CMD=/usr/bin/tesseract
TESSERACT_LANGUAGES=ara+eng

# File Upload
MAX_UPLOAD_SIZE_MB=50
ALLOWED_UPLOAD_EXTENSIONS=.pdf,.jpg,.jpeg,.png,.tiff,.xlsx,.csv

# Email
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-password
EMAIL_USE_TLS=True

# Google OAuth (optional)
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com

# Site Configuration
SITE_URL=http://localhost:8000
```

### Configuration Validation

```bash
# Check environment
docker-compose exec web python -c "from django.conf import settings; print(settings.OPENAI_API_KEY[:20])"

# Test Redis connection
docker-compose exec redis redis-cli ping

# Test Tesseract
docker-compose exec web tesseract --version
```

---

## Celery Worker Management

### Worker Roles

| Worker | Queue | Concurrency | Purpose |
|--------|-------|-------------|---------|
| Default | default | 4 | Document OCR processing |
| Priority | priority | 2 | High-priority documents |
| Background | background | 2 | Analytics, reports, anomaly detection |
| Beat | - | N/A | Scheduled tasks (nightly scan, weekly reports) |

### Scaling Workers

```bash
# Increase default worker concurrency
docker-compose exec celery_default celery -A finai_backend worker \
  --loglevel=info --concurrency=8 --queues=default

# Add extra priority workers
docker-compose run -d celery_priority bash -c \
  "celery -A finai_backend worker --concurrency=4 --queues=priority --hostname=worker-priority-2"

# Monitor active workers
docker-compose exec redis redis-cli
> celery (to get Celery-related info)

# Or use Flower UI: http://localhost:5555
```

### Task Monitoring

```bash
# View active tasks
docker-compose exec web python -c "
from celery.app.control import Inspect
from finai_backend.celery import app
insp = Inspect(app=app)
import json
print(json.dumps(insp.active(), indent=2, default=str))
"

# Check task stats
docker-compose exec web python -c "
from celery.app.control import Inspect
from finai_backend.celery import app
insp = Inspect(app=app)
import json
print(json.dumps(insp.stats(), indent=2, default=str))
"

# Revoke a specific task
celery -A finai_backend revoke <task-id> --terminate
```

### Scheduled Tasks

Configured in `finai_backend/celery.py`:

```
- nightly-anomaly-scan: Daily at 2 AM
  → Detect transaction anomalies
  
- weekly-kpi-report: Mondays at 6 AM
  → Generate organizational KPI reports
  
- weekly-summary: Mondays at 9 AM
  → Send weekly summary emails
```

Modify via Django admin or edit `celery.py` → restart Beat scheduler.

---

## Monitoring & Health Checks

### Health Check Endpoints

**Basic Health:**
```bash
curl http://localhost:8000/health/
# Response:
{
  "status": "healthy",
  "timestamp": "2026-03-13T04:31:00Z",
  "components": {
    "redis": {"status": "healthy", "response_time_ms": 2.5},
    "database": {"status": "healthy", "response_time_ms": 5.1},
    "tesseract": {"status": "healthy", "message": "Tesseract 5.0 ready"},
    "stuck_documents": {"status": "healthy", "message": "No stuck documents"},
    "openai_api": {"status": "healthy", "message": "Model gpt-4o available"},
    "celery_workers": {"status": "healthy", "message": "8 workers active"},
    "processing_rate": {"status": "healthy", "message": "98.5% success rate (1h)"}
  }
}
```

**Quick Status (lightweight):**
```bash
curl http://localhost:8000/health/status/
# Response:
{
  "status": "healthy",
  "timestamp": "2026-03-13T04:31:00Z",
  "critical_components": {
    "redis": "healthy",
    "database": "healthy",
    "tesseract": "healthy"
  }
}
```

**With Heavy Checks:**
```bash
curl "http://localhost:8000/health/?heavy=true"
# Includes API connectivity, worker status, processing statistics
```

### Monitoring Tools

**Flower (Celery Monitor):** http://localhost:5555
- Active tasks
- Worker status
- Task history
- Performance graphs
- Task routing visualization

**Logs:**
```bash
# View real-time logs
docker-compose logs -f celery_default
docker-compose logs -f web

# Filter by service
docker-compose logs celery_default | grep ERROR

# Export logs
docker-compose logs celery_default > celery.log
docker-compose logs web > web.log
```

**Redis CLI:**
```bash
docker-compose exec redis redis-cli
> MONITOR              # Watch all commands
> CLIENT LIST          # Connected clients
> INFO server          # Server statistics
> DBSIZE               # Total keys
> KEYS "*"             # List all keys
> GET ocr_pipeline_health  # Get cached health
```

---

## Performance Tuning

### Worker Configuration

**For High Throughput (many documents):**
```bash
# Dockerfile: Increase prefetch and concurrency
-command: celery -A finai_backend worker \
+command: celery -A finai_backend worker \
  --loglevel=info \
  --concurrency=8 \           # Increase concurrency
  --prefetch-multiplier=4 \   # More tasks per worker
  --max-tasks-per-child=100   # Restart workers more frequently
```

**For Stability (fewer resources):**
```bash
-command: celery -A finai_backend worker \
+command: celery -A finai_backend worker \
  --loglevel=info \
  --concurrency=2 \           # Reduce concurrency
  --prefetch-multiplier=1 \   # One task at a time
  --max-tasks-per-child=1000  # Workers live longer
```

### Redis Optimization

```bash
# In docker-compose.yml for redis service:
command: redis-server --maxmemory 512mb --maxmemory-policy allkeys-lru

# In .env:
Redis settings can be tuned via environment
```

### Database Query Optimization

The OCR pipeline uses:
- `select_related()` for foreign keys
- `prefetch_related()` for reverse relations
- `only()` to select specific fields

Verify in `core/services/optimization.py:QueryOptimizer`

### Batch Processing

Process multiple documents efficiently:

```python
from core.services.optimization import BatchProcessor

processor = BatchProcessor(batch_size=10, use_priority_queue=True)
result = processor.process_document_batch([doc_id1, doc_id2, doc_id3...])
# Automatically routes every 3rd document to priority queue
```

### Caching Strategy

```python
from core.services.optimization import CacheManager

# Cache OCR results for 1 hour
CacheManager.cache_ocr_result(doc_id, result, timeout=3600)

# Retrieve from cache
result = CacheManager.get_ocr_result(doc_id)

# Clear cache when document updated
CacheManager.invalidate_document_cache(doc_id)
```

---

## Troubleshooting

### Common Issues

**Issue: Tesseract not found**
```bash
# Install in container
docker-compose exec web apt-get update && apt-get install tesseract-ocr

# Or verify in Dockerfile:
RUN apt-get install -y tesseract-ocr tesseract-ocr-ara
```

**Issue: OpenAI API timeout**
```bash
# Check timeout setting in .env
OPENAI_TIMEOUT_SECONDS=30

# View error logs
docker-compose logs web | grep OpenAI
```

**Issue: Celery tasks not processing**
```bash
# Verify Redis connection
docker-compose exec redis redis-cli ping

# Check if workers are running
docker-compose ps | grep celery

# Check worker logs
docker-compose logs celery_default | tail -50

# Try restarting workers
docker-compose restart celery_default celery_priority celery_background
```

**Issue: Memory usage growing**
```bash
# Check container memory
docker stats

# Reduce worker concurrency in docker-compose.yml
# Or enable max-tasks-per-child to restart workers

# Clear old cache entries
docker-compose exec redis redis-cli FLUSHDB
```

**Issue: Stuck documents in PROCESSING status**
```bash
# Find stuck documents (>30 min old)
docker-compose exec web python -c "
from apps.documents.models import Document
from django.utils import timezone
from datetime import timedelta
stuck = Document.objects.filter(
    processing_status='processing',
    updated_at__lt=timezone.now()-timedelta(minutes=30)
)
print(f'Stuck: {stuck.count()} documents')
for doc in stuck:
    print(f'- {doc.id}: {doc.original_filename}')
"

# Requeue stuck documents
docker-compose exec web python -c "
from apps.documents.models import Document
from django.utils import timezone
from datetime import timedelta
stuck = Document.objects.filter(
    processing_status='processing',
    updated_at__lt=timezone.now()-timedelta(minutes=30)
)
stuck.update(processing_status='pending')
print(f'Requeued {stuck.count()} documents')
"
```

### Debug Mode

Enable detailed logging:

```bash
# In .env
DEBUG=True
LOG_LEVEL=DEBUG

# View debug logs
docker-compose logs -f web | grep DEBUG
docker-compose logs -f celery_default | grep DEBUG
```

---

## Production Deployment

### Pre-deployment Checklist

- [ ] All environment variables configured (.env)
- [ ] Redis persistence enabled (appendonly yes)
- [ ] Database backups configured
- [ ] OpenAI API key valid and quotas sufficient
- [ ] Tesseract + language packs installed
- [ ] Email service configured and tested
- [ ] SSL/HTTPS certificates ready
- [ ] Worker resource limits set
- [ ] Monitoring dashboards accessible
- [ ] Backup and disaster recovery plan

### Kubernetes Deployment

Example deployment manifests:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: finai-web
spec:
  replicas: 2
  template:
    spec:
      containers:
      - name: web
        image: finai:latest
        ports:
        - containerPort: 8000
        livenessProbe:
          httpGet:
            path: /health/
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 30
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: finai-worker
spec:
  replicas: 3
  template:
    spec:
      containers:
      - name: worker
        image: finai:latest
        command: ["celery", "-A", "finai_backend", "worker"]
        resources:
          requests:
            memory: "512Mi"
            cpu: "500m"
          limits:
            memory: "1Gi"
            cpu: "1000m"
```

### Load Balancing

Use reverse proxy (nginx/HAProxy):

```nginx
upstream finai_backend {
    server web:8000;
    server web2:8000;
    server web3:8000;
}

server {
    listen 80;
    server_name api.finai.sa;
    
    location /api/ {
        proxy_pass http://finai_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Monitoring & Alerting

Recommend:
- Prometheus for metrics
- Grafana for dashboards
- AlertManager for alerts
- ELK stack for log aggregation

---

**Last Updated:** March 13, 2026  
**Status:** Production Ready ✅
