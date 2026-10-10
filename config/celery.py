
import os
from celery import Celery

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('verifyng')

# Reads configuration keys with 'CELERY_' prefix from Django settings.py
app.config_from_object('django.conf:settings', namespace='CELERY')

# Automatically discovers tasks from installed Django apps (e.g. core/tasks.py)
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f'Request: {self.request!r}')

