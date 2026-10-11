from django.test import TestCase, RequestFactory
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse

from users.models import User
from identities.models import SubjectEntity
from reports.models import FraudReport, ReportEvidence
from core.permissions import (
    is_moderator,
    is_verification_officer,
    is_employer,
    is_business,
    is_agency,
    can_view_report,
    can_view_evidence,
    role_required,
    moderator_required,
    officer_required,
    employer_required,
    business_required,
    agency_required,
)


class PermissionHelpersTestCase(TestCase):
    def setUp(self):
        self.individual_user = User.objects.create_user(
            username='indiv', email='indiv@test.com', password='password123', role='individual'
        )
        self.officer_user = User.objects.create_user(
            username='officer', email='officer@test.com', password='password123', role='officer'
        )
        self.moderator_user = User.objects.create_user(
            username='mod', email='mod@test.com', password='password123', role='moderator'
        )
        self.employer_user = User.objects.create_user(
            username='emp', email='emp@test.com', password='password123', role='employer'
        )
        self.business_user = User.objects.create_user(
            username='biz', email='biz@test.com', password='password123', role='business'
        )
        self.agency_user = User.objects.create_user(
            username='agency', email='agency@test.com', password='password123', role='agency'
        )
        self.staff_user = User.objects.create_user(
            username='staff', email='staff@test.com', password='password123', is_staff=True
        )
        self.superuser = User.objects.create_superuser(
            username='admin', email='admin@test.com', password='password123'
        )
        self.anonymous_user = AnonymousUser()

    def test_role_helpers(self):
        # is_moderator tests
        self.assertTrue(is_moderator(self.moderator_user))
        self.assertTrue(is_moderator(self.staff_user))
        self.assertTrue(is_moderator(self.superuser))
        self.assertFalse(is_moderator(self.officer_user))
        self.assertFalse(is_moderator(self.individual_user))
        self.assertFalse(is_moderator(self.anonymous_user))

        # is_verification_officer tests (strictly role-based)
        self.assertTrue(is_verification_officer(self.officer_user))
        self.assertFalse(is_verification_officer(self.staff_user))
        self.assertFalse(is_verification_officer(self.superuser))
        self.assertFalse(is_verification_officer(self.individual_user))

        # role specific helpers
        self.assertTrue(is_employer(self.employer_user))
        self.assertFalse(is_employer(self.individual_user))

        self.assertTrue(is_business(self.business_user))
        self.assertFalse(is_business(self.individual_user))

        self.assertTrue(is_agency(self.agency_user))
        self.assertFalse(is_agency(self.individual_user))


class ReportAndEvidenceVisibilityTestCase(TestCase):
    def setUp(self):
        self.reporter = User.objects.create_user(
            username='reporter', email='reporter@test.com', password='password123', role='individual'
        )
        self.other_user = User.objects.create_user(
            username='other', email='other@test.com', password='password123', role='individual'
        )
        self.moderator = User.objects.create_user(
            username='moderator', email='mod@test.com', password='password123', role='moderator'
        )
        self.anonymous = AnonymousUser()

        # Subject Entity verified: type='person'
        self.subject = SubjectEntity.objects.create(name='John Doe', type='person')

        # Create reports in various states
        self.pub_report = FraudReport.objects.create(
            reference_number='VNG-1001',
            reporter=self.reporter,
            target_subject=self.subject,
            title='Public Fraud Report',
            allegation='Scam incident',
            state='published'
        )
        self.review_report = FraudReport.objects.create(
            reference_number='VNG-1002',
            reporter=self.reporter,
            target_subject=self.subject,
            title='Under Review Report',
            allegation='Pending review',
            state='under_review'
        )
        self.archived_report = FraudReport.objects.create(
            reference_number='VNG-1003',
            reporter=self.reporter,
            target_subject=self.subject,
            title='Archived Report',
            allegation='Old report',
            state='archived'
        )

        # Evidence files
        self.pub_non_conf_evidence = ReportEvidence.objects.create(
            report=self.pub_report,
            description='Public Document',
            is_confidential=False
        )
        self.pub_conf_evidence = ReportEvidence.objects.create(
            report=self.pub_report,
            description='Confidential ID',
            is_confidential=True
        )
        self.review_conf_evidence = ReportEvidence.objects.create(
            report=self.review_report,
            description='Confidential Receipt',
            is_confidential=True
        )

    def test_can_view_report(self):
        # Published report: accessible by all
        self.assertTrue(can_view_report(self.anonymous, self.pub_report))
        self.assertTrue(can_view_report(self.other_user, self.pub_report))
        self.assertTrue(can_view_report(self.reporter, self.pub_report))
        self.assertTrue(can_view_report(self.moderator, self.pub_report))

        # Under review report: accessible to reporter and moderator, denied to public and other users
        self.assertFalse(can_view_report(self.anonymous, self.review_report))
        self.assertFalse(can_view_report(self.other_user, self.review_report))
        self.assertTrue(can_view_report(self.reporter, self.review_report))
        self.assertTrue(can_view_report(self.moderator, self.review_report))

        # Archived report: accessible ONLY to moderator, denied even to reporter
        self.assertFalse(can_view_report(self.anonymous, self.archived_report))
        self.assertFalse(can_view_report(self.other_user, self.archived_report))
        self.assertFalse(can_view_report(self.reporter, self.archived_report))
        self.assertTrue(can_view_report(self.moderator, self.archived_report))

    def test_can_view_evidence(self):
        # Non-confidential evidence on published report: viewable by public/all
        self.assertTrue(can_view_evidence(self.anonymous, self.pub_non_conf_evidence))
        self.assertTrue(can_view_evidence(self.other_user, self.pub_non_conf_evidence))

        # Confidential evidence on published report: denied to public/other users, allowed for reporter and moderator
        self.assertFalse(can_view_evidence(self.anonymous, self.pub_conf_evidence))
        self.assertFalse(can_view_evidence(self.other_user, self.pub_conf_evidence))
        self.assertTrue(can_view_evidence(self.reporter, self.pub_conf_evidence))
        self.assertTrue(can_view_evidence(self.moderator, self.pub_conf_evidence))

        # Confidential evidence on under_review report: denied to public/other, allowed for reporter and moderator
        self.assertFalse(can_view_evidence(self.anonymous, self.review_conf_evidence))
        self.assertFalse(can_view_evidence(self.other_user, self.review_conf_evidence))
        self.assertTrue(can_view_evidence(self.reporter, self.review_conf_evidence))
        self.assertTrue(can_view_evidence(self.moderator, self.review_conf_evidence))


class ViewDecoratorsTestCase(TestCase):
    def setUp(self):
        self.rf = RequestFactory()
        self.officer = User.objects.create_user(
            username='officer', email='officer@test.com', password='password123', role='officer'
        )
        self.individual = User.objects.create_user(
            username='indiv', email='indiv@test.com', password='password123', role='individual'
        )
        self.staff = User.objects.create_user(
            username='staff', email='staff@test.com', password='password123', is_staff=True
        )
        self.superuser = User.objects.create_superuser(
            username='admin', email='admin@test.com', password='password123'
        )
        self.anonymous = AnonymousUser()

    def test_role_required_decorator(self):
        @role_required('officer')
        def dummy_view(request):
            return HttpResponse("OK")

        # Authorized officer
        req = self.rf.get('/')
        req.user = self.officer
        response = dummy_view(req)
        self.assertEqual(response.status_code, 200)

        # Superuser bypass
        req.user = self.superuser
        response = dummy_view(req)
        self.assertEqual(response.status_code, 200)

        # Staff user without officer role -> 403 PermissionDenied
        req.user = self.staff
        with self.assertRaises(PermissionDenied):
            dummy_view(req)

        # Unauthorized individual user -> 403 PermissionDenied
        req.user = self.individual
        with self.assertRaises(PermissionDenied):
            dummy_view(req)

        # Anonymous user -> redirected (302)
        req.user = self.anonymous
        response = dummy_view(req)
        self.assertEqual(response.status_code, 302)

    def test_moderator_required_decorator(self):
        @moderator_required
        def dummy_mod_view(request):
            return HttpResponse("OK")

        # Staff user allowed
        req = self.rf.get('/')
        req.user = self.staff
        response = dummy_mod_view(req)
        self.assertEqual(response.status_code, 200)

        # Superuser allowed
        req.user = self.superuser
        response = dummy_mod_view(req)
        self.assertEqual(response.status_code, 200)

        # Officer denied
        req.user = self.officer
        with self.assertRaises(PermissionDenied):
            dummy_mod_view(req)


# ==============================================================================
# SiteConfiguration Singleton and Branding Tests (Batch UI-4)
# ==============================================================================
import io
from PIL import Image
from django.db import transaction, IntegrityError
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.admin.sites import AdminSite
from core.models import SiteConfiguration
from core.admin import SiteConfigurationAdmin
from core.context_processors import site_configuration


class SiteConfigurationTestCase(TestCase):
    def setUp(self):
        self.rf = RequestFactory()

    def test_get_solo_creates_initial_record_and_repeated_calls_return_same(self):
        # 1. get_solo creates initial record with default 'VerifyNG'
        config = SiteConfiguration.get_solo()
        self.assertEqual(config.pk, 1)
        self.assertEqual(config.site_name, 'VerifyNG')
        self.assertEqual(config.site_tagline, 'Public Trust & Safety Platform')

        # 2. Repeated calls return the identical instance without creating extra records
        config2 = SiteConfiguration.get_solo()
        self.assertEqual(config2.pk, 1)
        self.assertEqual(SiteConfiguration.objects.count(), 1)

    def test_existing_configuration_updates_normally(self):
        config = SiteConfiguration.get_solo()
        config.site_name = "Custom Trust Portal"
        config.site_tagline = "National Verification"
        config.save()

        config.refresh_from_db()
        self.assertEqual(config.site_name, "Custom Trust Portal")
        self.assertEqual(config.site_tagline, "National Verification")
        self.assertEqual(SiteConfiguration.objects.count(), 1)

    def test_detached_duplicate_instance_with_pk1_rejected(self):
        # Initial record exists
        initial = SiteConfiguration.get_solo()
        initial.site_name = "Original Brand"
        initial.save()

        # Detached instance explicitly assigned pk=1 attempts to save
        duplicate = SiteConfiguration(pk=1, site_name="New Brand")
        with self.assertRaises(ValidationError):
            duplicate.save()

        # Verify original record in database is preserved and untouched
        initial.refresh_from_db()
        self.assertEqual(initial.site_name, "Original Brand")

    def test_attempted_creation_with_pk2_rejected_at_model_and_database_levels(self):
        # 1. Via model save(): rejected by ValidationError before touching DB
        with self.assertRaises(ValidationError):
            SiteConfiguration(pk=2, site_name="Invalid Brand").save()

        self.assertFalse(SiteConfiguration.objects.filter(pk=2).exists())

        # 2. Via bulk_create() (bypassing save()): rejected by PostgreSQL CheckConstraint
        # Wrapped in transaction.atomic() to keep PostgreSQL transaction healthy
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                SiteConfiguration.objects.bulk_create([
                    SiteConfiguration(id=2, site_name="Bulk Invalid")
                ])

        self.assertFalse(SiteConfiguration.objects.filter(id=2).exists())

    def test_instance_and_queryset_deletion_blocked(self):
        config = SiteConfiguration.get_solo()

        # Instance deletion blocked
        with self.assertRaises(ValidationError):
            config.delete()

        # QuerySet bulk deletion blocked
        with self.assertRaises(ValidationError):
            SiteConfiguration.objects.all().delete()

        self.assertEqual(SiteConfiguration.objects.count(), 1)

    def test_context_processor_exposes_configuration(self):
        config = SiteConfiguration.get_solo()
        config.site_name = "Portal Context Test"
        config.save()

        request = self.rf.get('/')
        ctx = site_configuration(request)
        self.assertIn('site_config', ctx)
        self.assertEqual(ctx['site_config'].site_name, "Portal Context Test")

    def test_default_branding_rendered_when_images_absent(self):
        config = SiteConfiguration.get_solo()
        config.site_name = "VerifyNG"
        config.logo = None
        config.favicon = None
        config.save()

        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "VerifyNG")
        # Confirms default fallback SVG shield is rendered
        self.assertContains(response, 'fill="#2457D6"')

    def test_custom_logo_and_favicon_rendered(self):
        config = SiteConfiguration.get_solo()

        # Generate small valid test images in memory
        logo_buf = io.BytesIO()
        Image.new('RGB', (100, 32), color='blue').save(logo_buf, format='PNG')
        logo_buf.seek(0)
        config.logo = SimpleUploadedFile("brand_logo.png", logo_buf.read(), content_type="image/png")

        fav_buf = io.BytesIO()
        Image.new('RGB', (16, 16), color='green').save(fav_buf, format='PNG')
        fav_buf.seek(0)
        config.favicon = SimpleUploadedFile("brand_fav.png", fav_buf.read(), content_type="image/png")
        config.save()

        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, config.logo.url)
        self.assertContains(response, config.favicon.url)

    def test_admin_permissions_lifecycle(self):
        admin_site = AdminSite()
        admin_instance = SiteConfigurationAdmin(SiteConfiguration, admin_site)
        request = self.rf.get('/admin/core/siteconfiguration/')

        # When record exists (pk=1)
        SiteConfiguration.get_solo()
        self.assertFalse(admin_instance.has_add_permission(request))
        self.assertFalse(admin_instance.has_delete_permission(request))

    def test_invalid_image_upload_rejected(self):
        config = SiteConfiguration.get_solo()
        # Non-image plain text file
        invalid_file = SimpleUploadedFile("fake.png", b"This is plain text, not an image", content_type="image/png")
        config.logo = invalid_file

        from django import forms
        class SiteConfigForm(forms.ModelForm):
            class Meta:
                model = SiteConfiguration
                fields = ['site_name', 'logo']

        form = SiteConfigForm(
            data={'site_name': 'Test'},
            files={'logo': invalid_file},
            instance=config
        )
        self.assertFalse(form.is_valid())
        self.assertIn('logo', form.errors)



# ==============================================================================
# Rate Limiting Tests (Phase 6, Batch 6.1)
# ==============================================================================
from unittest.mock import patch
from django.test import override_settings
from django.core.cache import caches
from django.core.exceptions import ImproperlyConfigured
from redis.exceptions import ConnectionError as RedisConnectionError, ResponseError as RedisResponseError
from core.rate_limiting import (
    validate_positive_int,
    get_client_ip,
    check_rate_limit,
)


@override_settings(CACHES={
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'rate-limit-locmem-test',
        'KEY_PREFIX': 'verifyng_test',
    }
})
class RateLimiterUnitTestCase(TestCase):
    def setUp(self):
        caches['default'].clear()
        self.rf = RequestFactory()

    def test_validation_rejects_invalid_values(self):
        with self.assertRaises(ImproperlyConfigured):
            validate_positive_int(True, 'Limit')
        with self.assertRaises(ImproperlyConfigured):
            validate_positive_int(False, 'Limit')
        with self.assertRaises(ImproperlyConfigured):
            validate_positive_int(0, 'Limit')
        with self.assertRaises(ImproperlyConfigured):
            validate_positive_int(-15, 'Window')
        with self.assertRaises(ImproperlyConfigured):
            validate_positive_int("30", 'Limit')
        self.assertEqual(validate_positive_int(30, 'Limit'), 30)

    def test_client_ip_extraction_and_proxy_trust(self):
        # 1. Standard untrusted direct IP
        req = self.rf.get('/')
        req.META['REMOTE_ADDR'] = '203.0.113.195'
        self.assertEqual(get_client_ip(req), '203.0.113.195')

        # 2. Spoofed X-Forwarded-For ignored when REMOTE_ADDR is untrusted
        req.META['HTTP_X_FORWARDED_FOR'] = '198.51.100.22, 10.0.0.1'
        self.assertEqual(get_client_ip(req), '203.0.113.195')

        # 3. Trusted proxy right-to-left traversal
        with override_settings(SECURE_PROXY_TRUSTED_IPS=['10.0.0.1', '10.0.0.2']):
            req.META['REMOTE_ADDR'] = '10.0.0.1'
            req.META['HTTP_X_FORWARDED_FOR'] = '198.51.100.22, 10.0.0.2'
            self.assertEqual(get_client_ip(req), '198.51.100.22')

        # 4. Malformed entry halts traversal safely
        with override_settings(SECURE_PROXY_TRUSTED_IPS=['10.0.0.1']):
            req.META['REMOTE_ADDR'] = '10.0.0.1'
            req.META['HTTP_X_FORWARDED_FOR'] = '198.51.100.22, invalid-ip-string'
            self.assertEqual(get_client_ip(req), '10.0.0.1')

        # 5. Missing/invalid REMOTE_ADDR
        req.META['REMOTE_ADDR'] = ''
        self.assertEqual(get_client_ip(req), 'invalid_peer')

    def test_rate_limiting_enforcement_and_retry_after(self):
        req = self.rf.get('/')
        req.META['REMOTE_ADDR'] = '192.0.2.1'

        # Requests 1 to 5 allowed (limit=5, window=60)
        for i in range(5):
            limited, retry_after = check_rate_limit(req, namespace="test_ns", limit=5, window=60)
            self.assertFalse(limited)
            self.assertEqual(retry_after, 0)

        # 6th request exceeded
        limited, retry_after = check_rate_limit(req, namespace="test_ns", limit=5, window=60)
        self.assertTrue(limited)
        self.assertGreaterEqual(retry_after, 1)
        self.assertLessEqual(retry_after, 60)

    def test_client_ip_isolation(self):
        req1 = self.rf.get('/')
        req1.META['REMOTE_ADDR'] = '192.0.2.10'

        req2 = self.rf.get('/')
        req2.META['REMOTE_ADDR'] = '192.0.2.20'

        for _ in range(3):
            check_rate_limit(req1, namespace="test_iso", limit=3, window=60)

        limited1, _ = check_rate_limit(req1, namespace="test_iso", limit=3, window=60)
        limited2, _ = check_rate_limit(req2, namespace="test_iso", limit=3, window=60)

        self.assertTrue(limited1)
        self.assertFalse(limited2)

    def test_namespace_isolation(self):
        req = self.rf.get('/')
        req.META['REMOTE_ADDR'] = '192.0.2.30'

        for _ in range(2):
            check_rate_limit(req, namespace="ns_a", limit=2, window=60)

        limited_a, _ = check_rate_limit(req, namespace="ns_a", limit=2, window=60)
        limited_b, _ = check_rate_limit(req, namespace="ns_b", limit=2, window=60)

        self.assertTrue(limited_a)
        self.assertFalse(limited_b)

    def test_fail_open_on_redis_connectivity_error(self):
        req = self.rf.get('/')
        req.META['REMOTE_ADDR'] = '192.0.2.40'

        with patch('core.rate_limiting._execute_test_locmem_rate_limit', side_effect=RedisConnectionError("Connection lost")):
            limited, retry_after = check_rate_limit(req, namespace="test_failopen", limit=5, window=60)
            self.assertFalse(limited)
            self.assertEqual(retry_after, 0)

    def test_unexpected_programming_error_propagates(self):
        req = self.rf.get('/')
        req.META['REMOTE_ADDR'] = '192.0.2.50'

        with patch('core.rate_limiting._execute_test_locmem_rate_limit', side_effect=TypeError("Unexpected error")):
            with self.assertRaises(TypeError):
                check_rate_limit(req, namespace="test_propagate", limit=5, window=60)

    @override_settings(CACHES={
        'default': {
            'BACKEND': 'django.core.cache.backends.dummy.DummyCache',
        }
    })
    def test_unsupported_cache_backend_raises_improperly_configured(self):
        req = self.rf.get('/')
        with self.assertRaises(ImproperlyConfigured):
            check_rate_limit(req, namespace="test_unsupported", limit=5, window=60)



from django.urls import reverse
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from identities.models import Identifier
from identities.utils import hash_identifier_value
from identities.services import lookup_public_record
from reports.models import ReportEvidence
from reports.services import (
    create_fraud_report,
    transition_report_state,
    file_dispute_for_report,
    resolve_dispute,
)
from verification.services import (
    create_verification_request,
    claim_verification_request,
    complete_verification_request,
    reject_verification_request,
)


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=True,
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'
)
class EndToEndFraudReportAndPublicCheckTestCase(TestCase):
    def setUp(self):
        self.reporter = User.objects.create_user(
            username='e2e_reporter', email='rep@example.com', password='password123', role='individual'
        )
        self.disputant = User.objects.create_user(
            username='e2e_disputant', email='disp@example.com', password='password123', role='individual'
        )
        self.moderator = User.objects.create_user(
            username='e2e_mod', email='mod@example.com', password='password123', role='moderator'
        )

        # Create SubjectEntity with registered Phone Identifier
        self.phone_raw = "08012345678"
        self.phone_hash = hash_identifier_value('phone', self.phone_raw)
        self.subject = SubjectEntity.objects.create(name="E2E Merchant Ltd", type="business")
        Identifier.objects.create(subject=self.subject, type='phone', value_hash=self.phone_hash)

    def test_full_lifecycle_report_dispute_and_public_check_sync(self):
        # 1. Subject starts clean
        res0 = lookup_public_record(self.phone_hash)
        self.assertIsNotNone(res0)
        self.assertFalse(res0['has_active_flags'])
        self.assertEqual(res0['active_reports_count'], 0)
        self.assertEqual(res0['published_reports_count'], 0)
        self.assertEqual(res0['disputed_reports_count'], 0)

        # 2. User submits fraud report (status: 'submitted')
        report = create_fraud_report(
            reporter=self.reporter,
            subject_name="E2E Merchant Ltd",
            subject_type="business",
            title="Non-delivery of goods",
            allegation="Paid invoice, item never shipped."
        )
        # Link report to our registered subject for public CHECK evaluation
        report.target_subject = self.subject
        report.save(update_fields=['target_subject'])

        # Public lookup still clean: unreviewed 'submitted' report is not public
        res1 = lookup_public_record(self.phone_hash)
        self.assertFalse(res1['has_active_flags'])
        self.assertEqual(res1['published_reports_count'], 0)

        # 3. Moderator reviews and publishes report (status: 'published')
        transition_report_state(report, new_state='published', actor=self.moderator)

        # Public lookup IMMEDIATELY shows active flag
        res2 = lookup_public_record(self.phone_hash)
        self.assertTrue(res2['has_active_flags'])
        self.assertEqual(res2['active_reports_count'], 1)
        self.assertEqual(res2['published_reports_count'], 1)
        self.assertEqual(res2['disputed_reports_count'], 0)

        # 4. Target files right-of-response dispute (status: 'disputed')
        dispute = file_dispute_for_report(
            report=report,
            disputant=self.disputant,
            reason="Item delivered via courier waybill #998877."
        )
        report.refresh_from_db()
        self.assertEqual(report.state, 'disputed')

        # Public lookup updates: disputed reports are tracked separately, published active flag is 0
        res3 = lookup_public_record(self.phone_hash)
        self.assertFalse(res3['has_active_flags'])
        self.assertEqual(res3['published_reports_count'], 0)
        self.assertEqual(res3['disputed_reports_count'], 1)

        # 5. Moderator accepts dispute (status: 'restricted' / quarantined)
        resolve_dispute(
            dispute=dispute,
            outcome='accepted',
            actor=self.moderator,
            resolution_notes="Waybill proof verified. Allegation quarantined."
        )
        report.refresh_from_db()
        self.assertEqual(report.state, 'restricted')

        # Public lookup updates: restricted report is completely excluded from flags and counts
        res4 = lookup_public_record(self.phone_hash)
        self.assertFalse(res4['has_active_flags'])
        self.assertEqual(res4['published_reports_count'], 0)
        self.assertEqual(res4['disputed_reports_count'], 0)


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=True,
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'
)
class EndToEndVerificationAndPublicCheckTestCase(TestCase):
    def setUp(self):
        self.requester = User.objects.create_user(
            username='e2e_employer', email='emp@example.com', password='password123', role='employer'
        )
        self.officer = User.objects.create_user(
            username='e2e_officer', email='officer@example.com', password='password123', role='officer'
        )

        # Create SubjectEntity with registered CAC/RC Identifier
        self.cac_raw = "RC123456"
        self.cac_hash = hash_identifier_value('cac', self.cac_raw)
        self.subject = SubjectEntity.objects.create(name="Verified Logistics Ltd", type="business")
        Identifier.objects.create(subject=self.subject, type='cac', value_hash=self.cac_hash)

    def test_full_lifecycle_verification_intake_to_public_check_verified(self):
        # 1. Initially unverified
        res0 = lookup_public_record(self.cac_hash)
        self.assertIsNotNone(res0)
        self.assertFalse(res0['identity_verified'])
        self.assertEqual(res0['verification_label'], "Unverified (No Official Verification on File)")

        # 2. Employer submits verification request referencing CAC
        verif_req = create_verification_request(
            requester=self.requester,
            subject_name="Verified Logistics Ltd",
            subject_type="business",
            verification_type="credential",
            identifier_type='cac',
            identifier_value=self.cac_raw
        )
        self.assertEqual(verif_req.target_subject.id, self.subject.id)
        self.assertEqual(verif_req.status, 'pending')

        # 3. Officer claims and completes review
        claim_verification_request(verif_req.reference_number, self.officer)
        result = complete_verification_request(
            reference_number=verif_req.reference_number,
            officer_user=self.officer,
            outcome='verified',
            summary='Corporate registration active and confirmed in registry.',
            details={'registry_status': 'Active Standing', 'registration_number': 'RC123456'}
        )
        self.assertEqual(result.outcome, 'verified')

        # 4. Requester accesses report document
        self.client.force_login(self.requester)
        report_url = reverse('verification:report', kwargs={'reference_number': verif_req.reference_number})
        resp = self.client.get(report_url)
        self.assertEqual(resp.status_code, 200)

        # Mandatory non-government statutory disclaimer present
        self.assertIn("independent VerifyNG Verification Report", resp.content.decode('utf-8'))
        self.assertIn("does NOT constitute an official government certificate", resp.content.decode('utf-8'))

        # 5. Public CHECK on the CAC hash immediately evaluates as officially verified
        res1 = lookup_public_record(self.cac_hash)
        self.assertTrue(res1['identity_verified'])
        self.assertEqual(res1['verification_label'], "Officially Verified")


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=True,
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'
)
class AdversarialSecurityAndXssTestCase(TestCase):
    def setUp(self):
        self.user_a = User.objects.create_user(
            username='user_a', email='a@example.com', password='password123', role='individual'
        )
        self.user_b = User.objects.create_user(
            username='user_b', email='b@example.com', password='password123', role='individual'
        )
        self.officer = User.objects.create_user(
            username='officer_sec', email='officer@example.com', password='password123', role='officer'
        )
        self.moderator = User.objects.create_user(
            username='mod_sec', email='mod@example.com', password='password123', role='moderator'
        )
        self.superuser = User.objects.create_superuser(
            username='admin_sec', email='admin@example.com', password='password123'
        )

    def test_adversarial_invalid_state_transitions(self):
        # 1. State machine transition: invalid state string raises ValueError
        report = create_fraud_report(
            reporter=self.user_a,
            subject_name="State Test",
            subject_type="person",
            title="Title",
            allegation="Allegation"
        )
        with self.assertRaises(ValueError):
            transition_report_state(report, new_state='nonexistent_state')

        # 2. Verification state machine: completing pending directly raises ValidationError
        verif = create_verification_request(
            requester=self.user_a,
            subject_name="State Verif",
            subject_type="person",
            verification_type="identity"
        )
        with self.assertRaises(ValidationError):
            complete_verification_request(verif.reference_number, self.officer, 'verified', 'Summary')

        # 3. Claiming already claimed verification raises ValidationError
        claim_verification_request(verif.reference_number, self.officer)
        with self.assertRaises(ValidationError):
            claim_verification_request(verif.reference_number, self.officer)

        # 4. Re-completing completed verification raises ValidationError
        complete_verification_request(verif.reference_number, self.officer, 'verified', 'Summary')
        with self.assertRaises(ValidationError):
            complete_verification_request(verif.reference_number, self.officer, 'verified', 'Second attempt')

        # 5. Resolving dispute with invalid outcome raises ValueError
        report.state = 'published'
        report.save()
        dispute = file_dispute_for_report(report, self.user_b, "Dispute statement")
        with self.assertRaises(ValueError):
            resolve_dispute(dispute, outcome='invalid_adjudication', actor=self.moderator, resolution_notes="Notes")

    def test_cross_tenant_confidential_evidence_access(self):
        # Create published report with confidential evidence without external network calls
        report = create_fraud_report(
            reporter=self.user_a,
            subject_name="Evidence Target",
            subject_type="business",
            title="Evidence Report",
            allegation="Allegation with confidential ID"
        )
        transition_report_state(report, 'published', actor=self.moderator)
        evidence = ReportEvidence.objects.create(
            report=report,
            description="Confidential Passport",
            is_confidential=True
        )

        download_url = reverse('reports:evidence_download', kwargs={'evidence_id': evidence.id})

        # 1. Unauthenticated user denied (HTTP 403)
        res_anon = self.client.get(download_url)
        self.assertEqual(res_anon.status_code, 403)

        # 2. Unrelated User B denied (HTTP 403)
        self.client.force_login(self.user_b)
        res_b = self.client.get(download_url)
        self.assertEqual(res_b.status_code, 403)

        # 3. Report Owner (User A) allowed access (attempt to download file; may 404 if file unbacked, but NOT 403)
        self.client.force_login(self.user_a)
        res_a = self.client.get(download_url)
        self.assertNotEqual(res_a.status_code, 403)

        # 4. Moderator allowed access (NOT 403)
        self.client.force_login(self.moderator)
        res_mod = self.client.get(download_url)
        self.assertNotEqual(res_mod.status_code, 403)

        # 5. Superuser allowed access (NOT 403)
        self.client.force_login(self.superuser)
        res_admin = self.client.get(download_url)
        self.assertNotEqual(res_admin.status_code, 403)

    def test_xss_payload_escaped_in_rendered_templates(self):
        xss_payload = "<script>alert('XSS-TEST')</script>"

        # 1. Fraud report allegation with XSS
        report = create_fraud_report(
            reporter=self.user_a,
            subject_name="XSS Target",
            subject_type="person",
            title="XSS Title",
            allegation=f"Normal text {xss_payload} more text"
        )
        transition_report_state(report, 'published', actor=self.moderator)

        detail_url = reverse('reports:detail', kwargs={'reference_number': report.reference_number})
        res_rep = self.client.get(detail_url)
        self.assertEqual(res_rep.status_code, 200)
        rep_html = res_rep.content.decode('utf-8')

        # Raw executable script tags must NOT exist in rendered HTML
        self.assertNotIn("<script>alert('XSS-TEST')</script>", rep_html)
        # HTML-escaped entities must be present
        self.assertIn("&lt;script&gt;", rep_html)

        # 2. Verification findings summary with XSS
        verif = create_verification_request(
            requester=self.user_a,
            subject_name="XSS Entity",
            subject_type="business",
            verification_type="identity"
        )
        claim_verification_request(verif.reference_number, self.officer)
        complete_verification_request(
            reference_number=verif.reference_number,
            officer_user=self.officer,
            outcome='verified',
            summary=f"Findings {xss_payload} concluded."
        )

        self.client.force_login(self.user_a)
        verif_url = reverse('verification:report', kwargs={'reference_number': verif.reference_number})
        res_verif = self.client.get(verif_url)
        self.assertEqual(res_verif.status_code, 200)
        verif_html = res_verif.content.decode('utf-8')

        # Raw executable script tags must NOT exist in printable report HTML
        self.assertNotIn("<script>alert('XSS-TEST')</script>", verif_html)
        self.assertIn("&lt;script&gt;", verif_html)
        


            