
from django.test import TestCase
from django.urls import reverse

from users.models import User
from identities.models import SubjectEntity
from reports.models import FraudReport, Dispute
from reports.services import create_fraud_report, file_dispute_for_report
from verification.models import VerificationRequest
from verification.services import create_verification_request


class DashboardAccessAndContextTestCase(TestCase):
    def setUp(self):
        self.individual_user = User.objects.create_user(
            username='indiv_dash', email='indiv@example.com', password='password123', role='individual'
        )
        self.other_user = User.objects.create_user(
            username='other_dash', email='other@example.com', password='password123', role='individual'
        )
        self.moderator_user = User.objects.create_user(
            username='mod_dash', email='mod@example.com', password='password123', role='moderator'
        )
        self.officer_user = User.objects.create_user(
            username='officer_dash', email='officer@example.com', password='password123', role='officer'
        )
        self.superuser = User.objects.create_superuser(
            username='admin_dash', email='admin@example.com', password='password123'
        )
        self.dashboard_url = reverse('dashboard:index')

    def test_unauthenticated_redirects_to_login(self):
        res = self.client.get(self.dashboard_url)
        self.assertEqual(res.status_code, 302)
        self.assertIn('/users/login/', res.url)
        self.assertIn('next=/dashboard/', res.url)

    def test_individual_user_context_and_isolation(self):
        # 1. Create reports and verifications for individual_user
        rep_user = create_fraud_report(
            reporter=self.individual_user,
            subject_name="Target A",
            subject_type="business",
            title="User Report",
            allegation="Allegation by user"
        )
        verif_user = create_verification_request(
            requester=self.individual_user,
            subject_name="Target A",
            subject_type="business",
            verification_type="identity"
        )

        # 2. Create reports and verifications for other_user (should NOT appear in individual_user context)
        rep_other = create_fraud_report(
            reporter=self.other_user,
            subject_name="Target B",
            subject_type="person",
            title="Other Report",
            allegation="Allegation by other"
        )
        verif_other = create_verification_request(
            requester=self.other_user,
            subject_name="Target B",
            subject_type="person",
            verification_type="identity"
        )

        # 3. Log in as individual_user and inspect context
        self.client.force_login(self.individual_user)
        res = self.client.get(self.dashboard_url)
        self.assertEqual(res.status_code, 200)

        user_reports = list(res.context['user_reports'])
        user_verifs = list(res.context['user_verifications'])

        self.assertIn(rep_user, user_reports)
        self.assertNotIn(rep_other, user_reports)
        self.assertIn(verif_user, user_verifs)
        self.assertNotIn(verif_other, user_verifs)

    def test_individual_role_desk_visibility(self):
        self.client.force_login(self.individual_user)
        res = self.client.get(self.dashboard_url)
        self.assertEqual(res.status_code, 200)

        # Context booleans
        self.assertFalse(res.context['is_moderator'])
        self.assertFalse(res.context['is_officer'])

        content = res.content.decode('utf-8')
        # Safety tips widget should be rendered
        self.assertIn("Safety Tips", content)
        self.assertIn("Stay Vigilant", content)

        # Moderation and Officer desk widgets must NOT be rendered in DOM
        self.assertNotIn("Open Moderation Queue", content)
        self.assertNotIn("Staff Operations", content)
        self.assertNotIn("Open Officer Queue", content)
        self.assertNotIn("Verification Queue", content)

    def test_moderator_role_desk_counters(self):
        # Create 1 submitted report and 1 under_review report
        r1 = create_fraud_report(
            reporter=self.individual_user,
            subject_name="Mod Target 1",
            subject_type="business",
            title="Pending Report 1",
            allegation="Details 1"
        )
        r2 = create_fraud_report(
            reporter=self.individual_user,
            subject_name="Mod Target 2",
            subject_type="business",
            title="Pending Report 2",
            allegation="Details 2"
        )
        r2.state = 'under_review'
        r2.save()

        # Log in as moderator
        self.client.force_login(self.moderator_user)
        res = self.client.get(self.dashboard_url)
        self.assertEqual(res.status_code, 200)

        self.assertTrue(res.context['is_moderator'])
        self.assertEqual(res.context['pending_moderation_count'], 2)
        self.assertEqual(res.context['open_disputes_count'], 0)

        content = res.content.decode('utf-8')
        self.assertIn("Moderator Desk", content)
        self.assertIn("Staff Operations", content)

    def test_officer_role_desk_counters(self):
        # Create 1 pending verification request
        create_verification_request(
            requester=self.individual_user,
            subject_name="Verification Target",
            subject_type="business",
            verification_type="credential"
        )

        self.client.force_login(self.officer_user)
        res = self.client.get(self.dashboard_url)
        self.assertEqual(res.status_code, 200)

        self.assertTrue(res.context['is_officer'])
        self.assertEqual(res.context['pending_verification_count'], 1)

        content = res.content.decode('utf-8')
        self.assertIn("Officer Desk", content)
        self.assertIn("Verification Queue", content)

    def test_superuser_desk_visibility(self):
        # Superuser has access to both operations desks simultaneously
        self.client.force_login(self.superuser)
        res = self.client.get(self.dashboard_url)
        self.assertEqual(res.status_code, 200)

        self.assertTrue(res.context['is_moderator'])
        self.assertTrue(res.context['is_officer'])

        content = res.content.decode('utf-8')
        self.assertIn("Moderator Desk", content)
        self.assertIn("Officer Desk", content)


from unittest.mock import patch
from users.models import LoginAudit


class AdminPortalOperationsTestCase(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(
            username='admin_boss',
            email='admin@verifyng.org',
            password='Password123!'
        )
        self.individual = User.objects.create_user(
            username='regular_user',
            email='regular@test.com',
            password='Password123!',
            role='individual'
        )
        self.client.login(username='admin_boss', password='Password123!')

    def test_admin_portal_access_restricted_from_regular_users(self):
        """Regular users are blocked from /admin-portal/."""
        self.client.login(username='regular_user', password='Password123!')
        res = self.client.get(reverse('admin_portal:overview'))
        self.assertEqual(res.status_code, 403)

    def test_admin_overview_loads_for_superuser(self):
        """Superuser loads overview and receives status 200 with metrics."""
        res = self.client.get(reverse('admin_portal:overview'))
        self.assertEqual(res.status_code, 200)
        self.assertIn('total_users', res.context)
        self.assertIn('chart_labels_json', res.context)

    def test_admin_user_suspend_and_reactivate(self):
        """Admin can toggle user active state between active and suspended."""
        toggle_url = reverse('admin_portal:user_toggle_status', kwargs={'user_id': self.individual.id})

        # Suspend
        res_suspend = self.client.post(toggle_url)
        self.assertEqual(res_suspend.status_code, 302)
        self.individual.refresh_from_db()
        self.assertFalse(self.individual.is_active)

        # Reactivate
        res_activate = self.client.post(toggle_url)
        self.assertEqual(res_activate.status_code, 302)
        self.individual.refresh_from_db()
        self.assertTrue(self.individual.is_active)

    def test_admin_user_role_change(self):
        """Admin can reassign user role to moderator."""
        role_url = reverse('admin_portal:user_change_role', kwargs={'user_id': self.individual.id})
        res = self.client.post(role_url, {'role': 'moderator'})
        self.assertEqual(res.status_code, 302)
        self.individual.refresh_from_db()
        self.assertEqual(self.individual.role, 'moderator')

    def test_login_audit_record_created_on_login(self):
        """Authentication signals automatically record LoginAudit entry."""
        self.client.logout()
        self.client.login(username='admin_boss', password='Password123!')

        audit = LoginAudit.objects.filter(username_attempted='admin_boss', status='success').first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.status, 'success')

    @patch('core.tasks.send_email_notification_task.delay')
    def test_admin_communications_dispatch(self, mock_email_delay):
        """Admin can dispatch broadcast notifications to selected user groups."""
        comm_url = reverse('admin_portal:communications')
        res = self.client.post(comm_url, {
            'target_type': 'single',
            'target_email': 'test_target@example.com',
            'subject': 'System Maintenance',
            'message_body': 'Platform updating tonight.'
        })
        self.assertEqual(res.status_code, 302)
        mock_email_delay.assert_called_once_with(
            'test_target@example.com',
            'System Maintenance',
            'Platform updating tonight.'
        )


