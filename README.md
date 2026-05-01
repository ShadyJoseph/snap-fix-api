# SnapFix API

Django REST Framework + GeoDjango backend for the SnapFix home-services platform.
Handles customer bookings, provider onboarding & matching, FSM-driven service-request
lifecycle, multi-method payment settlement (cash / card / wallet), and AI-powered
provider recommendation with a multi-provider scoring engine (OpenAI, Gemini, Groq, Anthropic).

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

Builds containers, runs migrations, creates the superuser, and starts the dev server.

- API: `http://localhost:8000/`
- Admin panel: `http://localhost:8000/admin/`

---

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
make shell           # Open Django shell (shell_plus + IPython)
make bash            # Open container bash
```

## Testing

```bash
make test                                              # Run all tests
make test-v                                            # Verbose output

# Run a specific app's tests
make test-app app=apps.booking.tests.test_views
make test-app app=apps.provider.tests.test_views
make test-app app=apps.core.tests.test_views
make test-app app=apps.customer.tests.test_views
make test-app app=apps.provider.tests.test_provider_onboarding
make test-app app=apps.notifications.tests.test_notifications
make test-app app=apps.booking.tests.test_recommendations

# Run a specific test class or method
make test-class path=apps.customer.tests.test_views.CustomerRegisterTests
make test-class path=apps.customer.tests.test_views.CustomerRegisterTests.test_register_success
```

## Code Quality

```bash
make lint            # Check for linting issues (ruff)
make format          # Check formatting (ruff format --check)
make security        # Static security scan (bandit)
make fix             # Auto-fix lint + format issues
make clean           # Run fix and confirm all checks pass
```

---

## Local Shell Testing

`factories.py` at the project root provides unified model factories for
interactive shell sessions. Every factory has safe defaults and accepts `**kwargs`
to override any field.

```bash
make shell   # opens shell_plus + IPython inside the container
```

```python
from factories import *

# Quick full scaffold — returns a dict of linked objects
d = scaffold()
sr = d["service_request"]

# Or build piecemeal
region   = make_region()
category = make_category(name="Electrical", slug="electrical")
customer = make_customer(email="alice@test.com")
provider = make_provider(active=True, verified=True)
provider.categories.add(category)

sr = make_service_request(customer, category, region, is_urgent=True)

# Provider onboarding flow
staff = make_staff()
p     = make_provider(active=False, verified=False)
onb   = make_onboarding(region, category, applicant=p)
onb.move_to_review(staff)
onb.approve(staff)

# Completed job + review
sr     = make_completed_request(customer, provider, category, region)
review = make_review(sr, customer, provider, rating=5, comment="Great!")

# Images (for ImageField testing)
img = make_image("photo.png")
```

**Available factories:**

| Function                                                                 | Creates                           |
| ------------------------------------------------------------------------ | --------------------------------- |
| `make_image(name)`                                                       | `SimpleUploadedFile` (1x1 PNG)    |
| `make_region(**kwargs)`                                                  | `Region`                          |
| `make_category(**kwargs)`                                                | `Category`                        |
| `make_office(region, **kwargs)`                                          | `Office`                          |
| `make_customer(**kwargs)`                                                | `Customer` (active)               |
| `make_provider(active, verified, **kwargs)`                              | `Provider`                        |
| `make_staff(**kwargs)`                                                   | `Staff`                           |
| `make_service_request(customer, category, region, **kwargs)`             | `ServiceRequest` (PENDING)        |
| `make_completed_request(customer, provider, category, region, **kwargs)` | `ServiceRequest` (COMPLETED)      |
| `make_review(sr, customer, provider, **kwargs)`                          | `Review`                          |
| `make_onboarding(region, category, applicant, **kwargs)`                 | `ProviderOnboarding`              |
| `scaffold()`                                                             | All of the above, linked together |

---

## Project Structure

```
snap-fix-api/
├── apps/
│   ├── core/             # Categories, regions, offices
│   ├── customer/         # Customer auth & profile
│   ├── provider/         # Provider auth, profile & onboarding FSM
│   ├── booking/          # Service request lifecycle, payments, reviews, AI recommendation
│   ├── staff/            # Staff accounts
│   └── user/             # Shared base user model
├── config/
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── local_scripts/        # One-off helper scripts
├── factories.py          # Unified model factories (tests + shell)
├── docker-compose.yml
├── Dockerfile
├── manage.py
├── requirements.txt
├── makefile
├── URLs.md                  # Full API reference with request/response shapes
├── AI_RECOMMENDATION.md     # Mobile integration guide for the AI recommendation flow
├── AI_VALIDATION_PIPELINE.md # Architecture doc for onboarding document AI validation
├── .env.example
└── README.md
```

---

## API Overview

Full request/response documentation lives in [URLs.md](URLs.md).
Mobile integration for the AI recommendation flow: [AI_RECOMMENDATION.md](AI_RECOMMENDATION.md).

### Service-Request State Flow

```
pending → assigned → quoted → confirmed → in_progress → completed
                  ↘ (accept) ↗                          ↑ terminal

CANCELLED is reachable from: pending, assigned, quoted, confirmed, in_progress.
```

### Booking Modes

| Mode                  | How it works                                                                                                                                |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `broadcast` (default) | Request enters the open pool; any matching provider can self-assign                                                                         |
| `direct`              | Customer books a provider from their favorites via `POST /requests/direct/`; atomically assigned at creation                                |
| `recommended`         | On creation the API scores eligible providers and returns the top 3 with AI reasoning; customer picks one via `POST /requests/recommended/` |

Scoring signals (shared engine used for both recommendation and the provider open-requests view):
rating (30%) · distance (25%) · completion rate (20%) · favourite bonus (15%) · urgency availability (10%)

---

## Environment Variables Reference

| Variable                    | Description           | Example               |
| --------------------------- | --------------------- | --------------------- |
| `SECRET_KEY`                | Django secret key     | Random 50-char string |
| `DEBUG`                     | Debug mode            | `True`                |
| `ALLOWED_HOSTS`             | Comma-separated hosts | `localhost,127.0.0.1` |
| `DB_NAME`                   | Database name         | `snapfix_db`          |
| `DB_USER`                   | Database username     | `postgres`            |
| `DB_PASSWORD`               | Database password     | `postgres`            |
| `DB_HOST`                   | Database host         | `db`                  |
| `DB_PORT`                   | Database port         | `5432`                |
| `DJANGO_SUPERUSER_EMAIL`    | Admin email           | `admin@example.com`   |
| `DJANGO_SUPERUSER_PASSWORD` | Admin password        | `your_password`       |

---

## Contributing

```bash
git checkout -b feature/<your-feature-name>

git add <files>
git commit -m "feature/<your-feature-name>: Brief description"

git push origin feature/<your-feature-name>
```

Commit message format: `<branch-name>: <short description>`
Example: `feature/login-api: Add login endpoint and serializer`
