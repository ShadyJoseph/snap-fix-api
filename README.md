# SnapFix API

Django REST API backend for the SnapFix application.

## Prerequisites

- Python 3.11 or higher
- PostgreSQL 12 or higher
- pip (Python package manager)
- Git

## Initial Setup

### 1. Clone the Repository

```bash
git clone <repository-url>
cd snap-fix-api
```

### 2. Create Virtual Environment

```bash
python -m venv venv
```

### 3. Activate Virtual Environment

**Windows (PowerShell):**

```powershell
.\venv\Scripts\Activate
```

**Windows (Command Prompt):**

```cmd
venv\Scripts\activate.bat
```

**macOS/Linux:**

```bash
source venv/bin/activate
```

### 4. Install Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

## Database Setup

### 1. Install PostgreSQL

Download and install PostgreSQL from postgresql.org
. During installation, make note of:

PostgreSQL superuser: postgres

Superuser password: choose something secure

### 2. Create Database & User

Open psql (PostgreSQL command line) or pgAdmin and run:

-- Connect as postgres superuser
CREATE DATABASE snapfix;
CREATE USER snapfix_user WITH PASSWORD 'your_password';
GRANT ALL PRIVILEGES ON DATABASE snapfix TO snapfix_user;

-- Switch to snapfix database
\c snapfix

-- Make snapfix_user the owner of the public schema
ALTER SCHEMA public OWNER TO snapfix_user;
GRANT ALL PRIVILEGES ON SCHEMA public TO snapfix_user;

This step ensures Django can create tables in the public schema without permission errors.

### 3. Configure Environment Variables

Create a `.env` file in the project root (copy from `.env.example`):

```bash
cp .env.example .env
```

Update the `.env` file with your database credentials:

```env
SECRET_KEY=your-django-secret-key
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

DB_NAME=snapfix
DB_USER=snapfix
DB_PASSWORD=your_password
DB_HOST=localhost
DB_PORT=5432
```

**Generate a new SECRET_KEY:**

```python
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

## Running the Application

### 1. Run Migrations

```bash
python manage.py migrate
```

### 2. Create Superuser (Admin)

```bash
python manage.py createsuperuser
```

Follow the prompts to create an admin account.

### 3. Start Development Server

```bash
python manage.py runserver
```

The API will be available at `http://127.0.0.1:8000/`

Admin panel: `http://127.0.0.1:8000/admin/`

## Development Workflow

### Creating a New App

```bash
python manage.py startapp app_name
```

Don't forget to add the new app to `INSTALLED_APPS` in `config/settings.py`.

### Making Model Changes

After modifying models:

```bash
python manage.py makemigrations
python manage.py migrate
```

### Running Tests

```bash
python manage.py test
```

## Project Structure

```
snap-fix-api/
├── config/              # Project configuration
│   ├── settings.py      # Django settings
│   ├── urls.py          # URL routing
│   └── wsgi.py          # WSGI configuration
├── venv/                # Virtual environment (not in git)
├── manage.py            # Django management script
├── .env                 # Environment variables (not in git)
├── .env.example         # Example environment file
├── .gitignore           # Git ignore rules
├── requirements.txt     # Python dependencies
└── README.md            # This file
```

## Common Commands

```bash
# Install new package and update requirements
pip install package-name
pip freeze > requirements.txt

# Run linting and formatting with Ruff
ruff check .                    # Check for issues
ruff check --fix .              # Auto-fix issues
ruff format .                   # Format code

# Database operations
python manage.py makemigrations # Create new migrations
python manage.py migrate        # Apply migrations
python manage.py dbshell        # Open database shell

# Check for code issues
python manage.py check

```

## Troubleshooting

### Database Connection Issues

- Verify PostgreSQL is running
- Check credentials in `.env` file
- Ensure database exists
- Verify user has proper permissions

## Contributing

Create a unique branch for your feature:

git checkout -b feature/<your-feature-name>

Replace <your-feature-name> with a descriptive, unique name for your feature, e.g., feature/login-api.

Make your changes in your branch.

Commit your changes using a message that starts with the branch name:

git add .
git commit -m "feature/<your-feature-name>: Brief description of changes"

Example:

git commit -m "feature/login-api: Add login endpoint and serializer"

Push the branch to the remote repository:

git push origin feature/<your-feature-name>

Create a Pull Request on GitHub from your branch to the main branch.

Commit message structure reminder:

All commit messages should follow this format:

<branch-name>: <short description>

Example: feature/dashboard-ui: Implement responsive dashboard layout

## Environment Variables Reference

| Variable      | Description                   | Example                    |
| ------------- | ----------------------------- | -------------------------- |
| SECRET_KEY    | Django secret key             | Random 50-character string |
| DEBUG         | Debug mode (True/False)       | True                       |
| ALLOWED_HOSTS | Comma-separated allowed hosts | localhost,127.0.0.1        |
| DB_NAME       | Database name                 | snapfix_db                 |
| DB_USER       | Database username             | snapfix_user               |
| DB_PASSWORD   | Database password             | your_password              |
| DB_HOST       | Database host                 | localhost                  |
| DB_PORT       | Database port                 | 5432                       |
