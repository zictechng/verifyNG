import smtplib
from unittest.mock import patch
from django.test import TestCase, override_settings
from django.core import mail
from django.conf import settings
from celery.exceptions import Retry

# NOTE: We deliberately do NOT import core.tasks at module top-level here.
# This ensures test_task_autodiscovery_via_installed_apps verifies genuine
# autodiscovery through INSTALLED_APPS rather than Python module cache preloading.
from config.celery import app as celery_app


class CeleryConfigurationAndDiscoveryTestCase(TestCase):
    """
    Verifies Celery application initialization, settings binding,
    and genuine task registration/autodiscovery through Django INSTALLED_APPS.
    """

    def test_celery_app_configuration(self):
        self.assertEqual(celery_app.main, 'verifyng')
        self.assertEqual(celery_app.conf.broker_url, settings.CELERY_BROKER_URL)
        self.assertEqual(celery_app.conf.result_backend, settings.CELERY_RESULT_BACKEND)
        self.assertEqual(celery_app.conf.accept_content, ['json'])
        self.assertEqual(celery_app.conf.task_serializer, 'json')
        self.assertEqual(celery_app.conf.result_serializer, 'json')
        self.assertEqual(celery_app.conf.task_track_started, settings.CELERY_TASK_TRACK_STARTED)
        self.assertEqual(celery_app.conf.task_time_limit, settings.CELERY_TASK_TIME_LIMIT)

    def test_task_autodiscovery_via_installed_apps(self):
        # Trigger Celery loader default module import (which executes lazy autodiscover_tasks)
        celery_app.loader.import_default_modules()
        registered = celery_app.tasks.keys()
        self.assertIn('core.tasks.ping_celery_task', registered)
        self.assertIn('core.tasks.send_email_notification_task', registered)


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=True,
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'
)
class CeleryTaskExecutionTestCase(TestCase):
    """
    Validates task business logic, JSON serialization compliance,
    and email delivery under in-process eager execution.
    """

    def setUp(self):
        mail.outbox = []

    def tearDown(self):
        mail.outbox = []

    def test_ping_task_execution(self):
        from core.tasks import ping_celery_task
        async_result = ping_celery_task.delay()
        self.assertTrue(async_result.successful())
        result_data = async_result.get()
        self.assertEqual(result_data['status'], 'pong')
        self.assertIsNotNone(result_data['task_id'])

    def test_send_email_notification_success(self):
        from core.tasks import send_email_notification_task
        recipient = "claimant@example.com"
        subject = "VerifyNG Notification"
        body = "Reference: VNG-20261010-0001"

        async_result = send_email_notification_task.delay(recipient, subject, body)
        self.assertTrue(async_result.successful())
        result_data = async_result.get()

        # Validates that recipient PII is NOT returned in task result dictionary
        self.assertEqual(result_data, {"status": "sent", "count": 1})
        self.assertNotIn("recipient", result_data)

        # Validates actual delivery to locmem outbox
        self.assertEqual(len(mail.outbox), 1)
        sent_email = mail.outbox[0]
        self.assertIn(recipient, sent_email.to)
        self.assertEqual(sent_email.subject, subject)
        self.assertIn("VNG-20261010-0001", sent_email.body)

    def test_send_email_permanent_failure_propagates_without_retry(self):
        from core.tasks import send_email_notification_task
        # Permanent 554 SMTP rejection must propagate immediately without triggering task retry
        with patch('core.tasks.send_mail', side_effect=smtplib.SMTPResponseException(554, b'Transaction failed')):
            with self.assertRaises(smtplib.SMTPResponseException):
                send_email_notification_task.delay("perm_fail@example.com", "Test", "Body")

    def test_send_email_transient_network_failure_triggers_retry(self):
        from core.tasks import send_email_notification_task
        # Transient network disconnect must trigger task.retry(), which raises Retry in eager mode
        with patch('core.tasks.send_mail', side_effect=smtplib.SMTPServerDisconnected("Connection reset")):
            with self.assertRaises(Retry):
                send_email_notification_task.delay("transient@example.com", "Test", "Body")

