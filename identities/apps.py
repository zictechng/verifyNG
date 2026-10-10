from django.apps import AppConfig


class IdentitiesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'identities'

def ready(self):
        import identities.signals  # noqa: F401 — registers signal receivers
