
# payments/apps.py
from django.apps import AppConfig


class PaymentsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'payments'
    verbose_name = 'Payments & Subscriptions'

    def ready(self):
        import payments.signals  # noqa: F401
        