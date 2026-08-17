FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    pkg-config \
    gettext \
    default-libmysqlclient-dev \
    tesseract-ocr \
    tesseract-ocr-ara \
    tesseract-ocr-eng \
    libgl1 \
    libglib2.0-0 \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    shared-mime-info \
    fonts-dejavu-core \
    fonts-noto-core \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.lock.txt ./

RUN python -m pip install --upgrade pip setuptools wheel && \
    pip install --require-hashes -r requirements.lock.txt

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

COPY . .

# private_media belongs in this list for the same reason the others do: Docker
# populates a NEW named volume from the image path it is mounted over, including
# ownership. Create it here owned by www-data and a fresh private_* volume
# inherits that. Omit it — as the first version of this change did — and Docker
# creates the mountpoint owned by root, the container runs as www-data, and
# Django's PARTNER_DOCS_ROOT.mkdir() raises PermissionError at import. The
# entrypoint's database-wait catches every exception, so that surfaced as
# "Database unavailable: Permission denied" and looked like a database fault.
RUN mkdir -p /app/staticfiles /app/media /app/logs /app/private_media /var/www && \
    chown -R www-data:www-data /app /entrypoint.sh /var/www

USER www-data

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]

CMD ["gunicorn", "finai_backend.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-"]
