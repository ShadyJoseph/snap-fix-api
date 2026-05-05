FROM python:3.12-slim

# Prevent Python from writing .pyc files and keep logs snappy
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies for Postgres + PostGIS
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    binutils \
    libproj-dev \
    gdal-bin \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the code
COPY . .

RUN mkdir -p /app/media /app/staticfiles

EXPOSE 8080

# collectstatic runs at startup (after volumes are mounted) so Railway
# volume mounts don't silently shadow files baked into the image at build time.
CMD ["sh", "-c", "python manage.py collectstatic --noinput && python manage.py migrate --noinput && gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8080} --workers ${WEB_CONCURRENCY:-2} --timeout 120 --log-level info --access-logfile - --error-logfile -"]