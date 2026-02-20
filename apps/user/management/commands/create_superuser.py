import os
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model


class Command(BaseCommand):
    help = 'Create superuser from environment variables'

    def handle(self, *args, **options):
        User = get_user_model()
        email = os.getenv('DJANGO_SUPERUSER_EMAIL')
        password = os.getenv('DJANGO_SUPERUSER_PASSWORD')

        if not email or not password:
            self.stdout.write('Skipping superuser creation: env vars not set')
            return

        if User.objects.filter(email=email).exists():
            self.stdout.write('Superuser already exists')
            return

        User.objects.create_superuser(email=email, password=password)
        self.stdout.write(f'Superuser {email} created successfully')
