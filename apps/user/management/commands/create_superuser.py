import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create superuser from environment variables"

    def handle(self, *args, **options):
        user_model = get_user_model()
        email = os.getenv("DJANGO_SUPERUSER_EMAIL")
        password = os.getenv("DJANGO_SUPERUSER_PASSWORD")

        if not email or not password:
            self.stdout.write("Skipping superuser creation: env vars not set")
            return

        if user_model.objects.filter(email=email).exists():
            self.stdout.write("Superuser already exists")
            return

        user_model.objects.create_superuser(email=email, password=password)
        self.stdout.write(f"Superuser {email} created successfully")
