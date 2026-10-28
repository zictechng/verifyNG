from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse

User = get_user_model()


class AdminCommunicationsViewTestCase(TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST='localhost')
        self.superadmin = User.objects.create_superuser(
            username='admin_comm',
            email='admin_comm@example.com',
            password='Password123!',
        )
        self.user_indiv = User.objects.create_user(
            username='indiv_user',
            email='indiv@example.com',
            password='Password123!',
            role='individual',
            is_active=True,
        )
        self.user_employer = User.objects.create_user(
            username='emp_user',
            email='employer@example.com',
            password='Password123!',
            role='employer',
            is_active=True,
        )

    def test_communications_get_renders_roles(self):
        self.client.force_login(self.superadmin)
        res = self.client.get(reverse('admin_portal:communications'))
        self.assertEqual(res.status_code, 200)
        content = res.content.decode('utf-8')
        self.assertIn('Select Role', content)
        self.assertIn('-- Choose User Role --', content)
        self.assertIn('value="individual"', content)
        self.assertIn('value="employer"', content)
        self.assertIn('value="business"', content)
        self.assertIn('targetRoleSelect', content)

    def test_communications_post_role_missing_role_error(self):
        self.client.force_login(self.superadmin)
        res = self.client.post(reverse('admin_portal:communications'), {
            'target_type': 'role',
            'target_role': '',
            'subject': 'Test Subject',
            'message_body': 'Test Message Body',
        })
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Please select a specific role to target.')

    def test_communications_post_role_success(self):
        self.client.force_login(self.superadmin)
        res = self.client.post(reverse('admin_portal:communications'), {
            'target_type': 'role',
            'target_role': 'employer',
            'subject': 'Employer Notice',
            'message_body': 'Important employer update',
        })
        # Should redirect back to communications with success message
        self.assertEqual(res.status_code, 302)
        self.assertIn(reverse('admin_portal:communications'), res.url)
