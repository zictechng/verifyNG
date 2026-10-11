
# tests/test_views.py
"""
Batch 14.7 — Dashboard views, verification views, and core RBAC permission helpers.

Coverage:
  Dashboard:
    - login required
    - authenticated user sees dashboard
    - stat counts in context (reports, verifications, disputes)
    - moderator context flags present for moderator user

  Core permissions (core.permissions):
    - is_moderator: superuser, staff, role='moderator', anonymous, regular user
    - is_verification_officer: role='officer' only, not staff/superuser
    - can_view_report: moderator sees all, reporter sees own (not archived), public sees published only
    - can_view_evidence: respects is_confidential + can_view_report chain

  Verification views:
    - list view: login required, shows user's own requests
    - create view: login required, page renders
    - detail view: login required, requester can view own, third-party denied
    - officer_queue: anonymous → redirect, regular user → 403, officer → 200
    - officer_claim: regular user → 403
    - report document: only available for completed request with result
"""

from unittest.mock import patch, MagicMock

from django.test import TestCase, Client
from django.urls import reverse

from users.models import User
from identities.models import SubjectEntity
from reports.models import FraudReport, Dispute
from verification.models import VerificationRequest, VerificationResult


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_user(username='testuser', email='test@example.com', password='StrongPass123!',
              role='user', is_staff=False, is_superuser=False, identity_verified=True):
    u = User.objects.create_user(
        username=username, email=email, password=password,
        is_staff=is_staff, is_superuser=is_superuser,
    )
    u.role = role
    u.identity_verified = identity_verified
    u.save(update_fields=['role', 'identity_verified'])
    return u


def make_subject(name='Test Subject', entity_type='person'):
    return SubjectEntity.objects.create(name=name, type=entity_type)


def make_verification_request(requester, subject=None, status='pending'):
    if subject is None:
        subject = make_subject()
    return VerificationRequest.objects.create(
        requester=requester,
        target_subject=subject,
        verification_type='identity',
        status=status,
        reference_number=f'VRF-{requester.username.upper()}-001',
    )


# ─── Core RBAC — is_moderator ─────────────────────────────────────────────────

class IsModeratorTest(TestCase):

    def _call(self, user):
        from core.permissions import is_moderator
        return is_moderator(user)

    def test_superuser_is_moderator(self):
        u = make_user(username='su', email='su@x.com', is_superuser=True)
        self.assertTrue(self._call(u))

    def test_staff_is_moderator(self):
        u = make_user(username='st', email='st@x.com', is_staff=True)
        self.assertTrue(self._call(u))

    def test_role_moderator_is_moderator(self):
        u = make_user(username='mod', email='mod@x.com', role='moderator')
        self.assertTrue(self._call(u))

    def test_regular_user_not_moderator(self):
        u = make_user(username='reg', email='reg@x.com', role='user')
        self.assertFalse(self._call(u))

    def test_anonymous_user_not_moderator(self):
        from django.contrib.auth.models import AnonymousUser
        self.assertFalse(self._call(AnonymousUser()))

    def test_none_not_moderator(self):
        self.assertFalse(self._call(None))


# ─── Core RBAC — is_verification_officer ──────────────────────────────────────

class IsVerificationOfficerTest(TestCase):

    def _call(self, user):
        from core.permissions import is_verification_officer
        return is_verification_officer(user)

    def test_officer_role_is_officer(self):
        u = make_user(username='off', email='off@x.com', role='officer')
        self.assertTrue(self._call(u))

    def test_superuser_not_automatically_officer(self):
        """Superuser does NOT get officer role automatically — explicit role only."""
        u = make_user(username='su2', email='su2@x.com', is_superuser=True)
        self.assertFalse(self._call(u))

    def test_staff_not_automatically_officer(self):
        u = make_user(username='st2', email='st2@x.com', is_staff=True)
        self.assertFalse(self._call(u))

    def test_regular_user_not_officer(self):
        u = make_user(username='reg2', email='reg2@x.com', role='user')
        self.assertFalse(self._call(u))

    def test_none_not_officer(self):
        self.assertFalse(self._call(None))


# ─── Core RBAC — can_view_report ──────────────────────────────────────────────

class CanViewReportTest(TestCase):

    def setUp(self):
        from identities.models import SubjectEntity
        from reports.services import generate_report_reference_number
        self.reporter = make_user(username='reporter', email='reporter@x.com')
        self.other = make_user(username='other', email='other@x.com')
        self.moderator = make_user(username='modview', email='modview@x.com', role='moderator')
        subject = SubjectEntity.objects.create(name='Suspect', type='person')

        def _make(state):
            r = FraudReport(
                reference_number=generate_report_reference_number(),
                reporter=self.reporter,
                target_subject=subject,
                title='Test', allegation='Allegation.',
                state=state,
            )
            r._audit_logged = True
            r.save()
            return r

        self.published = _make('published')
        self.submitted = _make('submitted')
        self.archived  = _make('archived')

    def _call(self, user, report):
        from core.permissions import can_view_report
        return can_view_report(user, report)

    def test_moderator_views_any_state(self):
        self.assertTrue(self._call(self.moderator, self.submitted))
        self.assertTrue(self._call(self.moderator, self.archived))

    def test_reporter_views_own_submitted(self):
        self.assertTrue(self._call(self.reporter, self.submitted))

    def test_reporter_cannot_view_own_archived(self):
        self.assertFalse(self._call(self.reporter, self.archived))

    def test_public_views_published_only(self):
        self.assertTrue(self._call(self.other, self.published))

    def test_public_cannot_view_submitted(self):
        self.assertFalse(self._call(self.other, self.submitted))

    def test_none_report_returns_false(self):
        self.assertFalse(self._call(self.other, None))


# ─── Core RBAC — can_view_evidence ────────────────────────────────────────────

class CanViewEvidenceTest(TestCase):

    def setUp(self):
        from identities.models import SubjectEntity
        from reports.models import ReportEvidence
        from reports.services import generate_report_reference_number

        self.reporter = make_user(username='evreporter', email='evr@x.com')
        self.moderator = make_user(username='evmod', email='evm@x.com', role='moderator')
        self.other = make_user(username='evother', email='evo@x.com')

        subject = SubjectEntity.objects.create(name='EvidenceSubject', type='person')
        report = FraudReport(
            reference_number=generate_report_reference_number(),
            reporter=self.reporter,
            target_subject=subject,
            title='Ev Test', allegation='Allegation.',
            state='published',
        )
        report._audit_logged = True
        report.save()

        self.public_evidence = ReportEvidence.objects.create(
            report=report, file_type='screenshot',
            file='evidence/test/public.png',
            description='Public ev', is_confidential=False,
        )
        self.confidential_evidence = ReportEvidence.objects.create(
            report=report, file_type='document',
            file='evidence/test/confidential.pdf',
            description='Confidential ev', is_confidential=True,
        )

    def _call(self, user, evidence):
        from core.permissions import can_view_evidence
        return can_view_evidence(user, evidence)

    def test_moderator_views_confidential(self):
        self.assertTrue(self._call(self.moderator, self.confidential_evidence))

    def test_reporter_views_own_confidential(self):
        self.assertTrue(self._call(self.reporter, self.confidential_evidence))

    def test_other_user_cannot_view_confidential(self):
        self.assertFalse(self._call(self.other, self.confidential_evidence))

    def test_other_user_views_public_evidence(self):
        self.assertTrue(self._call(self.other, self.public_evidence))

    def test_none_evidence_returns_false(self):
        self.assertFalse(self._call(self.other, None))


# ─── Dashboard views ──────────────────────────────────────────────────────────

class DashboardIndexViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.url = reverse('dashboard:index')

    def test_anonymous_redirected_to_login(self):
        response = self.client.get(self.url, follow=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response['Location'])

    def test_authenticated_user_gets_200(self):
        user = make_user(username='dashuser', email='dash@x.com')
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_stat_counts_in_context(self):
        user = make_user(username='dashstat', email='dashstat@x.com')
        self.client.force_login(user)
        response = self.client.get(self.url)
        for key in ('total_reports', 'total_verifications', 'total_disputes', 'completed_verifications'):
            self.assertIn(key, response.context, f"Context missing key: {key}")

    def test_moderator_context_flags_set(self):
        mod = make_user(username='dashmod', email='dashmod@x.com', role='moderator')
        self.client.force_login(mod)
        response = self.client.get(self.url)
        self.assertTrue(response.context.get('is_moderator'))

    def test_regular_user_not_moderator_in_context(self):
        user = make_user(username='dashregular', email='dashregular@x.com')
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertFalse(response.context.get('is_moderator'))


# ─── Verification list view ───────────────────────────────────────────────────

class VerificationListViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.url = reverse('verification:list')

    def test_anonymous_redirected(self):
        response = self.client.get(self.url, follow=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response['Location'])

    def test_authenticated_user_sees_list(self):
        user = make_user(username='vlist', email='vlist@x.com')
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_user_only_sees_own_requests(self):
        user1 = make_user(username='vlist1', email='vl1@x.com')
        user2 = make_user(username='vlist2', email='vl2@x.com')
        make_verification_request(user1)
        self.client.force_login(user2)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(list(response.context['requests'])), 0)

    def test_stat_counts_in_context(self):
        user = make_user(username='vliststat', email='vlstat@x.com')
        make_verification_request(user)
        self.client.force_login(user)
        response = self.client.get(self.url)
        for key in ('pending_count', 'in_progress_count', 'completed_count'):
            self.assertIn(key, response.context)


# ─── Verification create view ─────────────────────────────────────────────────

class VerificationCreateViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.url = reverse('verification:create')

    def test_anonymous_redirected(self):
        response = self.client.get(self.url, follow=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response['Location'])

    def test_authenticated_user_sees_form(self):
        user = make_user(username='vcreate', email='vcreate@x.com')
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)


# ─── Verification detail view ─────────────────────────────────────────────────

class VerificationDetailViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.requester = make_user(username='vdetail', email='vdetail@x.com')
        self.other = make_user(username='vother', email='vother@x.com')
        self.vreq = make_verification_request(self.requester)
        self.url = reverse('verification:detail',
                           kwargs={'reference_number': self.vreq.reference_number})

    def test_anonymous_redirected(self):
        response = self.client.get(self.url, follow=False)
        self.assertEqual(response.status_code, 302)

    def test_requester_can_view_own_request(self):
        self.client.force_login(self.requester)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_third_party_user_denied(self):
        self.client.force_login(self.other)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_officer_can_view_any_request(self):
        officer = make_user(username='vofficer', email='vofficer@x.com', role='officer')
        self.client.force_login(officer)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)


# ─── Officer queue view ───────────────────────────────────────────────────────

class OfficerQueueViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.url = reverse('verification:officer_queue')

    def test_anonymous_redirected(self):
        response = self.client.get(self.url, follow=False)
        self.assertEqual(response.status_code, 302)

    def test_regular_user_denied(self):
        user = make_user(username='qreg', email='qreg@x.com')
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)

    def test_officer_sees_queue(self):
        officer = make_user(username='qofficer', email='qoff@x.com', role='officer')
        self.client.force_login(officer)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_superuser_sees_queue(self):
        su = make_user(username='qsu', email='qsu@x.com', is_superuser=True)
        self.client.force_login(su)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)


# ─── Officer claim view ───────────────────────────────────────────────────────

class OfficerClaimViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.requester = make_user(username='claimreq', email='claimreq@x.com')
        self.vreq = make_verification_request(self.requester)
        self.url = reverse('verification:officer_claim',
                           kwargs={'reference_number': self.vreq.reference_number})

    def test_regular_user_denied(self):
        user = make_user(username='claimreg', email='claimreg@x.com')
        self.client.force_login(user)
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 403)

    def test_anonymous_redirected(self):
        response = self.client.post(self.url, follow=False)
        self.assertEqual(response.status_code, 302)


# ─── Verification report document view ────────────────────────────────────────

class VerificationReportDocumentViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.requester = make_user(username='rptreq', email='rptreq@x.com')
        self.other = make_user(username='rptother', email='rptother@x.com')

    def _make_completed_request(self, requester):
        vreq = make_verification_request(requester, status='completed')
        officer = make_user(username='rptofficer', email='rptofficer@x.com', role='officer')
        VerificationResult.objects.create(
            request=vreq,
            outcome='verified',
            summary='All checks passed.',
            verified_by=officer,
            details={},
        )
        return vreq

    def test_anonymous_redirected(self):
        vreq = self._make_completed_request(self.requester)
        url = reverse('verification:report', kwargs={'reference_number': vreq.reference_number})
        response = self.client.get(url, follow=False)
        self.assertEqual(response.status_code, 302)

    def test_requester_can_view_completed_report(self):
        vreq = self._make_completed_request(self.requester)
        url = reverse('verification:report', kwargs={'reference_number': vreq.reference_number})
        self.client.force_login(self.requester)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_third_party_denied(self):
        vreq = self._make_completed_request(self.requester)
        url = reverse('verification:report', kwargs={'reference_number': vreq.reference_number})
        self.client.force_login(self.other)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

    def test_pending_request_returns_404(self):
        vreq = make_verification_request(self.requester, status='pending')
        url = reverse('verification:report', kwargs={'reference_number': vreq.reference_number})
        self.client.force_login(self.requester)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)
