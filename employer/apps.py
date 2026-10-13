# employer/apps.py
from django.apps import AppConfig


class EmployerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'employer'
    verbose_name = 'Employer Portal'

