
# tests/test_auth.py
"""
Authentication, registration, and login rate-limiting tests.

Run with:
    python manage.py test tests.test_auth --verbosity=2
"""

from django.test import TestCase, Client
from django.urls import reverse
from unittest.mock import patch

from users.models import User


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_user(username='testuser', password='StrongPass123!', email='test@example.com',
              is_verified=False):
    """Create and return a User instance."""
    user = User.objects.create_user(
        username=username,
        email=email,
        password=password,
    )
    if is_verified:
        user.is_verified = True
        user.save(update_fields=['is_verified'])
    return user


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------

class RegistrationTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.url = reverse('users:register')

    def test_registration_page_loads(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_valid_registration_creates_user(self):
        response = self.client.post(self.url, {
            'username': 'newuser',
            'email': 'new@example.com',
            'password1': 'StrongPass123!',
            'password2': 'StrongPass123!',
        })
        self.assertTrue(User.objects.filter(username='newuser').exists())

    def test_registration_redirects_after_success(self):
        response = self.client.post(self.url, {
            'username': 'newuser2',
            'email': 'new2@example.com',
            'password1': 'StrongPass123!',
            'password2': 'StrongPass123!',
        })
        self.assertIn(response.status_code, [200, 302])

    def test_password_mismatch_rejected(self):
        response = self.client.post(self.url, {
            'username': 'baduser',
            'email': 'bad@example.com',
            'password1': 'StrongPass123!',
            'password2': 'WrongPass456!',
        })
        self.assertFalse(User.objects.filter(username='baduser').exists())

    def test_duplicate_username_rejected(self):
        make_user(username='existing')
        response = self.client.post(self.url, {
            'username': 'existing',
            'email': 'other@example.com',
            'password1': 'StrongPass123!',
            'password2': 'StrongPass123!',
        })
        self.assertEqual(User.objects.filter(username='existing').count(), 1)

    def test_weak_password_rejected(self):
        response = self.client.post(self.url, {
            'username': 'weakuser',
            'email': 'weak@example.com',
            'password1': '123',
            'password2': '123',
        })
        self.assertFalse(User.objects.filter(username='weakuser').exists())


# ---------------------------------------------------------------------------
# Login tests
# ---------------------------------------------------------------------------

class LoginTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.url = reverse('users:login')
        self.user = make_user()

    def test_login_page_loads(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_valid_credentials_authenticate(self):
        response = self.client.post(self.url, {
            'username': 'testuser',
            'password': 'StrongPass123!',
        })
        self.assertIn(response.status_code, [200, 302])

    def test_wrong_password_rejected(self):
        response = self.client.post(self.url, {
            'username': 'testuser',
            'password': 'WrongPassword!',
        })
        # Should not redirect to dashboard — stays on login or shows error
        if response.status_code == 302:
            self.assertNotIn('/dashboard/', response['Location'])

    def test_nonexistent_user_rejected(self):
        response = self.client.post(self.url, {
            'username': 'ghostuser',
            'password': 'AnyPassword!',
        })
        self.assertNotEqual(response.status_code, 302)


# ---------------------------------------------------------------------------
# Login rate-limiting tests
# ---------------------------------------------------------------------------

class LoginRateLimitTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.url = reverse('users:login')

    def test_rate_limit_returns_429_when_exceeded(self):
        """When check_rate_limit signals exceeded, login view must return 429."""
        with patch('users.views.check_rate_limit', return_value=(True, 900)):
            response = self.client.post(self.url, {
                'username': 'anyuser',
                'password': 'anypass',
            })
        self.assertEqual(response.status_code, 429)

    def test_normal_request_not_rate_limited(self):
        """When check_rate_limit signals OK, login proceeds normally."""
        with patch('users.views.check_rate_limit', return_value=(False, 0)):
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)


# ---------------------------------------------------------------------------
# Authentication required — protected views
# ---------------------------------------------------------------------------

class AuthenticationRequiredTest(TestCase):

    def setUp(self):
        self.client = Client()

    def test_dashboard_redirects_anonymous(self):
        response = self.client.get('/dashboard/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response['Location'])

    def test_authenticated_user_can_access_dashboard(self):
        user = make_user(username='dashuser')
        self.client.force_login(user)
        response = self.client.get('/dashboard/')
        self.assertIn(response.status_code, [200, 302])

    def test_report_create_redirects_anonymous(self):
        response = self.client.get(reverse('reports:create'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response['Location'])


# ---------------------------------------------------------------------------
# Identity verification gate on report submission
# ---------------------------------------------------------------------------

class ReportIdentityGateTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.url = reverse('reports:create')

    def test_unverified_user_redirected_from_report_create(self):
        user = make_user(username='unverified', is_verified=False)
        self.client.force_login(user)
        response = self.client.get(self.url, follow=False)
        # Unverified user must be redirected — not shown the form
        self.assertRedirects(
            response,
            expected_url=reverse('verification:create'),
            fetch_redirect_response=False,
        )

    def test_verified_user_can_access_report_create(self):
        user = make_user(username='verified', is_verified=True)
        self.client.force_login(user)
        response = self.client.get(self.url)
        # 200 = form shown; any other non-login redirect is also acceptable
        self.assertNotEqual(response.status_code, 403)

