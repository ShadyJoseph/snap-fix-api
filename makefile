.PHONY: up upd down down-v logs migrate makemigrations superuser shell bash \
        test test-app test-class test-v \
        lint format security fix clean

DC      = docker compose
MANAGE  = $(DC) exec web python manage.py

# ── Docker ────────────────────────────────────────────────────

up:
	$(DC) up --build

upd:
	$(DC) up --build -d

down:
	$(DC) down

down-v:
	$(DC) down -v

logs:
	$(DC) logs -f web

# ── Django ────────────────────────────────────────────────────

migrate:
	$(MANAGE) migrate

makemigrations:
	$(MANAGE) makemigrations

superuser:
	$(MANAGE) createsuperuser

shell:
	$(MANAGE) shell

bash:
	$(DC) exec web bash

# ── Testing ───────────────────────────────────────────────────

test:
	$(MANAGE) test

test-v:
	$(MANAGE) test --verbosity=2

test-app:
	$(MANAGE) test $(app)

test-class:
	$(MANAGE) test $(path)

# ── Code Quality ──────────────────────────────────────────────

lint:
	$(DC) exec web ruff check .

format:
	$(DC) exec web ruff format . --check

security:
	$(DC) exec web bandit -r . -q

fix:
	$(DC) exec web ruff check . --fix
	$(DC) exec web ruff format .

clean: fix
	@echo "✓ All fixes and checks complete."