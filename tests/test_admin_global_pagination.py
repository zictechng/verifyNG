from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse

User = get_user_model()


class AdminGlobalPaginationTests(TestCase):
    """
    Test suite for admin-wide zero-reload pagination and Rows Per Page (15, 25, 50, 75, 100).
    Verifies that:
    1. All admin table views accept per_page in (15, 25, 50, 75, 100) and default to 15.
    2. Context contains per_page_options = [15, 25, 50, 75, 100].
    3. Templates contain #adminTableContainer, .admin-per-page-select, and .admin-page-link.
    4. AJAX requests with X-Requested-With return HTTP 200 with #adminTableContainer intact.
    """

    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_superuser(
            username='global_admin',
            email='admin@verifyng.com',
            password='AdminPass123!',
        )
        self.admin.is_staff = True
        self.admin.save(update_fields=['is_staff'])
        self.client.force_login(self.admin)

        # Create 35 dummy users so pagination kicks in (> 15)
        users = [
            User(
                username=f'user_batch_{i}',
                email=f'user_{i}@example.com',
                role='candidate'
            )
            for i in range(1, 36)
        ]
        User.objects.bulk_create(users)

    def test_users_table_pagination_and_per_page(self):
        """Users view accepts per_page=15, 25, 50, 75, 100 and renders #adminTableContainer."""
        url = reverse('admin_portal:users')
        res = self.client.get(url, {'per_page': '25'})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context['per_page'], 25)
        self.assertEqual(res.context['per_page_options'], [15, 25, 50, 75, 100])
        self.assertEqual(len(res.context['page_obj']), 25)
        self.assertContains(res, 'id="adminTableContainer"')
        self.assertContains(res, 'admin-per-page-select')
        self.assertContains(res, 'admin-page-link')

    def test_users_table_ajax_header_request(self):
        """AJAX request with X-Requested-With returns the full page containing #adminTableContainer."""
        url = reverse('admin_portal:users')
        res = self.client.get(url, {'page': '2', 'per_page': '15'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context['page_obj'].number, 2)
        self.assertContains(res, 'id="adminTableContainer"')

    def test_employer_profiles_table_per_page(self):
        """Employer profiles view accepts per_page (75, 100) and context options."""
        url = reverse('admin_portal:employer_profiles')
        res = self.client.get(url, {'per_page': '75'})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context['per_page'], 75)
        self.assertEqual(res.context['per_page_options'], [15, 25, 50, 75, 100])
        self.assertContains(res, 'id="adminTableContainer"')

    def test_reports_table_per_page(self):
        """Reports moderation view accepts per_page."""
        url = reverse('admin_portal:reports')
        res = self.client.get(url, {'per_page': '50'})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context['per_page'], 50)
        self.assertEqual(res.context['per_page_options'], [15, 25, 50, 75, 100])
        self.assertContains(res, 'id="adminTableContainer"')

    def test_disputes_table_per_page(self):
        """Disputes view accepts per_page."""
        url = reverse('admin_portal:disputes')
        res = self.client.get(url, {'per_page': '25'})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context['per_page'], 25)
        self.assertEqual(res.context['per_page_options'], [15, 25, 50, 75, 100])
        self.assertContains(res, 'id="adminTableContainer"')

    def test_verifications_table_per_page(self):
        """Verifications view accepts per_page."""
        url = reverse('admin_portal:verifications')
        res = self.client.get(url, {'per_page': '100'})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context['per_page'], 100)
        self.assertEqual(res.context['per_page_options'], [15, 25, 50, 75, 100])
        self.assertContains(res, 'id="adminTableContainer"')

    def test_subscriptions_table_per_page(self):
        """Subscriptions view accepts per_page."""
        url = reverse('admin_portal:subscriptions')
        res = self.client.get(url, {'per_page': '15'})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context['per_page'], 15)
        self.assertEqual(res.context['per_page_options'], [15, 25, 50, 75, 100])
        self.assertContains(res, 'id="adminTableContainer"')

    def test_certificates_table_per_page(self):
        """Certificates view accepts dynamic per_page (e.g. 75)."""
        url = reverse('admin_portal:certificates')
        res = self.client.get(url, {'per_page': '75'})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context['per_page'], 75)
        self.assertEqual(res.context['per_page_options'], [15, 25, 50, 75, 100])
        self.assertContains(res, 'id="adminTableContainer"')

    def test_system_logs_table_per_page(self):
        """System logs view accepts per_page."""
        url = reverse('admin_portal:system_logs')
        res = self.client.get(url, {'per_page': '50'})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context['per_page'], 50)
        self.assertEqual(res.context['per_page_options'], [15, 25, 50, 75, 100])
        self.assertContains(res, 'id="adminTableContainer"')

    def test_audit_logs_table_per_page(self):
        """Audit logs view accepts per_page and renders #adminTableContainer."""
        url = reverse('admin_portal:audit_logs')
        res = self.client.get(url, {'per_page': '25'})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context['per_page'], 25)
        self.assertEqual(res.context['per_page_options'], [15, 25, 50, 75, 100])
        self.assertContains(res, 'id="adminTableContainer"')

    def test_activity_logs_table_per_page(self):
        """Activity logs view accepts per_page and renders #adminTableContainer."""
        url = reverse('admin_portal:activity_logs')
        res = self.client.get(url, {'per_page': '15'})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context['per_page'], 15)
        self.assertEqual(res.context['per_page_options'], [15, 25, 50, 75, 100])
        self.assertContains(res, 'id="adminTableContainer"')

    def test_login_logs_table_per_page(self):
        """Login logs view accepts per_page and renders #adminTableContainer."""
        url = reverse('admin_portal:login_logs')
        res = self.client.get(url, {'per_page': '15'})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context['per_page'], 15)
        self.assertEqual(res.context['per_page_options'], [15, 25, 50, 75, 100])
        self.assertContains(res, 'id="adminTableContainer"')
