# Development
up:
	docker compose up --build

upd:
	docker compose up --build -d

down:
	docker compose down

down-v:
	docker compose down -v

logs:
	docker compose logs -f web

# Django
migrate:
	docker compose exec web python manage.py migrate

superuser:
	docker compose exec web python manage.py createsuperuser

shell:
	docker compose exec web python manage.py shell

bash:
	docker compose exec web bash

makemigrations:
	docker compose exec web python manage.py makemigrations

# Testing
test:
	docker compose exec web python manage.py test

test-app:
	docker compose exec web python manage.py test $(app)

test-class:
	docker compose exec web python manage.py test $(path)

test-v:
	docker compose exec web python manage.py test --verbosity=2