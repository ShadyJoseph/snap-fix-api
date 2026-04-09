FROM python:3.12-slim

WORKDIR /app

# Install system dependencies (Postgres + GIS)
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

# Do NOT run migrations or superuser here
CMD ["gunicorn", "config.wsgi:application"]