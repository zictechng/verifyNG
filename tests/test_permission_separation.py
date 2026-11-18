# tests/test_permission_separation.py
"""
Unit and integration test suite for Permission Separation (Step 3).
Verifies has_basic_identity_access, has_enhanced_identity_access,
has_verified_business_access, is_profile_verified backward compatibility,
VerificationResult truthiness/unpacking, and decorator/mixin gating.
"""
from django.test import TestCase, RequestFactory
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages.storage.fallback import FallbackStorage
from django.http import HttpResponse

from users.models import User
from employer.models import EmployerProfile, TeamMember
from core.permissions import (
    VerificationResult,
    has_basic_identity_access,
    has_enhanced_identity_access,
    has_verified_business_access,
    is_profile_verified,
    basic_identity_required,
    enhanced_identity_required,
    verified_business_required,
)


class VerificationResultTests(TestCase):
    def test_truthiness_and_boolean_behavior(self):
        """Verifies VerificationResult never evaluates as a truthy tuple when allowed=False."""
        denied = VerificationResult(False, "Access Denied")
        allowed = VerificationResult(True, "")

        self.assertFalse(bool(denied))
        self.assertTrue(bool(allowed))

        # Direct conditional evaluation
        branch_denied = "allowed" if denied else "denied"
        self.assertEqual(branch_denied, "denied")

        branch_allowed = "allowed" if allowed else "denied"
        self.assertEqual(branch_allowed, "allowed")

        # Boolean comparison
        self.assertEqual(denied, False)
        self.assertNotEqual(denied, True)
        self.assertEqual(allowed, True)
        self.assertNotEqual(allowed, False)

    def test_tuple_unpacking(self):
        """Verifies VerificationResult unpacks cleanly into (allowed, reason)."""
        denied = VerificationResult(False, "Needs Review")
        is_allowed, reason = denied
        self.assertFalse(is_allowed)
        self.assertEqual(reason, "Needs Review")

        allowed = VerificationResult(True, "")
        is_allowed, reason = allowed
        self.assertTrue(is_allowed)
        self.assertEqual(reason, "")


class PermissionSeparationTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

        # Regular individual candidates
        self.unverified_user = User.objects.create_user(
            username='unverified_joe',
            email='joe@verifyng.local',
            password='Password123!',
            role='candidate'
        )
        self.basic_user = User.objects.create_user(
            username='basic_sam',
            email='sam@verifyng.local',
            password='Password123!',
            role='candidate',
            assurance_level='basic_verified',
            identity_verified=True,
            id_verification_status='verified'
        )
        self.enhanced_user = User.objects.create_user(
            username='enhanced_alice',
            email='alice@verifyng.local',
            password='Password123!',
            role='candidate',
            assurance_level='enhanced_verified',
            identity_verified=True,
            id_verification_status='verified'
        )

        # Admin & Officer
        self.admin = User.objects.create_superuser(
            username='admin_boss',
            email='boss@verifyng.local',
            password='Password123!',
            role='ADMIN'
        )
        self.officer = User.objects.create_user(
            username='compliance_cop',
            email='cop@verifyng.local',
            password='Password123!',
            role='officer'
        )

        # Employers
        self.verified_employer_user = User.objects.create_user(
            username='corp_verified',
            email='corp@verifyng.local',
            password='Password123!',
            role='employer'
        )
        self.verified_employer_profile = EmployerProfile.objects.create(
            user=self.verified_employer_user,
            company_name="Acme Global Ltd",
            registration_type="cac",
            company_rc_number="RC-998877",
            is_verified=True,
            verification_status="verified"
        )

        self.unverified_employer_user = User.objects.create_user(
            username='corp_unverified',
            email='corp_unver@verifyng.local',
            password='Password123!',
            role='employer'
        )
        self.unverified_employer_profile = EmployerProfile.objects.create(
            user=self.unverified_employer_user,
            company_name="Pending Startups Ltd",
            registration_type="cac",
            company_rc_number="RC-112233",
            is_verified=False,
            verification_status="pending"
        )

    def test_anonymous_and_blocked_users(self):
        """Unauthenticated, inactive, and suspended accounts are strictly denied."""
        anon = AnonymousUser()
        for func in (has_basic_identity_access, has_enhanced_identity_access, has_verified_business_access):
            res = func(anon)
            self.assertFalse(res)
            self.assertIn("Authentication is required", res.reason)

        # Deactivated user
        self.basic_user.is_active = False
        res = has_basic_identity_access(self.basic_user)
        self.assertFalse(res)
        self.assertIn("deactivated", res.reason)

        # Suspended user
        self.basic_user.is_active = True
        self.basic_user.is_suspended = True
        res = has_basic_identity_access(self.basic_user)
        self.assertFalse(res)
        self.assertIn("suspended", res.reason)

    def test_administrative_bypass(self):
        """Superusers and verification officers bypass identity checks."""
        for admin_user in (self.admin, self.officer):
            self.assertTrue(has_basic_identity_access(admin_user))
            self.assertTrue(has_enhanced_identity_access(admin_user))
            self.assertTrue(has_verified_business_access(admin_user))

    def test_basic_identity_access_qualification(self):
        """Tests basic access tier for basic, enhanced, and unverified users."""
        self.assertFalse(has_basic_identity_access(self.unverified_user))
        self.assertTrue(has_basic_identity_access(self.basic_user))
        self.assertTrue(has_basic_identity_access(self.enhanced_user))

        # Rejected user
        self.basic_user.id_verification_status = 'rejected'
        self.basic_user.identity_verified = False
        self.basic_user.save(update_fields=['id_verification_status', 'identity_verified'])
        res = has_basic_identity_access(self.basic_user)
        self.assertFalse(res)
        self.assertIn("declined by compliance", res.reason)

        # Expired user
        self.basic_user.id_verification_status = 'expired'
        self.basic_user.save(update_fields=['id_verification_status', 'identity_verified'])
        res = has_basic_identity_access(self.basic_user)
        self.assertFalse(res)
        self.assertIn("expired", res.reason)

    def test_enhanced_identity_access_qualification(self):
        """Enhanced access strictly requires enhanced_verified tier."""
        # Basic user cannot access enhanced tier
        res = has_enhanced_identity_access(self.basic_user)
        self.assertFalse(res)
        self.assertIn("Enhanced identity verification required", res.reason)

        # Enhanced user succeeds
        self.assertTrue(has_enhanced_identity_access(self.enhanced_user))

        # Suspended enhanced user is blocked
        self.enhanced_user.id_verification_status = 'suspended'
        self.enhanced_user.identity_verified = False
        res = has_enhanced_identity_access(self.enhanced_user)
        self.assertFalse(res)
        self.assertIn("suspended", res.reason)

    def test_verified_business_access_qualification(self):
        """Business access strictly separates individual identity from corporate entity."""
        # Candidate with enhanced personal ID cannot access business features
        res = has_verified_business_access(self.enhanced_user)
        self.assertFalse(res)
        self.assertIn("Employer or business account required", res.reason)

        # Verified employer succeeds
        self.assertTrue(has_verified_business_access(self.verified_employer_user))

        # Pending employer is blocked
        res = has_verified_business_access(self.unverified_employer_user)
        self.assertFalse(res)
        self.assertIn("under compliance review", res.reason)

        # Team member of verified employer succeeds
        team_member = User.objects.create_user(
            username='team_member_bob',
            email='bob@verifyng.local',
            password='Password123!',
            role='employer'
        )
        TeamMember.objects.create(
            employer=self.verified_employer_profile,
            user=team_member,
            is_active=True
        )
        self.assertTrue(has_verified_business_access(team_member))

    def test_is_profile_verified_backward_compatibility(self):
        """
        is_profile_verified must unpack as (bool, str) AND evaluate as a Boolean,
        delegating individuals to basic identity and employers to business access.
        """
        # Individual unverified
        verified, msg = is_profile_verified(self.unverified_user)
        self.assertFalse(verified)
        self.assertFalse(is_profile_verified(self.unverified_user))

        # Individual basic verified
        verified, msg = is_profile_verified(self.basic_user)
        self.assertTrue(verified)
        self.assertTrue(is_profile_verified(self.basic_user))

        # Employer unverified
        verified, msg = is_profile_verified(self.unverified_employer_user)
        self.assertFalse(verified)
        self.assertFalse(is_profile_verified(self.unverified_employer_user))

        # Employer verified
        verified, msg = is_profile_verified(self.verified_employer_user)
        self.assertTrue(verified)
        self.assertTrue(is_profile_verified(self.verified_employer_user))


class DecoratorAndMixinTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.unverified = User.objects.create_user(
            username='dec_unver', email='dec_unver@verifyng.local', password='Password123!'
        )
        self.basic = User.objects.create_user(
            username='dec_basic', email='dec_basic@verifyng.local', password='Password123!',
            assurance_level='basic_verified', identity_verified=True, id_verification_status='verified'
        )
        self.enhanced = User.objects.create_user(
            username='dec_enh', email='dec_enh@verifyng.local', password='Password123!',
            assurance_level='enhanced_verified', identity_verified=True, id_verification_status='verified'
        )
        self.employer = User.objects.create_user(
            username='dec_emp', email='dec_emp@verifyng.local', password='Password123!',
            role='employer'
        )
        EmployerProfile.objects.create(
            user=self.employer, company_name="Test Corp", is_verified=True, verification_status="verified"
        )

    def _setup_request(self, user):
        req = self.factory.get('/dummy/')
        req.user = user
        # Attach messages storage
        setattr(req, 'session', {})
        messages = FallbackStorage(req)
        setattr(req, '_messages', messages)
        return req

    def test_basic_identity_decorator(self):
        @basic_identity_required
        def dummy_view(request):
            return HttpResponse("OK")

        # Unverified gets redirected to profile
        req = self._setup_request(self.unverified)
        res = dummy_view(req)
        self.assertEqual(res.status_code, 302)
        self.assertIn('/profile/', res.url)

        # Basic user gets HTTP 200
        req = self._setup_request(self.basic)
        res = dummy_view(req)
        self.assertEqual(res.status_code, 200)

    def test_enhanced_identity_decorator(self):
        @enhanced_identity_required
        def dummy_view(request):
            return HttpResponse("OK")

        # Basic user is redirected
        req = self._setup_request(self.basic)
        res = dummy_view(req)
        self.assertEqual(res.status_code, 302)

        # Enhanced user gets HTTP 200
        req = self._setup_request(self.enhanced)
        res = dummy_view(req)
        self.assertEqual(res.status_code, 200)

    def test_verified_business_decorator(self):
        @verified_business_required
        def dummy_view(request):
            return HttpResponse("OK")

        # Individual basic user is redirected
        req = self._setup_request(self.basic)
        res = dummy_view(req)
        self.assertEqual(res.status_code, 302)

        # Verified employer gets HTTP 200
        req = self._setup_request(self.employer)
        res = dummy_view(req)
        self.assertEqual(res.status_code, 200)
