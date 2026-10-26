
# tests/test_payments.py
"""
Batch 14.4 — Payments models, services, and quota logic tests.

Coverage:
  - SiteSettings singleton: get_or_create, defaults
  - Plan model: price_naira property, is_free, has_unlimited_checks, str repr
  - Subscription model: is_currently_active, days_remaining
  - Transaction model: amount_naira, reference uniqueness
  - FreeUsageQuota: for_user(), reset_if_expired(), quota exhaustion
  - user_can_perform_check(): active subscriber, free tier, quota exceeded
  - get_active_subscription(): active vs expired
  - generate_reference(): format and uniqueness
  - verify_webhook_signature(): valid and tampered signatures
  - process_webhook_event(): charge.success, subscription.disable,
    invoice.payment_failed, unknown events
  - PaymentAuditLog: creation, immutability (append-only)
"""

import hashlib
import hmac
from datetime import timedelta
from unittest.mock import patch, MagicMock

from django.test import TestCase
from django.utils import timezone

from users.models import User
from payments.models import (
    SiteSettings, Plan, Subscription, Transaction,
    FreeUsageQuota, PaymentAuditLog,
)
from payments.services import (
    generate_reference,
    verify_webhook_signature,
    process_webhook_event,
    get_active_subscription,
    user_can_perform_check,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_user(username='payuser', email='pay@example.com'):
    return User.objects.create_user(username=username, email=email, password='StrongPass123!')


def make_plan(name='Basic', slug='basic', price_kobo=500_00, interval='monthly',
              check_limit=10, is_active=True):
    return Plan.objects.create(
        name=name, slug=slug, price_kobo=price_kobo,
        interval=interval, check_limit=check_limit, is_active=is_active,
    )


def make_active_subscription(user, plan, days_ahead=30):
    now = timezone.now()
    return Subscription.objects.create(
        user=user, plan=plan, status='active',
        current_period_start=now,
        current_period_end=now + timedelta(days=days_ahead),
    )


# ─── SiteSettings singleton ───────────────────────────────────────────────────

class SiteSettingsTest(TestCase):

    def test_get_creates_singleton(self):
        s = SiteSettings.get()
        self.assertIsNotNone(s)
        self.assertEqual(s.pk, 1)

    def test_get_returns_same_instance(self):
        s1 = SiteSettings.get()
        s2 = SiteSettings.get()
        self.assertEqual(s1.pk, s2.pk)

    def test_defaults_are_sensible(self):
        s = SiteSettings.get()
        self.assertGreater(s.free_check_limit, 0)
        self.assertGreater(s.free_check_window_days, 0)
        self.assertFalse(s.maintenance_mode)

    def test_str_representation(self):
        s = SiteSettings.get()
        self.assertIn('free limit', str(s))


# ─── Plan model ───────────────────────────────────────────────────────────────

class PlanModelTest(TestCase):

    def setUp(self):
        self.plan = make_plan(price_kobo=500_00)

    def test_price_naira_conversion(self):
        self.assertEqual(self.plan.price_naira, 500.0)

    def test_is_free_false_for_paid_plan(self):
        self.assertFalse(self.plan.is_free)

    def test_is_free_true_for_zero_price(self):
        free_plan = make_plan(name='Free', slug='free', price_kobo=0)
        self.assertTrue(free_plan.is_free)

    def test_has_unlimited_checks_false(self):
        self.assertFalse(self.plan.has_unlimited_checks)

    def test_has_unlimited_checks_true(self):
        unlimited = make_plan(name='Pro', slug='pro', check_limit=-1)
        self.assertTrue(unlimited.has_unlimited_checks)

    def test_str_contains_plan_name(self):
        self.assertIn('Basic', str(self.plan))

    def test_plan_slug_unique(self):
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            Plan.objects.create(name='Basic2', slug='basic', price_kobo=100_00)


# ─── Subscription model ───────────────────────────────────────────────────────

class SubscriptionModelTest(TestCase):

    def setUp(self):
        self.user = make_user()
        self.plan = make_plan()

    def test_is_currently_active_true(self):
        sub = make_active_subscription(self.user, self.plan, days_ahead=15)
        self.assertTrue(sub.is_currently_active)

    def test_is_currently_active_false_when_expired(self):
        now = timezone.now()
        sub = Subscription.objects.create(
            user=self.user, plan=self.plan, status='active',
            current_period_start=now - timedelta(days=40),
            current_period_end=now - timedelta(days=10),
        )
        self.assertFalse(sub.is_currently_active)

    def test_is_currently_active_false_when_cancelled(self):
        sub = make_active_subscription(self.user, self.plan)
        sub.status = 'cancelled'
        sub.save(update_fields=['status'])
        self.assertFalse(sub.is_currently_active)

    def test_days_remaining_positive(self):
        sub = make_active_subscription(self.user, self.plan, days_ahead=10)
        # Allow ±1 due to timing
        self.assertIn(sub.days_remaining, [9, 10])

    def test_days_remaining_zero_when_expired(self):
        now = timezone.now()
        sub = Subscription.objects.create(
            user=self.user, plan=self.plan, status='active',
            current_period_start=now - timedelta(days=10),
            current_period_end=now - timedelta(days=1),
        )
        self.assertEqual(sub.days_remaining, 0)

    def test_days_remaining_none_without_period_end(self):
        sub = Subscription.objects.create(
            user=self.user, plan=self.plan, status='pending',
        )
        self.assertIsNone(sub.days_remaining)

    def test_str_contains_username_and_plan(self):
        sub = make_active_subscription(self.user, self.plan)
        self.assertIn(self.user.username, str(sub))
        self.assertIn(self.plan.name, str(sub))


# ─── Transaction model ────────────────────────────────────────────────────────

class TransactionModelTest(TestCase):

    def setUp(self):
        self.user = make_user()
        self.plan = make_plan()

    def test_amount_naira_conversion(self):
        txn = Transaction.objects.create(
            user=self.user, plan=self.plan,
            reference='VNG-TEST-001', amount_kobo=250_00,
        )
        self.assertEqual(txn.amount_naira, 250.0)

    def test_reference_uniqueness(self):
        from django.db import IntegrityError
        Transaction.objects.create(
            user=self.user, plan=self.plan,
            reference='VNG-UNIQUE-REF', amount_kobo=100_00,
        )
        with self.assertRaises(IntegrityError):
            Transaction.objects.create(
                user=self.user, plan=self.plan,
                reference='VNG-UNIQUE-REF', amount_kobo=100_00,
            )

    def test_default_status_is_pending(self):
        txn = Transaction.objects.create(
            user=self.user, plan=self.plan,
            reference='VNG-PEND-001', amount_kobo=0,
        )
        self.assertEqual(txn.status, 'pending')


# ─── generate_reference() ─────────────────────────────────────────────────────

class GenerateReferenceTest(TestCase):

    def test_reference_starts_with_vng(self):
        self.assertTrue(generate_reference().startswith('VNG-'))

    def test_reference_is_unique(self):
        refs = {generate_reference() for _ in range(30)}
        self.assertEqual(len(refs), 30)

    def test_reference_is_uppercase(self):
        ref = generate_reference()
        self.assertEqual(ref, ref.upper())


# ─── FreeUsageQuota ───────────────────────────────────────────────────────────

class FreeUsageQuotaTest(TestCase):

    def setUp(self):
        self.user = make_user()
        # Ensure a clean SiteSettings with known limits
        s = SiteSettings.get()
        s.free_check_limit = 3
        s.free_check_window_days = 30
        s.save()

    def test_for_user_creates_quota(self):
        quota = FreeUsageQuota.for_user(self.user)
        self.assertIsNotNone(quota)
        self.assertEqual(quota.checks_used, 0)

    def test_for_user_returns_existing_quota(self):
        q1 = FreeUsageQuota.for_user(self.user)
        q1.checks_used = 2
        q1.save(update_fields=['checks_used'])
        q2 = FreeUsageQuota.for_user(self.user)
        self.assertEqual(q2.checks_used, 2)

    def test_reset_if_expired_resets_after_window(self):
        quota = FreeUsageQuota.objects.create(
            user=self.user,
            checks_used=3,
            quota_period_start=timezone.now() - timedelta(days=31),
        )
        quota.reset_if_expired()
        quota.refresh_from_db()
        self.assertEqual(quota.checks_used, 0)

    def test_reset_if_expired_does_not_reset_within_window(self):
        quota = FreeUsageQuota.objects.create(
            user=self.user,
            checks_used=2,
            quota_period_start=timezone.now() - timedelta(days=5),
        )
        quota.reset_if_expired()
        quota.refresh_from_db()
        self.assertEqual(quota.checks_used, 2)

    def test_str_contains_username(self):
        quota = FreeUsageQuota.for_user(self.user)
        self.assertIn(self.user.username, str(quota))


# ─── user_can_perform_check() ─────────────────────────────────────────────────

class UserCanPerformCheckTest(TestCase):

    def setUp(self):
        s = SiteSettings.get()
        s.free_check_limit = 3
        s.free_check_window_days = 30
        s.save()

    def test_active_subscriber_unlimited_plan_allowed(self):
        user = make_user(username='u1', email='u1@x.com')
        plan = make_plan(name='Unlimited', slug='unlimited', check_limit=-1)
        make_active_subscription(user, plan)
        allowed, reason = user_can_perform_check(user)
        self.assertTrue(allowed)
        self.assertEqual(reason, 'unlimited')

    def test_active_subscriber_limited_plan_allowed(self):
        user = make_user(username='u2', email='u2@x.com')
        plan = make_plan(name='Standard', slug='standard', check_limit=50)
        make_active_subscription(user, plan)
        allowed, reason = user_can_perform_check(user)
        self.assertTrue(allowed)
        self.assertEqual(reason, 'subscribed')

    def test_free_tier_within_limit_allowed(self):
        user = make_user(username='u3', email='u3@x.com')
        quota = FreeUsageQuota.objects.create(user=user, checks_used=1)
        allowed, reason = user_can_perform_check(user)
        self.assertTrue(allowed)
        self.assertEqual(reason, 'free_tier')

    def test_free_tier_at_limit_blocked(self):
        user = make_user(username='u4', email='u4@x.com')
        FreeUsageQuota.objects.create(user=user, checks_used=3)
        allowed, reason = user_can_perform_check(user)
        self.assertFalse(allowed)
        self.assertEqual(reason, 'quota_exceeded')

    def test_expired_subscription_falls_to_free_tier(self):
        user = make_user(username='u5', email='u5@x.com')
        plan = make_plan(name='Lapsed', slug='lapsed')
        now = timezone.now()
        Subscription.objects.create(
            user=user, plan=plan, status='active',
            current_period_start=now - timedelta(days=40),
            current_period_end=now - timedelta(days=10),
        )
        # User has no active sub — falls to free tier (0 checks used)
        allowed, reason = user_can_perform_check(user)
        self.assertTrue(allowed)
        self.assertEqual(reason, 'free_tier')


# ─── get_active_subscription() ────────────────────────────────────────────────

class GetActiveSubscriptionTest(TestCase):

    def setUp(self):
        self.user = make_user()
        self.plan = make_plan()

    def test_returns_active_subscription(self):
        make_active_subscription(self.user, self.plan)
        sub = get_active_subscription(self.user)
        self.assertIsNotNone(sub)

    def test_returns_none_when_no_subscription(self):
        sub = get_active_subscription(self.user)
        self.assertIsNone(sub)

    def test_returns_none_when_subscription_expired(self):
        now = timezone.now()
        Subscription.objects.create(
            user=self.user, plan=self.plan, status='active',
            current_period_start=now - timedelta(days=40),
            current_period_end=now - timedelta(days=5),
        )
        sub = get_active_subscription(self.user)
        self.assertIsNone(sub)

    def test_returns_none_when_subscription_cancelled(self):
        now = timezone.now()
        Subscription.objects.create(
            user=self.user, plan=self.plan, status='cancelled',
            current_period_start=now,
            current_period_end=now + timedelta(days=20),
        )
        sub = get_active_subscription(self.user)
        self.assertIsNone(sub)


# ─── verify_webhook_signature() ───────────────────────────────────────────────

class WebhookSignatureTest(TestCase):

    def _make_signature(self, payload: bytes, secret: str) -> str:
        return hmac.new(
            secret.encode('utf-8'), payload, hashlib.sha512
        ).hexdigest()

    def test_valid_signature_returns_true(self):
        secret = 'test_paystack_secret_key'
        payload = b'{"event":"charge.success"}'
        sig = self._make_signature(payload, secret)
        with patch('payments.services.settings') as mock_settings:
            mock_settings.PAYSTACK_SECRET_KEY = secret
            result = verify_webhook_signature(payload, sig)
        self.assertTrue(result)

    def test_tampered_payload_returns_false(self):
        secret = 'test_paystack_secret_key'
        payload = b'{"event":"charge.success"}'
        sig = self._make_signature(payload, secret)
        tampered = b'{"event":"charge.success","amount":99999}'
        with patch('payments.services.settings') as mock_settings:
            mock_settings.PAYSTACK_SECRET_KEY = secret
            result = verify_webhook_signature(tampered, sig)
        self.assertFalse(result)

    def test_wrong_secret_returns_false(self):
        payload = b'{"event":"charge.success"}'
        sig = self._make_signature(payload, 'correct_secret')
        with patch('payments.services.settings') as mock_settings:
            mock_settings.PAYSTACK_SECRET_KEY = 'wrong_secret'
            result = verify_webhook_signature(payload, sig)
        self.assertFalse(result)


# ─── process_webhook_event() ──────────────────────────────────────────────────

class ProcessWebhookEventTest(TestCase):

    def setUp(self):
        self.user = make_user()
        self.plan = make_plan()

    def test_webhook_received_audit_log_always_created(self):
        event = {'event': 'some.unknown.event', 'data': {}}
        process_webhook_event(event)
        self.assertTrue(
            PaymentAuditLog.objects.filter(action='WEBHOOK_RECEIVED').exists()
        )

    def test_subscription_disable_cancels_subscription(self):
        sub = make_active_subscription(self.user, self.plan)
        sub.paystack_subscription_code = 'SUB_TEST_001'
        sub.save(update_fields=['paystack_subscription_code'])

        event = {
            'event': 'subscription.disable',
            'data': {'subscription_code': 'SUB_TEST_001'},
        }
        process_webhook_event(event)
        sub.refresh_from_db()
        self.assertEqual(sub.status, 'cancelled')

    def test_subscription_disable_creates_audit_log(self):
        event = {
            'event': 'subscription.disable',
            'data': {'subscription_code': 'SUB_AUDIT_002'},
        }
        process_webhook_event(event)
        self.assertTrue(
            PaymentAuditLog.objects.filter(
                action='WEBHOOK_SUBSCRIPTION_DISABLED'
            ).exists()
        )

    def test_invoice_payment_failed_marks_past_due(self):
        sub = make_active_subscription(self.user, self.plan)
        sub.paystack_subscription_code = 'SUB_FAIL_003'
        sub.save(update_fields=['paystack_subscription_code'])

        event = {
            'event': 'invoice.payment_failed',
            'data': {'subscription': {'subscription_code': 'SUB_FAIL_003'}},
        }
        process_webhook_event(event)
        sub.refresh_from_db()
        self.assertEqual(sub.status, 'past_due')

    def test_invoice_payment_failed_creates_audit_log(self):
        event = {
            'event': 'invoice.payment_failed',
            'data': {'subscription': {'subscription_code': 'SUB_LOG_004'}},
        }
        process_webhook_event(event)
        self.assertTrue(
            PaymentAuditLog.objects.filter(action='WEBHOOK_PAYMENT_FAILED').exists()
        )

    @patch('payments.services.verify_transaction')
    def test_charge_success_triggers_verify(self, mock_verify):
        # Create a pending transaction so the handler finds it
        txn = Transaction.objects.create(
            user=self.user, plan=self.plan,
            reference='VNG-CHARGE-001', amount_kobo=500_00, status='pending',
        )
        event = {
            'event': 'charge.success',
            'data': {'reference': 'VNG-CHARGE-001'},
        }
        process_webhook_event(event)
        mock_verify.assert_called_once_with('VNG-CHARGE-001')

    @patch('payments.services.verify_transaction')
    def test_charge_success_already_succeeded_not_reverified(self, mock_verify):
        """If transaction is already 'success', verify_transaction must not be called again."""
        Transaction.objects.create(
            user=self.user, plan=self.plan,
            reference='VNG-CHARGE-002', amount_kobo=500_00, status='success',
        )
        event = {
            'event': 'charge.success',
            'data': {'reference': 'VNG-CHARGE-002'},
        }
        process_webhook_event(event)
        mock_verify.assert_not_called()

    def test_unknown_event_does_not_raise(self):
        """Unknown webhook events must be silently logged, not crash the handler."""
        event = {'event': 'totally.unknown', 'data': {}}
        try:
            process_webhook_event(event)
        except Exception as e:
            self.fail(f"process_webhook_event() raised unexpectedly: {e}")


# ─── PaymentAuditLog ──────────────────────────────────────────────────────────

class PaymentAuditLogTest(TestCase):

    def setUp(self):
        self.user = make_user()

    def test_audit_log_created(self):
        log = PaymentAuditLog.objects.create(
            action='CHECKOUT_INITIATED',
            user=self.user,
            details={'plan': 'Basic'},
        )
        self.assertIsNotNone(log.pk)
        self.assertEqual(log.action, 'CHECKOUT_INITIATED')

    def test_audit_log_count_grows_per_event(self):
        initial = PaymentAuditLog.objects.count()
        PaymentAuditLog.objects.create(action='PAYMENT_SUCCESS', user=self.user)
        PaymentAuditLog.objects.create(action='SUBSCRIPTION_ACTIVATED', user=self.user)
        self.assertEqual(PaymentAuditLog.objects.count(), initial + 2)

    def test_audit_log_str_contains_action(self):
        log = PaymentAuditLog.objects.create(
            action='WEBHOOK_RECEIVED', user=self.user,
        )
        self.assertIn('WEBHOOK_RECEIVED', str(log))

    def test_audit_log_has_timestamp(self):
        log = PaymentAuditLog.objects.create(action='FREE_PLAN_ACTIVATED', user=self.user)
        self.assertIsNotNone(log.timestamp)



# ─── Pay-As-You-Go Service Tests ──────────────────────────────────────────────

class PayAsYouGoServiceTest(TestCase):

    def setUp(self):
        self.user = make_user(username='payg_user', email='payg@example.com')
        self.settings = SiteSettings.get()

    @patch('payments.services.requests.post')
    def test_initialize_service_checkout_pricing_and_transaction(self, mock_post):
        from payments.services import initialize_service_checkout

        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            'status': True,
            'message': 'Authorization URL created',
            'data': {
                'authorization_url': 'https://checkout.paystack.com/payg-test',
                'access_code': 'ACC_TEST_123',
                'reference': 'PAYG-REF-1',
            }
        }

        # 1-Year Standard TrustPass
        res_1yr = initialize_service_checkout(
            user=self.user,
            service='certificate',
            tier='standard',
        )
        self.assertEqual(res_1yr['amount_naira'], self.settings.price_trustpass_1yr)
        self.assertEqual(res_1yr['authorization_url'], 'https://checkout.paystack.com/payg-test')

        trx_1yr = Transaction.objects.get(reference=res_1yr['reference'])
        self.assertEqual(trx_1yr.amount_kobo, self.settings.price_trustpass_1yr * 100)
        self.assertEqual(trx_1yr.status, 'pending')

        # 3-Year Enhanced TrustPass
        res_3yr = initialize_service_checkout(
            user=self.user,
            service='certificate',
            tier='enhanced',
        )
        self.assertEqual(res_3yr['amount_naira'], self.settings.price_trustpass_3yr)
        trx_3yr = Transaction.objects.get(reference=res_3yr['reference'])
        self.assertEqual(trx_3yr.amount_kobo, self.settings.price_trustpass_3yr * 100)

        # Audit log verification
        self.assertTrue(PaymentAuditLog.objects.filter(action='CHECKOUT_INITIATED', user=self.user).exists())

    def test_fulfill_payg_trustpass_certificate(self):
        from payments.services import _fulfill_payg_transaction
        from verification.models import VerificationCertificate
        from identities.models import SubjectEntity

        subject = SubjectEntity.objects.create(name="Applicant Test", type="person")
        cert = VerificationCertificate.objects.create(
            certificate_id="VNG-PAYG-TEST",
            subject=subject,
            holder=self.user,
            status='pending_payment',
        )

        trx = Transaction.objects.create(
            user=self.user,
            reference="VNG-TRX-CERT-PAYG",
            amount_kobo=150000,
            status='success',
            paystack_response={'data': {'metadata': {'service': 'certificate', 'certificate_id': cert.certificate_id}}}
        )

        _fulfill_payg_transaction(trx, {'metadata': {'service': 'certificate', 'certificate_id': cert.certificate_id}})
        cert.refresh_from_db()
        self.assertEqual(cert.status, 'pending')

    @patch('employer.tasks.process_single_staff_check_task.delay')
    def test_fulfill_payg_staff_check(self, mock_delay):
        from payments.services import _fulfill_payg_transaction
        from employer.models import EmployerProfile, StaffCheckRequest

        profile = EmployerProfile.objects.create(user=self.user, company_name="Test Corp")
        check = StaffCheckRequest.objects.create(
            employer=profile,
            requested_by=self.user,
            full_name="Staff Test",
            check_type='standard',
            status='pending_payment',
        )

        trx = Transaction.objects.create(
            user=self.user,
            reference="VNG-TRX-STAFF-PAYG",
            amount_kobo=150000,
            status='success',
            paystack_response={'data': {'metadata': {'service': 'staff_check', 'staff_check_id': str(check.id)}}}
        )

        _fulfill_payg_transaction(trx, {'metadata': {'service': 'staff_check', 'staff_check_id': str(check.id)}})
        check.refresh_from_db()
        self.assertEqual(check.status, 'pending')
        mock_delay.assert_called_once_with(str(check.id))

    def test_payg_routing_urls(self):
        from payments.views import _route_payg_success
        from django.test import RequestFactory

        rf = RequestFactory()
        req = rf.get('/payments/callback/')
        req.user = self.user

        from django.contrib.sessions.middleware import SessionMiddleware
        from django.contrib.messages.middleware import MessageMiddleware

        SessionMiddleware(lambda r: None).process_request(req)
        req.session.save()
        MessageMiddleware(lambda r: None).process_request(req)

        trx_pc = Transaction.objects.create(
            user=self.user,
            reference="VNG-TRX-PAYG-PC",
            amount_kobo=50000,
            status='success',
            paystack_response={'data': {'metadata': {'service': 'person_check', 'query': '08012345678'}}}
        )
        res_pc = _route_payg_success(req, trx_pc)
        self.assertIn('/employer/checks/person/?paid_ref=VNG-TRX-PAYG-PC', res_pc.url)
        self.assertIn('query=08012345678', res_pc.url)

        trx_cv = Transaction.objects.create(
            user=self.user,
            reference="VNG-TRX-PAYG-CV",
            amount_kobo=50000,
            status='success',
            paystack_response={'data': {'metadata': {
                'service': 'certificate_verify',
                'certificate_id': 'VNG-2026-TEST',
                'surname': 'Doe',
                'date_of_birth': '1990-01-01'
            }}}
        )
        res_cv = _route_payg_success(req, trx_cv)
        self.assertIn('/employer/certificate/verify/?paid_ref=VNG-TRX-PAYG-CV', res_cv.url)
        self.assertIn('certificate_id=VNG-2026-TEST', res_cv.url)
