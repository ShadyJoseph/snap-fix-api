# Deployment Guide

## Production Stack

```
Internet
    │
    ▼
Railway (cloud host)
    ├── web service          Gunicorn + Django (handles HTTP requests)
    ├── celery service       Celery worker (handles async tasks — FCM pushes)
    ├── PostgreSQL plugin    Primary database
    └── Redis plugin         Message broker (queue between web and celery)
```

---

## Services Explained

### web

The main Django application. Gunicorn spawns multiple worker processes, each capable of handling one HTTP request at a time. When a booking transition triggers a notification, the web worker writes the DB row (sync) then drops a message into Redis (non-blocking) and immediately returns the response to the client. It does **not** wait for Firebase.

### celery

A separate process that reads tasks off the Redis queue and executes them. Its only job right now is sending FCM pushes via `send_push_notification`. It runs independently of the web service — if it restarts or is briefly down, tasks sit in Redis and are processed when it comes back.

**Why not just do it in the web worker?**
Firebase API calls can take hundreds of milliseconds and can fail. Running them inside a Gunicorn worker blocks that worker for the duration and ties retries to the HTTP request lifecycle. Celery decouples the work: the web worker finishes fast and the push is delivered reliably in the background.

### Redis

Acts as the **message broker**: web writes task messages to it, celery reads and executes them. Also stores task result metadata. Railway injects `REDIS_URL` automatically when you add the Redis plugin — no manual wiring needed.

### PostgreSQL

Primary data store for everything: users, service requests, notifications, device tokens. Railway injects connection details automatically when you add the Postgres plugin.

---

## Celery Task: FCM Push

```python
# apps/notifications/tasks.py

@shared_task(bind=True, max_retries=3, acks_late=True, reject_on_worker_lost=True)
def send_push_notification(self, user_id, title, body, data):
    ...
```

| Setting | What it does |
|---|---|
| `max_retries=3` | Retry up to 3 times before giving up |
| `acks_late=True` | Task is only acknowledged (removed from queue) after it succeeds — if the worker crashes mid-task, the task is re-queued |
| `reject_on_worker_lost=True` | If the worker process dies unexpectedly, the task goes back to the queue instead of being lost |
| Retry countdown | 60s → 120s → 240s (exponential back-off) |

---

## Local Setup (Docker Compose)

```
docker-compose up
```

This starts:
- `db` — PostgreSQL 15
- `redis` — Redis 7 (Alpine)
- `web` — Django + Gunicorn (with migrations on startup)
- `celery` — Celery worker connected to the same Redis

The web and celery services share the same image and codebase. They differ only in their startup command.

### Environment variables (local)

Stored in `.env.dev`. Key ones:

| Variable | Example value | Notes |
|---|---|---|
| `SECRET_KEY` | `dev-secret-key` | Any string locally |
| `DEBUG` | `True` | Never True in prod |
| `DATABASE_URL` | `postgres://...` | Set by docker-compose |
| `REDIS_URL` | `redis://redis:6379/0` | `redis` is the Docker service name |
| `GOOGLE_APPLICATION_CREDENTIALS` | `./secrets/firebase-service-account.json` | Local path to the Firebase JSON file |

---

## Railway Production Setup

### 1. Add PostgreSQL

Railway dashboard → your project → **+ New** → **Database** → **PostgreSQL**.

Railway auto-injects `DATABASE_URL` into all services in the project.

### 2. Add Redis

Railway dashboard → your project → **+ New** → **Database** → **Redis**.

Railway auto-injects `REDIS_URL` into all services. The Django settings already read it:

```python
_REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
CELERY_BROKER_URL = _REDIS_URL
CELERY_RESULT_BACKEND = _REDIS_URL
```

### 3. Deploy the web service

Connect your GitHub repo. Railway detects the `Dockerfile` and builds automatically on every push.

Set these environment variables on the web service:

| Variable | Value |
|---|---|
| `SECRET_KEY` | A long random string (use `openssl rand -hex 32`) |
| `DEBUG` | `False` |
| `ALLOWED_HOSTS` | Your Railway domain, e.g. `snap-fix-api.up.railway.app` |
| `CSRF_TRUSTED_ORIGINS` | `https://snap-fix-api.up.railway.app` |
| `GOOGLE_APPLICATION_CREDENTIALS_JSON` | Full contents of `firebase-service-account.json` (paste the entire JSON) |

### 4. Deploy the Celery service

Create a second Railway service pointing at the **same GitHub repo**. Override the start command:

```
celery -A config worker --loglevel=info --concurrency=2
```

Set the **same environment variables** as the web service (it needs `REDIS_URL`, `DATABASE_URL`, `GOOGLE_APPLICATION_CREDENTIALS_JSON`, `SECRET_KEY`, etc.).

Railway auto-injects the database and Redis URLs into both services since they're in the same project.

### 5. Firebase credentials on Railway

You cannot mount files on Railway, so the Firebase service-account JSON is passed as an environment variable:

1. Open `secrets/firebase-service-account.json`, copy the entire contents.
2. Railway → web service → **Variables** → add:
   - Key: `GOOGLE_APPLICATION_CREDENTIALS_JSON`
   - Value: *(paste the full JSON)*
3. Repeat on the celery service.

The app handles this in `apps/notifications/apps.py`:

```python
def ready(self):
    cred_json = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    if cred_json:
        # Write to a temp file because firebase-admin requires a file path
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write(cred_json)
        firebase_admin.initialize_app(credentials.Certificate(f.name))
```

---

## Deploy Flow on Every Push

```
git push origin master
        │
        ▼
Railway detects change → builds Docker image
        │
        ▼
web service starts:
  python manage.py migrate
  python manage.py create_superuser  (skips if already exists)
  gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 2
        │
        ▼
celery service starts (separate):
  celery -A config worker --loglevel=info --concurrency=2
        │
        ▼
App is live. Web handles HTTP. Celery handles async FCM pushes.
```

---

## Dockerfile Notes

```dockerfile
# Non-root user — prevents Celery security warning
# ("Running as root is not recommended")
RUN useradd --no-create-home --shell /bin/false appuser \
    && chown -R appuser:appuser /app
USER appuser
```

Celery refuses to run as root by default. The `appuser` fix makes the warning disappear and is also better security practice.

---

## Installed Packages and Why

| Package | Why |
|---|---|
| `gunicorn` | Production WSGI server — Django's dev server is not safe for real traffic |
| `psycopg2-binary` | Django's PostgreSQL adapter |
| `whitenoise` | Serves static files (admin CSS) without needing Nginx |
| `python-dotenv` | Reads `.env` files locally without hardcoding secrets |
| `django-cors-headers` | Allows mobile/frontend apps on different domains to call the API |
| `celery[redis]` | Async task queue — decouples FCM push delivery from HTTP request handling |
| `redis` | Python client for Redis, required by Celery |
| `firebase-admin` | Official Firebase SDK — used by Celery worker to send FCM pushes |
| `fcm-django` | Django model (`FCMDevice`) for storing and managing device tokens |
