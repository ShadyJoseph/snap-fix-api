# SnapFix API

Django REST API backend for the SnapFix application.

## Prerequisites

- Docker & Docker Compose
- Git

## Setup

### 1. Clone the Repository

```bash
git clone <repository-url>
cd snap-fix-api
```

### 2. Configure Environment Variables

```bash
cp .env.example .env
```

Update `.env` with your values:

```env
SECRET_KEY=your-django-secret-key
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

DB_NAME=snapfix_db
DB_USER=postgres
DB_PASSWORD=postgres
DB_HOST=db
DB_PORT=5432

DJANGO_SUPERUSER_EMAIL=admin@example.com
DJANGO_SUPERUSER_PASSWORD=your_password
```

**Generate a SECRET_KEY:**

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

### 3. Start the Application

```bash
make up
```

This will build the containers, run migrations, create the superuser, and start the dev server.

The API will be available at `http://localhost:8000/`

Admin panel: `http://localhost:8000/admin/`

## Development Commands

```bash
make up              # Build and start containers with hot reload
make upd             # Build and start containers in background
make down            # Stop containers
make down-v          # Stop containers and delete volumes (fresh DB)
make logs            # Follow container logs

make migrate         # Apply migrations
make makemigrations  # Create new migrations
make superuser       # Create superuser manually
make shell           # Open Django shell
make bash            # Open container bash
```

## Testing

```bash
make test                                              # Run all tests
make test-v                                            # Run all tests with verbose output

# Run specific app tests
make test-app app=apps.customer.tests.test_views
make test-app app=apps.provider.tests.test_views
make test-app app=apps.core.tests.test_views

# Run specific test class
make test-class path=apps.customer.tests.test_views.CustomerRegisterTests

# Run specific test method
make test-class path=apps.customer.tests.test_views.CustomerRegisterTests.test_register_success
```

## Linting & Formatting

```bash
ruff check .          # Check for issues
ruff check --fix .    # Auto-fix issues
ruff format .         # Format code
```

## Project Structure

```
snap-fix-api/
├── apps/
│   ├── core/         # Categories & regions
│   ├── customer/     # Customer auth & profile
│   ├── provider/     # Provider auth, profile & onboarding
│   ├── booking/      # Booking management
│   ├── staff/        # Staff accounts
│   └── user/         # Base user model
├── config/
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── docker-compose.yml
├── docker-compose.dev.yml
├── Dockerfile
├── manage.py
├── requirements.txt
├── makefile
├── .env.example
└── README.md
```

## API Endpoints

```
BASE URL: http://localhost:8000

CUSTOMERS
  POST   /api/v1/customers/register/
  POST   /api/v1/customers/login/
  POST   /api/v1/customers/logout/
  GET    /api/v1/customers/me/

PROVIDERS
  POST   /api/v1/providers/register/
  POST   /api/v1/providers/login/
  POST   /api/v1/providers/logout/
  GET    /api/v1/providers/me/

CORE
  GET    /api/v1/core/categories/
  GET    /api/v1/core/regions/
```

## Environment Variables Reference

| Variable                  | Description                   | Example                    |
| ------------------------- | ----------------------------- | -------------------------- |
| SECRET_KEY                | Django secret key             | Random 50-character string |
| DEBUG                     | Debug mode                    | True                       |
| ALLOWED_HOSTS             | Comma-separated allowed hosts | localhost,127.0.0.1        |
| DB_NAME                   | Database name                 | snapfix_db                 |
| DB_USER                   | Database username             | postgres                   |
| DB_PASSWORD               | Database password             | postgres                   |
| DB_HOST                   | Database host                 | db                         |
| DB_PORT                   | Database port                 | 5432                       |
| DJANGO_SUPERUSER_EMAIL    | Admin email                   | admin@example.com          |
| DJANGO_SUPERUSER_PASSWORD | Admin password                | your_password              |

## Contributing

Create a branch for your feature:

```bash
git checkout -b feature/<your-feature-name>
```

Commit your changes:

```bash
git add .
git commit -m "feature/<your-feature-name>: Brief description"
```

Push and open a Pull Request:

```bash
git push origin feature/<your-feature-name>
```

All commit messages must follow this format:

```
<branch-name>: <short description>

Example: feature/login-api: Add login endpoint and serializer
```
