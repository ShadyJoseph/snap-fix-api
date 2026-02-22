## What We Built

A production-ready Django REST API deployed on Railway with PostgreSQL, served by Gunicorn, with automated migrations and superuser creation.

---

## Dependencies Installed & Why

**gunicorn** — Django's built-in dev server is not safe for production. Gunicorn is a production-grade WSGI server that handles real traffic with multiple workers.

**psycopg2-binary** — Django needs this to talk to PostgreSQL. Without it Django can only use SQLite.

**whitenoise** — In production there's no Nginx to serve static files, so Whitenoise lets Django/Gunicorn serve them directly. Needed for the admin panel CSS to load.

**python-dotenv** — Lets Django read environment variables from `.env` files locally without hardcoding secrets in code.

**django-cors-headers** — Your frontend (different domain) needs permission to make API requests to your backend. Browsers block cross-origin requests by default, CORS headers tell the browser it's allowed.

---

## Files Created & Why

**Dockerfile** — Tells Docker how to build your app into a container: install dependencies, collect static files, run migrations and start Gunicorn.

**docker-compose.yml** — Orchestrates running both your Django app and PostgreSQL database together locally as if they were one system.

**Makefile** — Shortcuts for common Docker commands so you don't type long commands every time.

**.env.dev** — Local environment variables (database credentials, debug mode, secret key) kept out of your code.

**.env.prod** — Same but for production values, also kept out of git.

**apps/user/management/commands/create_superuser.py** — Custom management command to automatically create a superuser from environment variables on startup, since Railway's free tier doesn't give you a shell to run it manually.

---

## Settings Changes & Why

**Whitenoise in MIDDLEWARE** — Must be second in the list right after SecurityMiddleware so it intercepts static file requests before Django processes them.

**STATICFILES_STORAGE** — Tells Django to use Whitenoise's compressed storage for better performance.

**CORS_ALLOWED_ORIGINS** — List of frontend domains allowed to call your API. Read from env vars so you can change them without touching code.

**CSRF_TRUSTED_ORIGINS** — Django's CSRF protection blocks POST requests from untrusted domains, including your own admin panel if accessed via HTTPS. This tells Django to trust your Railway domain.

---

## Problems We Faced & Fixes

**Buildx missing on WSL2** — Docker's buildx plugin wasn't installed. Fixed by manually downloading and placing it in `~/.docker/cli-plugins/`.

**Web container starting before database was ready** — Django tried to migrate immediately but PostgreSQL was still initializing. Fixed by a retry loop in the Dockerfile CMD that waits until migrations succeed before starting Gunicorn.

**Wrong DB credentials in .env.dev** — Docker Compose set Postgres credentials as `postgres/postgres` but `.env.dev` had different values. Fixed by making them match, and setting `DB_HOST=db` (the Docker service name, not localhost).

**collectstatic failing during Docker build** — Running `collectstatic` at build time failed because `SECRET_KEY` wasn't available yet. Fixed by passing dummy env vars inline: `RUN SECRET_KEY=dummy DEBUG=False python manage.py collectstatic`.

**Railway DB connection failing** — Multiple causes in sequence:

- First used placeholder Railway hostnames that didn't exist
- Then the `${{reference}}` syntax didn't resolve because services weren't properly linked
- Finally the real issue: Django settings read `DB_*` variables but we were only setting `PG*` variables which Railway uses internally. Fixed by explicitly adding `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` to the web service variables with the actual values.

**ALLOWED_HOSTS not set correctly** — Was set to localhost which doesn't work on Railway. Fixed by setting it to the Railway-generated domain.

**No shell access on Railway free tier** — Can't run `createsuperuser` interactively. Fixed by creating a custom management command that reads credentials from environment variables and runs automatically on every startup, skipping if the user already exists.

**CSRF blocking admin login** — Django's CSRF protection blocked the admin login form because the Railway domain wasn't trusted. Fixed by adding `CSRF_TRUSTED_ORIGINS` to settings pointing to the Railway domain.

---

## Final Flow on Every Deploy

```
git push → Railway detects change → builds Dockerfile
→ runs migrations → creates superuser if not exists
→ starts Gunicorn → app is live
```
