FROM python:3.12-slim

# Prevent Python from writing .pyc files and keep logs snappy
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies for Postgres and PostGIS
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

# Collect static files (Uses a dummy key for the build phase)
RUN SECRET_KEY=build-phase-dummy-key DEBUG=False python manage.py collectstatic --noinput

# Expose the default port (Railway overrides this with $PORT)
EXPOSE 8080

CMD ["sh", "-c", "echo \"=== PORT = ${PORT} ===\"; rm -f gunicorn.conf.py 2>/dev/null || true; exec gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8080} --workers 2 --timeout 120 --access-logfile - --error-logfile - --log-level debug --config /dev/null"]