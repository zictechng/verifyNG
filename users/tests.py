from django.test import TestCase
from django.urls import reverse
from django.core import mail
from users.models import User


class UserAuthenticationTestCase(TestCase):
    def setUp(self):
        self.username = 'testuser'
        self.password = 'StrongPass123!'
        self.email = 'testuser@example.com'
        self.user = User.objects.create_user(
            username=self.username,
            email=self.email,
            password=self.password,
            role='individual'
        )

    def test_successful_registration_defaults_to_individual_role(self):
        url = reverse('users:register')
        data = {
            'username': 'newuser',
            'email': 'newuser@example.com',
            'password1': 'NewPass123!',
            'password2': 'NewPass123!',
            'first_name': 'John',
            'last_name': 'Doe',
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)  # Redirects to login

        new_user = User.objects.get(username='newuser')
        self.assertEqual(new_user.role, 'individual')
        self.assertEqual(new_user.email, 'newuser@example.com')

    def test_registration_ignores_tampered_privileged_role(self):
        url = reverse('users:register')
        data = {
            'username': 'attacker',
            'email': 'attacker@example.com',
            'password1': 'NewPass123!',
            'password2': 'NewPass123!',
            'role': 'moderator',  # Attempted injection
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)

        user = User.objects.get(username='attacker')
        self.assertEqual(user.role, 'individual')

    def test_login_and_logout_flow(self):
        login_url = reverse('users:login')
        response = self.client.post(login_url, {
            'username': self.username,
            'password': self.password,
        })
        self.assertRedirects(response, '/dashboard/')

        logout_url = reverse('users:logout')
        response = self.client.post(logout_url)
        self.assertRedirects(response, reverse('users:login'))

    def test_failed_login(self):
        login_url = reverse('users:login')
        response = self.client.post(login_url, {
            'username': self.username,
            'password': 'WrongPassword',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context['form'], None, 'Please enter a correct username and password. Note that both fields may be case-sensitive.')

    def test_profile_view_requires_authentication(self):
        profile_url = reverse('users:profile')
        response = self.client.get(profile_url)
        self.assertEqual(response.status_code, 302)

        self.client.login(username=self.username, password=self.password)
        response = self.client.get(profile_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.username)

    def test_dashboard_requires_authentication(self):
        dashboard_url = reverse('dashboard:index')
        response = self.client.get(dashboard_url)
        self.assertEqual(response.status_code, 302)

        self.client.login(username=self.username, password=self.password)
        response = self.client.get(dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Dashboard')

    def test_password_reset_flow(self):
        reset_url = reverse('users:password_reset')
        response = self.client.post(reset_url, {'email': self.email})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('password reset', mail.outbox[0].subject.lower())

        