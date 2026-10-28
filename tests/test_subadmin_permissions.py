from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.urls import reverse
from django_otp.plugins.otp_totp.models import TOTPDevice

User = get_user_model()


class SubAdminPermissionsSecurityTestCase(TestCase):
    """
    Test suite for Two-Tier Defense in Depth Sub-Admin Permissions:
    1. Sub-admins can only access sections matching their granted model permissions.
    2. Unauthorized section access returns HTTP 403 with friendly access_denied.html.
    3. Direct access to technical /admin/ is blocked for non-superusers with a friendly guide back to portal.
    4. Superusers maintain full unrestricted access across all portal views and /admin/.
    """

    def setUp(self):
        self.client = Client(HTTP_HOST='localhost')

        # Superadmin user with verified OTP TOTPDevice
        self.superadmin = User.objects.create_superuser(
            username='superadmin',
            email='superadmin@example.com',
            password='Password123!',
            first_name='Super',
            last_name='Admin',
        )
        self.otp_device = TOTPDevice.objects.create(
            user=self.superadmin,
            name='default',
            confirmed=True
        )

        # Subadmin: Reports Moderator
        self.reports_group = Group.objects.create(name='Reports Moderator')
        report_perms = Permission.objects.filter(
            codename__in=['view_fraudreport', 'change_fraudreport', 'view_dispute', 'change_dispute']
        )
        self.reports_group.permissions.set(report_perms)

        self.reports_subadmin = User.objects.create_user(
            username='report_mod',
            email='report_mod@example.com',
            password='Password123!',
            first_name='Report',
            last_name='Moderator',
            is_staff=True,
            is_superuser=False,
        )
        self.reports_subadmin.groups.add(self.reports_group)

        # Subadmin: Verification Officer
        self.verif_group = Group.objects.create(name='Verification Officer')
        verif_perms = Permission.objects.filter(
            codename__in=['view_verificationrequest', 'change_verificationrequest', 'view_verificationcertificate']
        )
        self.verif_group.permissions.set(verif_perms)

        self.verif_subadmin = User.objects.create_user(
            username='verif_officer',
            email='verif_officer@example.com',
            password='Password123!',
            first_name='Verif',
            last_name='Officer',
            is_staff=True,
            is_superuser=False,
        )
        self.verif_subadmin.groups.add(self.verif_group)

        # Regular individual user (non-staff)
        self.regular_user = User.objects.create_user(
            username='regular_user',
            email='regular@example.com',
            password='Password123!',
            is_staff=False,
            is_superuser=False,
        )

    def _login_superadmin_with_otp(self):
        self.client.force_login(self.superadmin)
        session = self.client.session
        session['otp_device_id'] = self.otp_device.persistent_id
        session.save()

    def test_reports_moderator_allowed_reports_view(self):
        """Reports Moderator should have 200 OK access to Fraud Reports."""
        self.client.force_login(self.reports_subadmin)
        res = self.client.get(reverse('admin_portal:reports'))
        self.assertEqual(res.status_code, 200)

    def test_reports_moderator_blocked_from_verifications_view(self):
        """Reports Moderator attempting to open Verifications gets HTTP 403 and friendly access_denied page."""
        self.client.force_login(self.reports_subadmin)
        res = self.client.get(reverse('admin_portal:verifications'))
        self.assertEqual(res.status_code, 403)
        self.assertTemplateUsed(res, 'admin_portal/access_denied.html')
        content = res.content.decode('utf-8')
        self.assertIn("Access Restricted", content)
        self.assertIn("Verification Requests", content)
        self.assertIn("Return to Dashboard", content)
        self.assertIn("Reports Moderator", content)

    def test_reports_moderator_blocked_from_users_view(self):
        """Reports Moderator attempting to open Users view gets HTTP 403 access_denied page."""
        self.client.force_login(self.reports_subadmin)
        res = self.client.get(reverse('admin_portal:users'))
        self.assertEqual(res.status_code, 403)
        self.assertTemplateUsed(res, 'admin_portal/access_denied.html')
        content = res.content.decode('utf-8')
        self.assertIn("Access Restricted", content)
        self.assertIn("User Management", content)

    def test_reports_moderator_blocked_from_raw_django_admin(self):
        """Sub-admin accessing raw technical /admin/ is stopped with friendly access_denied screen."""
        self.client.force_login(self.reports_subadmin)
        res = self.client.get('/admin/')
        self.assertEqual(res.status_code, 403)
        self.assertTemplateUsed(res, 'admin_portal/access_denied.html')
        content = res.content.decode('utf-8')
        self.assertIn("Access Restricted", content)
        self.assertIn("You are not authorized to access the technical backend", content)
        self.assertIn("Return to Dashboard", content)

    def test_verification_officer_allowed_verifications_view(self):
        """Verification Officer should have 200 OK access to Verifications."""
        self.client.force_login(self.verif_subadmin)
        res = self.client.get(reverse('admin_portal:verifications'))
        self.assertEqual(res.status_code, 200)

    def test_verification_officer_blocked_from_reports_view(self):
        """Verification Officer attempting to open Reports gets HTTP 403 access_denied page."""
        self.client.force_login(self.verif_subadmin)
        res = self.client.get(reverse('admin_portal:reports'))
        self.assertEqual(res.status_code, 403)
        self.assertTemplateUsed(res, 'admin_portal/access_denied.html')
        content = res.content.decode('utf-8')
        self.assertIn("Access Restricted", content)
        self.assertIn("Fraud Reports", content)

    def test_subadmin_blocked_from_superuser_only_settings(self):
        """Sub-admin attempting to access site settings gets HTTP 403 access_denied page."""
        self.client.force_login(self.verif_subadmin)
        res = self.client.get(reverse('admin_portal:site_settings'))
        self.assertEqual(res.status_code, 403)
        self.assertTemplateUsed(res, 'admin_portal/access_denied.html')
        content = res.content.decode('utf-8')
        self.assertIn("Access Restricted", content)
        self.assertIn("Site Settings", content)

    def test_superadmin_has_full_access(self):
        """Superadmin has unrestricted access to all portal views and raw /admin/."""
        self._login_superadmin_with_otp()

        res_reports = self.client.get(reverse('admin_portal:reports'))
        self.assertEqual(res_reports.status_code, 200)

        res_verif = self.client.get(reverse('admin_portal:verifications'))
        self.assertEqual(res_verif.status_code, 200)

        res_users = self.client.get(reverse('admin_portal:users'))
        self.assertEqual(res_users.status_code, 200)

        res_settings = self.client.get(reverse('admin_portal:site_settings'))
        self.assertEqual(res_settings.status_code, 200)

        # In /admin/, superadmin is allowed
        res_raw_admin = self.client.get('/admin/', follow=True)
        # Should not be 403 access denied
        self.assertNotEqual(res_raw_admin.status_code, 403)

    def test_non_staff_redirected_to_login(self):
        """Non-staff user attempting to access admin portal is redirected to login."""
        self.client.force_login(self.regular_user)
        res = self.client.get(reverse('admin_portal:reports'))
        self.assertEqual(res.status_code, 302)
        self.assertIn('/users/login/', res.url)
