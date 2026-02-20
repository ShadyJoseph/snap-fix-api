FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN SECRET_KEY=dummy DEBUG=False python manage.py collectstatic --noinput

EXPOSE 8000

CMD sh -c "until python manage.py migrate --noinput; do echo 'Waiting for DB...'; sleep 2; done && python manage.py create_superuser && gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3"
