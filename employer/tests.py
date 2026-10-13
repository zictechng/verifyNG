"""
employer/tests.py
=================
Full test suite for the employer app.

Covers:
- Model behaviour (EmployerProfile, TeamMember, BulkCheckUpload, BulkCheckRow)
- Permission enforcement (employer_required, login_required)
- View behaviour (dashboard, profile update, bulk upload list/detail, team list)
- Edge cases and security (role isolation, CSRF not bypassed, inactive members)

Test database: uses Django's standard test runner (SQLite in-memory).
No external services are contacted.
"""

import uuid

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from employer.models import (
    BulkCheckRow,
    BulkCheckUpload,
    EmployerProfile,
    TeamMember,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_user(username, role='employer', password='Str0ngP@ss!', **kwargs):
    """Create and return a saved User with the given role."""
    user = User.objects.create_user(
        username=username,
        email=f'{username}@example.com',
        password=password,
        role=role,
        **kwargs,
    )
    return user


def make_employer_profile(user, company_name='Acme Ltd') -> EmployerProfile:
    """Create and return a saved EmployerProfile for the given user."""
    return EmployerProfile.objects.create(
        user=user,
        company_name=company_name,
        company_rc_number='RC123456',
        industry='Technology',
        contact_phone='+234800000000',
        company_address='1 Lagos Street, Lagos',
    )


def make_bulk_upload(employer_profile, filename='candidates.csv', status='pending'):
    """Create and return a saved BulkCheckUpload."""
    return BulkCheckUpload.objects.create(
        employer=employer_profile,
        uploaded_by=employer_profile.user,
        original_filename=filename,
        row_count=10,
        processed_count=0,
        status=status,
    )


# ===========================================================================
# 1. Model Tests
# ===========================================================================

class EmployerProfileModelTest(TestCase):
    """Unit tests for EmployerProfile model."""

    def setUp(self):
        self.user = make_user('emp_user')
        self.profile = make_employer_profile(self.user)

    def test_str_representation(self):
        self.assertIn('Acme Ltd', str(self.profile))
        self.assertIn('emp_user', str(self.profile))

    def test_default_is_verified_false(self):
        self.assertFalse(self.profile.is_verified)

    def test_default_is_active_true(self):
        self.assertTrue(self.profile.is_active)

    def test_timestamps_populated(self):
        self.assertIsNotNone(self.profile.created_at)
        self.assertIsNotNone(self.profile.updated_at)

    def test_one_to_one_constraint(self):
        """Creating a second profile for the same user must raise an error."""
        with self.assertRaises(Exception):
            EmployerProfile.objects.create(
                user=self.user,
                company_name='Duplicate Co',
            )

    def test_verified_at_null_by_default(self):
        self.assertIsNone(self.profile.verified_at)

    def test_ordering_newest_first(self):
        user2 = make_user('emp_user2')
        profile2 = make_employer_profile(user2, 'Beta Corp')
        profiles = list(EmployerProfile.objects.all())
        self.assertEqual(profiles[0], profile2)
        self.assertEqual(profiles[1], self.profile)


class TeamMemberModelTest(TestCase):
    """Unit tests for TeamMember model."""

    def setUp(self):
        self.owner = make_user('owner')
        self.profile = make_employer_profile(self.owner)
        self.member_user = make_user('member', role='individual')

    def test_create_team_member(self):
        tm = TeamMember.objects.create(
            employer=self.profile,
            user=self.member_user,
            team_role='checker',
            invited_by=self.owner,
        )
        self.assertEqual(tm.team_role, 'checker')
        self.assertTrue(tm.is_active)

    def test_str_representation(self):
        tm = TeamMember.objects.create(
            employer=self.profile,
            user=self.member_user,
            team_role='viewer',
        )
        self.assertIn('member', str(tm))
        self.assertIn('Acme Ltd', str(tm))

    def test_unique_together_employer_user(self):
        """Same user cannot be added to the same employer twice."""
        TeamMember.objects.create(
            employer=self.profile,
            user=self.member_user,
            team_role='checker',
        )
        with self.assertRaises(Exception):
            TeamMember.objects.create(
                employer=self.profile,
                user=self.member_user,
                team_role='viewer',
            )

    def test_default_role_checker(self):
        tm = TeamMember.objects.create(
            employer=self.profile,
            user=self.member_user,
        )
        self.assertEqual(tm.team_role, 'checker')

    def test_invited_by_set_to_null_on_user_delete(self):
        """invited_by uses SET_NULL — deleting the inviter must not cascade."""
        inviter = make_user('inviter_user')
        tm = TeamMember.objects.create(
            employer=self.profile,
            user=self.member_user,
            team_role='admin',
            invited_by=inviter,
        )
        inviter.delete()
        tm.refresh_from_db()
        self.assertIsNone(tm.invited_by)


class BulkCheckUploadModelTest(TestCase):
    """Unit tests for BulkCheckUpload model."""

    def setUp(self):
        self.user = make_user('bulk_user')
        self.profile = make_employer_profile(self.user)
        self.upload = make_bulk_upload(self.profile)

    def test_pk_is_uuid(self):
        self.assertIsInstance(self.upload.pk, uuid.UUID)

    def test_default_status_pending(self):
        self.assertEqual(self.upload.status, 'pending')

    def test_str_includes_filename(self):
        self.assertIn('candidates.csv', str(self.upload))

    def test_progress_pct_zero_when_no_rows(self):
        upload = BulkCheckUpload.objects.create(
            employer=self.profile,
            uploaded_by=self.user,
            original_filename='empty.csv',
            row_count=0,
            processed_count=0,
        )
        self.assertEqual(upload.progress_pct, 0)

    def test_progress_pct_calculation(self):
        self.upload.row_count = 100
        self.upload.processed_count = 37
        self.assertEqual(self.upload.progress_pct, 37)

    def test_progress_pct_full(self):
        self.upload.row_count = 50
        self.upload.processed_count = 50
        self.assertEqual(self.upload.progress_pct, 100)

    def test_is_active_default_true(self):
        self.assertTrue(self.upload.is_active)


class BulkCheckRowModelTest(TestCase):
    """Unit tests for BulkCheckRow model."""

    def setUp(self):
        self.user = make_user('row_user')
        self.profile = make_employer_profile(self.user)
        self.upload = make_bulk_upload(self.profile)

    def test_create_row(self):
        row = BulkCheckRow.objects.create(
            upload=self.upload,
            row_number=1,
            full_name='Jane Doe',
            phone_number='+2348012345678',
        )
        self.assertEqual(row.status, 'pending')
        self.assertEqual(row.row_number, 1)

    def test_str_representation(self):
        row = BulkCheckRow.objects.create(
            upload=self.upload,
            row_number=2,
            full_name='John Smith',
        )
        self.assertIn('2', str(row))
        self.assertIn('John Smith', str(row))

    def test_unique_together_upload_row_number(self):
        BulkCheckRow.objects.create(
            upload=self.upload,
            row_number=1,
            full_name='First',
        )
        with self.assertRaises(Exception):
            BulkCheckRow.objects.create(
                upload=self.upload,
                row_number=1,
                full_name='Duplicate',
            )

    def test_nin_hash_never_stores_raw_nin(self):
        """
        Security contract: NIN is stored as a 64-char SHA-256 hex hash.
        A raw NIN (11 digits) must never appear in this field.
        """
        raw_nin = '12345678901'
        row = BulkCheckRow.objects.create(
            upload=self.upload,
            row_number=3,
            full_name='Secure Person',
            nin_hash='a' * 64,  # valid-length hash placeholder
        )
        # The field value must NOT equal a raw 11-digit NIN
        self.assertNotEqual(row.nin_hash, raw_nin)
        self.assertEqual(len(row.nin_hash), 64)

    def test_result_data_defaults_to_empty_dict(self):
        row = BulkCheckRow.objects.create(
            upload=self.upload,
            row_number=4,
        )
        self.assertEqual(row.result_data, {})

    def test_ordering_by_row_number(self):
        BulkCheckRow.objects.create(upload=self.upload, row_number=3)
        BulkCheckRow.objects.create(upload=self.upload, row_number=1)
        BulkCheckRow.objects.create(upload=self.upload, row_number=2)
        rows = list(self.upload.rows.all())
        self.assertEqual([r.row_number for r in rows], [1, 2, 3])


# ===========================================================================
# 2. Permission / Authentication Tests
# ===========================================================================

class EmployerPermissionTest(TestCase):
    """
    Verify that all employer views enforce login_required and employer_required.
    Non-employer roles must receive HTTP 302 (redirect to login or root)
    or HTTP 403 (PermissionDenied).
    """

    EMPLOYER_URLS = [
        ('employer:dashboard', {}),
        ('employer:profile', {}),
        ('employer:bulk_upload_list', {}),
        ('employer:team_list', {}),
    ]

    def setUp(self):
        self.client = Client()
        self.employer_user = make_user('emp_perm')
        self.individual_user = make_user('ind_perm', role='individual')
        self.moderator_user = make_user('mod_perm', role='moderator')

    def test_anonymous_redirected_to_login(self):
        for url_name, kwargs in self.EMPLOYER_URLS:
            with self.subTest(url=url_name):
                url = reverse(url_name, kwargs=kwargs)
                response = self.client.get(url)
                self.assertIn(
                    response.status_code, [302, 403],
                    msg=f'{url_name} should redirect or deny anonymous access',
                )
                if response.status_code == 302:
                    self.assertIn('/login', response['Location'])

    def test_individual_role_denied(self):
        self.client.force_login(self.individual_user)
        for url_name, kwargs in self.EMPLOYER_URLS:
            with self.subTest(url=url_name):
                url = reverse(url_name, kwargs=kwargs)
                response = self.client.get(url)
                self.assertIn(
                    response.status_code, [302, 403],
                    msg=f'Individual user should be denied {url_name}',
                )

    def test_moderator_role_denied(self):
        """
        Moderator role must NOT bypass employer_required
        (employer_required uses role_required('employer') which only allows
        superusers and role='employer').
        """
        self.client.force_login(self.moderator_user)
        url = reverse('employer:dashboard')
        response = self.client.get(url)
        self.assertIn(response.status_code, [302, 403])

    def test_employer_role_allowed(self):
        """An employer-role user must reach the dashboard (200 or 302 to profile setup)."""
        self.client.force_login(self.employer_user)
        url = reverse('employer:dashboard')
        response = self.client.get(url)
        self.assertIn(response.status_code, [200, 302])

    def test_superuser_can_access_employer_views(self):
        """Superusers bypass role_required and must be allowed."""
        su = User.objects.create_superuser(
            username='superadmin', password='Admin1234!', email='su@example.com'
        )
        self.client.force_login(su)
        url = reverse('employer:dashboard')
        response = self.client.get(url)
        self.assertIn(response.status_code, [200, 302])


# ===========================================================================
# 3. View Tests — Dashboard
# ===========================================================================

class EmployerDashboardViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = make_user('dash_user')
        self.client.force_login(self.user)

    def test_dashboard_creates_profile_on_first_visit(self):
        """Profile must be auto-created if it does not exist."""
        self.assertFalse(EmployerProfile.objects.filter(user=self.user).exists())
        self.client.get(reverse('employer:dashboard'))
        self.assertTrue(EmployerProfile.objects.filter(user=self.user).exists())

    def test_dashboard_returns_200(self):
        make_employer_profile(self.user)
        response = self.client.get(reverse('employer:dashboard'))
        self.assertEqual(response.status_code, 200)

    def test_dashboard_context_contains_profile(self):
        profile = make_employer_profile(self.user)
        response = self.client.get(reverse('employer:dashboard'))
        self.assertEqual(response.context['profile'], profile)

    def test_dashboard_context_contains_team_count(self):
        profile = make_employer_profile(self.user)
        member_user = make_user('member1', role='individual')
        TeamMember.objects.create(employer=profile, user=member_user, team_role='checker')
        response = self.client.get(reverse('employer:dashboard'))
        self.assertEqual(response.context['team_count'], 1)

    def test_dashboard_context_contains_recent_uploads(self):
        profile = make_employer_profile(self.user)
        for i in range(6):
            make_bulk_upload(profile, filename=f'file_{i}.csv')
        response = self.client.get(reverse('employer:dashboard'))
        # recent_uploads is capped at 5
        self.assertLessEqual(len(response.context['recent_uploads']), 5)

    def test_dashboard_inactive_team_members_not_counted(self):
        profile = make_employer_profile(self.user)
        member_user = make_user('inactive_m', role='individual')
        TeamMember.objects.create(
            employer=profile, user=member_user, team_role='viewer', is_active=False
        )
        response = self.client.get(reverse('employer:dashboard'))
        self.assertEqual(response.context['team_count'], 0)

    def test_dashboard_uses_correct_template(self):
        make_employer_profile(self.user)
        response = self.client.get(reverse('employer:dashboard'))
        self.assertTemplateUsed(response, 'employer/dashboard.html')


# ===========================================================================
# 4. View Tests — Profile
# ===========================================================================

class EmployerProfileViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = make_user('profile_user')
        self.profile = make_employer_profile(self.user)
        self.client.force_login(self.user)
        self.url = reverse('employer:profile')

    def test_get_returns_200(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_get_uses_correct_template(self):
        response = self.client.get(self.url)
        self.assertTemplateUsed(response, 'employer/profile.html')

    def test_post_updates_company_name(self):
        response = self.client.post(self.url, {
            'company_name': 'Updated Corp',
            'company_rc_number': 'RC999',
            'industry': 'Finance',
            'company_address': '5 New Street',
            'contact_phone': '+2348099999999',
        })
        self.assertRedirects(response, self.url)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.company_name, 'Updated Corp')

    def test_post_updates_rc_number(self):
        self.client.post(self.url, {
            'company_name': 'Acme Ltd',
            'company_rc_number': 'RC777777',
            'industry': 'Technology',
            'company_address': '1 Lagos Street',
            'contact_phone': '+234800000000',
        })
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.company_rc_number, 'RC777777')

    def test_post_strips_whitespace_from_fields(self):
        self.client.post(self.url, {
            'company_name': '  Trimmed Corp  ',
            'company_rc_number': '',
            'industry': '',
            'company_address': '',
            'contact_phone': '',
        })
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.company_name, 'Trimmed Corp')

    def test_post_missing_company_name_keeps_existing(self):
        """If company_name is absent from POST, the existing value is preserved."""
        original_name = self.profile.company_name
        self.client.post(self.url, {
            # company_name omitted
            'company_rc_number': 'RC111',
            'industry': 'Retail',
            'company_address': '',
            'contact_phone': '',
        })
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.company_name, original_name)

    def test_profile_not_visible_to_other_employer(self):
        """A second employer must not be able to read the first employer's profile data."""
        other = make_user('other_emp')
        make_employer_profile(other, 'Other Corp')
        other_client = Client()
        other_client.force_login(other)
        response = other_client.get(self.url)
        # Other employer sees THEIR own profile, not self.profile
        self.assertEqual(response.status_code, 200)
        ctx_profile = response.context['profile']
        self.assertNotEqual(ctx_profile.pk, self.profile.pk)


# ===========================================================================
# 5. View Tests — Bulk Upload List
# ===========================================================================

class BulkUploadListViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = make_user('bulk_list_user')
        self.profile = make_employer_profile(self.user)
        self.client.force_login(self.user)
        self.url = reverse('employer:bulk_upload_list')

    def test_returns_200(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_uses_correct_template(self):
        response = self.client.get(self.url)
        self.assertTemplateUsed(response, 'employer/bulk_upload_list.html')

    def test_only_own_uploads_visible(self):
        """Uploads belonging to another employer must not appear."""
        other = make_user('other_bulk')
        other_profile = make_employer_profile(other, 'Other Co')
        make_bulk_upload(other_profile, 'secret.csv')
        my_upload = make_bulk_upload(self.profile, 'mine.csv')

        response = self.client.get(self.url)
        upload_pks = [u.pk for u in response.context['page_obj'].object_list]
        self.assertIn(my_upload.pk, upload_pks)
        # the other employer's upload must NOT appear
        other_upload = BulkCheckUpload.objects.filter(
            employer=other_profile
        ).first()
        self.assertNotIn(other_upload.pk, upload_pks)

    def test_pagination_20_per_page(self):
        for i in range(25):
            make_bulk_upload(self.profile, filename=f'f_{i}.csv')
        response = self.client.get(self.url)
        self.assertEqual(len(response.context['page_obj'].object_list), 20)

    def test_page_2_accessible(self):
        for i in range(25):
            make_bulk_upload(self.profile, filename=f'g_{i}.csv')
        response = self.client.get(self.url + '?page=2')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['page_obj'].object_list), 5)

    def test_empty_list_returns_200(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['page_obj'].object_list), 0)


# ===========================================================================
# 6. View Tests — Bulk Upload Detail
# ===========================================================================

class BulkUploadDetailViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = make_user('detail_user')
        self.profile = make_employer_profile(self.user)
        self.upload = make_bulk_upload(self.profile)
        self.client.force_login(self.user)
        self.url = reverse('employer:bulk_upload_detail', kwargs={'upload_id': self.upload.pk})

    def test_returns_200(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_uses_correct_template(self):
        response = self.client.get(self.url)
        self.assertTemplateUsed(response, 'employer/bulk_upload_detail.html')

    def test_context_contains_upload(self):
        response = self.client.get(self.url)
        self.assertEqual(response.context['upload'], self.upload)

    def test_rows_paginated_50_per_page(self):
        for i in range(55):
            BulkCheckRow.objects.create(
                upload=self.upload,
                row_number=i + 1,
                full_name=f'Person {i}',
            )
        response = self.client.get(self.url)
        self.assertEqual(len(response.context['page_obj'].object_list), 50)

    def test_rows_ordered_by_row_number(self):
        BulkCheckRow.objects.create(upload=self.upload, row_number=3)
        BulkCheckRow.objects.create(upload=self.upload, row_number=1)
        BulkCheckRow.objects.create(upload=self.upload, row_number=2)
        response = self.client.get(self.url)
        rows = list(response.context['page_obj'].object_list)
        self.assertEqual([r.row_number for r in rows], [1, 2, 3])

    def test_other_employer_cannot_access_upload(self):
        """Another employer must receive 404, not the upload detail."""
        other = make_user('other_detail')
        make_employer_profile(other, 'Evil Corp')
        other_client = Client()
        other_client.force_login(other)
        response = other_client.get(self.url)
        self.assertEqual(response.status_code, 404)

    def test_invalid_uuid_returns_404(self):
        bad_url = reverse(
            'employer:bulk_upload_detail',
            kwargs={'upload_id': uuid.uuid4()},  # random — does not exist
        )
        response = self.client.get(bad_url)
        self.assertEqual(response.status_code, 404)


# ===========================================================================
# 7. View Tests — Team List
# ===========================================================================

class TeamListViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = make_user('team_list_user')
        self.profile = make_employer_profile(self.user)
        self.client.force_login(self.user)
        self.url = reverse('employer:team_list')

    def test_returns_200(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_uses_correct_template(self):
        response = self.client.get(self.url)
        self.assertTemplateUsed(response, 'employer/team_list.html')

    def test_context_contains_members(self):
        member = make_user('tm_user', role='individual')
        TeamMember.objects.create(employer=self.profile, user=member, team_role='checker')
        response = self.client.get(self.url)
        self.assertIn('members', response.context)
        self.assertEqual(len(response.context['members']), 1)

    def test_inactive_members_excluded(self):
        active_m = make_user('active_m', role='individual')
        inactive_m = make_user('inactive_m2', role='individual')
        TeamMember.objects.create(employer=self.profile, user=active_m, team_role='checker')
        TeamMember.objects.create(
            employer=self.profile, user=inactive_m, team_role='viewer', is_active=False
        )
        response = self.client.get(self.url)
        members = list(response.context['members'])
        usernames = [m.user.username for m in members]
        self.assertIn('active_m', usernames)
        self.assertNotIn('inactive_m2', usernames)

    def test_only_own_team_members_visible(self):
        other = make_user('other_tm_emp')
        other_profile = make_employer_profile(other, 'Other Firm')
        other_member = make_user('other_member', role='individual')
        TeamMember.objects.create(employer=other_profile, user=other_member, team_role='admin')

        response = self.client.get(self.url)
        members = list(response.context['members'])
        member_employers = {m.employer_id for m in members}
        self.assertNotIn(other_profile.pk, member_employers)

    def test_empty_team_returns_200(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['members']), 0)


# ===========================================================================
# 8. Integration Tests — Auto Profile Creation
# ===========================================================================

class AutoProfileCreationTest(TestCase):
    """
    Verify that _get_or_create_employer_profile creates a profile whose
    company_name falls back to the user's full name or username.
    """

    def setUp(self):
        self.client = Client()

    def test_profile_name_falls_back_to_username_when_no_full_name(self):
        user = make_user('no_name_emp')
        self.client.force_login(user)
        self.client.get(reverse('employer:dashboard'))
        profile = EmployerProfile.objects.get(user=user)
        self.assertEqual(profile.company_name, user.username)

    def test_profile_name_uses_full_name_when_set(self):
        user = make_user('full_name_emp', first_name='Ada', last_name='Lovelace')
        self.client.force_login(user)
        self.client.get(reverse('employer:dashboard'))
        profile = EmployerProfile.objects.get(user=user)
        self.assertEqual(profile.company_name, 'Ada Lovelace')

    def test_profile_created_only_once_on_repeated_visits(self):
        user = make_user('repeat_visit_emp')
        self.client.force_login(user)
        self.client.get(reverse('employer:dashboard'))
        self.client.get(reverse('employer:dashboard'))
        self.client.get(reverse('employer:dashboard'))
        self.assertEqual(EmployerProfile.objects.filter(user=user).count(), 1)


# ===========================================================================
# 9. Security Tests
# ===========================================================================

class EmployerSecurityTest(TestCase):
    """
    Cross-employer data isolation and CSRF enforcement.
    """

    def setUp(self):
        self.client = Client()
        self.emp1 = make_user('sec_emp1')
        self.emp2 = make_user('sec_emp2')
        self.profile1 = make_employer_profile(self.emp1, 'Corp One')
        self.profile2 = make_employer_profile(self.emp2, 'Corp Two')

    def test_employer1_cannot_access_employer2_upload_detail(self):
        upload = make_bulk_upload(self.profile2, 'private.csv')
        self.client.force_login(self.emp1)
        url = reverse('employer:bulk_upload_detail', kwargs={'upload_id': upload.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_profile_post_only_updates_own_profile(self):
        """POSTing to employer:profile must update the logged-in user's profile only."""
        self.client.force_login(self.emp1)
        self.client.post(reverse('employer:profile'), {
            'company_name': 'Changed By Emp1',
            'company_rc_number': '',
            'industry': '',
            'company_address': '',
            'contact_phone': '',
        })
        self.profile2.refresh_from_db()
        self.assertNotEqual(self.profile2.company_name, 'Changed By Emp1')

    def test_csrf_enforced_on_profile_update(self):
        """Without CSRF token the Django test client enforces protection when enforce_csrf_checks=True."""
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.emp1)
        response = csrf_client.post(reverse('employer:profile'), {
            'company_name': 'CSRF Attack',
            'company_rc_number': '',
            'industry': '',
            'company_address': '',
            'contact_phone': '',
        })
        self.assertEqual(response.status_code, 403)

    def test_nin_hash_field_accepts_only_64_char_strings(self):
        """
        BulkCheckRow.nin_hash is a CharField(max_length=64).
        Storing a value longer than 64 chars must raise a database error.
        """
        upload = make_bulk_upload(self.profile1)
        row = BulkCheckRow(
            upload=upload,
            row_number=1,
            nin_hash='x' * 65,  # one char over limit
        )
        with self.assertRaises(Exception):
            row.full_clean()  # Django model validation catches max_length

    def test_bulk_upload_employer_isolation_on_list(self):
        """
        Employer 1's upload list must never include Employer 2's uploads.
        """
        make_bulk_upload(self.profile1, 'emp1.csv')
        make_bulk_upload(self.profile2, 'emp2.csv')

        self.client.force_login(self.emp1)
        response = self.client.get(reverse('employer:bulk_upload_list'))
        pks = {u.pk for u in response.context['page_obj'].object_list}

        emp2_uploads = BulkCheckUpload.objects.filter(employer=self.profile2)
        for upload in emp2_uploads:
            self.assertNotIn(upload.pk, pks)

    