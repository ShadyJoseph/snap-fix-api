FROM python:3.12-slim

WORKDIR /app

# System dependencies for Postgres + PostGIS
RUN apt-get update && apt-get install -y \
    libpq-dev gcc \
    binutils libproj-dev gdal-bin \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

# Collect static files
RUN SECRET_KEY=dummy DEBUG=False python manage.py collectstatic --noinput

# Expose default port (Railway will override with $PORT)
EXPOSE 8000

# Don't run migrations or superuser here; handled in Railway releaseCommand
CMD ["gunicorn", "config.wsgi:application"]