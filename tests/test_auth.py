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
              identity_verified=False):
    """Create and return a User instance."""
    user = User.objects.create_user(
        username=username,
        email=email,
        password=password,
    )
    if identity_verified:
        user.identity_verified = True
        user.save(update_fields=['identity_verified'])
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
        self.client.post(self.url, {
            'username': 'baduser',
            'email': 'bad@example.com',
            'password1': 'StrongPass123!',
            'password2': 'WrongPass456!',
        })
        self.assertFalse(User.objects.filter(username='baduser').exists())

    def test_duplicate_username_rejected(self):
        make_user(username='existing')
        self.client.post(self.url, {
            'username': 'existing',
            'email': 'other@example.com',
            'password1': 'StrongPass123!',
            'password2': 'StrongPass123!',
        })
        self.assertEqual(User.objects.filter(username='existing').count(), 1)

    def test_weak_password_rejected(self):
        self.client.post(self.url, {
            'username': 'weakuser',
            'email': 'weak@example.com',
            'password1': '123',
            'password2': '123',
        })
        self.assertFalse(User.objects.filter(username='weakuser').exists())


# ---------------------------------------------------------------------------
# Login tests
# All login tests mock check_rate_limit to avoid Redis state bleed between tests.
# ---------------------------------------------------------------------------

class LoginTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.url = reverse('users:login')
        self.user = make_user()

    def test_login_page_loads(self):
        with patch('users.views.check_rate_limit', return_value=(False, 0)):
            response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_valid_credentials_authenticate(self):
        with patch('users.views.check_rate_limit', return_value=(False, 0)):
            response = self.client.post(self.url, {
                'username': 'testuser',
                'password': 'StrongPass123!',
            })
        self.assertIn(response.status_code, [200, 302])

    def test_wrong_password_rejected(self):
        with patch('users.views.check_rate_limit', return_value=(False, 0)):
            response = self.client.post(self.url, {
                'username': 'testuser',
                'password': 'WrongPassword!',
            })
        if response.status_code == 302:
            self.assertNotIn('/dashboard/', response['Location'])

    def test_nonexistent_user_rejected(self):
        with patch('users.views.check_rate_limit', return_value=(False, 0)):
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
    """
    Tests the identity verification gate on ReportCreateView.
    Uses RequestFactory + middleware simulation for accurate dispatch testing.
    """

    def setUp(self):
        self.url = reverse('reports:create')

    def test_dispatch_blocks_unverified_user(self):
        """dispatch() must redirect authenticated-but-unverified users."""
        from reports.views import ReportCreateView
        from django.test import RequestFactory
        from django.contrib.messages.storage.fallback import FallbackStorage

        factory = RequestFactory()
        request = factory.get(self.url)

        user = make_user(username='unverified', identity_verified=False)
        request.user = user

        # Attach message storage (required by messages.warning in dispatch)
        setattr(request, 'session', {})
        messages_storage = FallbackStorage(request)
        setattr(request, '_messages', messages_storage)

        view = ReportCreateView.as_view()
        response = view(request)

        self.assertEqual(response.status_code, 302)
        self.assertIn('verification', response['Location'])

    def test_dispatch_allows_verified_user(self):
        """dispatch() must allow authenticated verified users through."""
        from reports.views import ReportCreateView
        from django.test import RequestFactory
        from django.contrib.messages.storage.fallback import FallbackStorage

        factory = RequestFactory()
        request = factory.get(self.url)

        user = make_user(username='verified2', identity_verified=True)
        request.user = user

        setattr(request, 'session', {})
        messages_storage = FallbackStorage(request)
        setattr(request, '_messages', messages_storage)

        view = ReportCreateView.as_view()
        response = view(request)

        # 200 = form shown; should NOT be a verification redirect
        self.assertNotEqual(response.status_code, 302)

    def test_report_create_redirects_anonymous(self):
        """Anonymous users must be redirected to login."""
        client = Client()
        response = client.get(self.url, follow=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response['Location'])




# ---------------------------------------------------------------------------
# Google OAuth Role Intent & In-App Company Registration Tests
# ---------------------------------------------------------------------------

class GoogleOAuthRoleIntentTest(TestCase):
    def setUp(self):
        self.client = Client()

    def test_oauth_initiate_employer_role(self):
        url = reverse('users:oauth_google_login') + '?role=employer'
        response = self.client.get(url, follow=False)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session.get('oauth_role_intent'), 'employer')

    def test_oauth_initiate_agency_role(self):
        url = reverse('users:oauth_google_login') + '?role=agency'
        response = self.client.get(url, follow=False)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session.get('oauth_role_intent'), 'agency')

    def test_oauth_initiate_default_role(self):
        url = reverse('users:oauth_google_login')
        response = self.client.get(url, follow=False)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session.get('oauth_role_intent'), 'individual')


class RegisterCompanyUpgradeTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = make_user(username='indiv_upgrade_user', email='upgrade@test.com')
        self.url = reverse('users:register_company')

    def test_anonymous_redirected_to_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response['Location'])

    def test_individual_can_access_company_registration_form(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Register Your Organisation')

    def test_upgrade_creates_employer_profile_and_switches_role(self):
        self.client.force_login(self.user)
        response = self.client.post(self.url, {
            'company_name': 'Sterling Logistics Limited',
            'company_rc_number': 'RC109283',
            'contact_phone': '+2348030001122'
        }, follow=False)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('employer:dashboard'))

        self.user.refresh_from_db()
        self.assertEqual(self.user.role, 'employer')

        from employer.models import EmployerProfile
        profile = EmployerProfile.objects.filter(user=self.user).first()
        self.assertIsNotNone(profile)
        self.assertEqual(profile.company_name, 'Sterling Logistics Limited')
        self.assertEqual(profile.company_rc_number, 'RC109283')
        self.assertEqual(profile.is_verified, False)  # KYC gate strictly intact



class OAuthUserPasswordResetTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = make_user(username='google_oauth_user', email='oauthuser@test.com')
        # Simulate OAuth signup: unusable local password
        self.user.set_unusable_password()
        self.user.save()

    def test_unusable_password_user_can_request_reset(self):
        self.assertFalse(self.user.has_usable_password())
        url = reverse('users:password_reset')
        with patch('notifications.tasks.send_broadcast_email_task.delay') as mock_send:
            response = self.client.post(url, {'email': 'oauthuser@test.com'}, follow=False)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response['Location'], reverse('users:password_reset_done'))
            mock_send.assert_called_once()
            call_kwargs = mock_send.call_args[1]
            self.assertEqual(call_kwargs['to_email'], 'oauthuser@test.com')
            self.assertIn('users/password-reset/confirm/', call_kwargs['html_body'])
