import logging
import os

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.notifications"
    verbose_name = "Notifications"

    def ready(self):
        """Initialise the Firebase default app once at startup."""
        try:
            import firebase_admin
            from firebase_admin import credentials

            try:
                firebase_admin.get_app()
                return  # already initialised (e.g. during tests)
            except ValueError:
                pass

            # Production: credentials JSON stored as an environment variable.
            cred_json = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")
            if cred_json:
                import tempfile

                tmp_path = None
                try:
                    with tempfile.NamedTemporaryFile(
                        mode="w", suffix=".json", delete=False
                    ) as f:
                        f.write(cred_json)
                        tmp_path = f.name
                    firebase_admin.initialize_app(credentials.Certificate(tmp_path))
                finally:
                    if tmp_path:
                        try:
                            os.unlink(tmp_path)
                        except OSError:
                            pass
                return

            # Local Docker: path to the mounted secrets file.
            cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            if cred_path:
                firebase_admin.initialize_app(credentials.Certificate(cred_path))
                return

            # No credentials found — fail hard in production, warn in development.
            from django.conf import settings

            message = (
                "Firebase credentials not configured — "
                "set GOOGLE_APPLICATION_CREDENTIALS_JSON or GOOGLE_APPLICATION_CREDENTIALS."
            )
            if not settings.DEBUG:
                raise RuntimeError(message)
            logger.warning(message + " Push notifications will not be delivered.")

        except RuntimeError:
            raise
        except Exception as exc:
            logger.exception("Firebase initialisation failed: %s", exc)
            from django.conf import settings

            if not settings.DEBUG:
                raise
