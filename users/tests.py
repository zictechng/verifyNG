from unittest.mock import patch
from django.test import TestCase, override_settings
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

    @patch('notifications.tasks.send_broadcast_email_task.delay')
    def test_password_reset_flow(self, mock_send):
        reset_url = reverse('users:password_reset')
        response = self.client.post(reset_url, {'email': self.email})
        self.assertEqual(response.status_code, 302)
        mock_send.assert_called_once()
        self.assertEqual(mock_send.call_args[1]['to_email'], self.email)
        self.assertIn('password', mock_send.call_args[1]['subject'].lower())


class VerifyAccountViewTestCase(TestCase):
    def setUp(self):
        self.username = 'verifyuser'
        self.password = 'StrongPass123!'
        self.email = 'verifyuser@example.com'
        self.user = User.objects.create_user(
            username=self.username,
            email=self.email,
            password=self.password,
            role='individual'
        )

    def test_verify_account_requires_authentication(self):
        url = reverse('users:verify_account')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)

    def test_verify_account_renders_successfully(self):
        self.client.login(username=self.username, password=self.password)
        url = reverse('users:verify_account')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Verify Account')
        self.assertContains(response, 'Government Identity Document')
        self.assertContains(response, 'Alternative Person Verification')
        self.assertContains(response, 'Select a Verification Method to Begin')

    def test_profile_tab_verification_redirects_to_verify_account(self):
        self.client.login(username=self.username, password=self.password)
        profile_tab_url = reverse('users:profile') + '?tab=verification'
        response = self.client.get(profile_tab_url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('users:verify_account'), response.url)

    def test_verify_account_with_method_parameter(self):
        self.client.login(username=self.username, password=self.password)
        url_gov = reverse('users:verify_account') + '?method=government_id'
        response_gov = self.client.get(url_gov)
        self.assertEqual(response_gov.status_code, 200)
        self.assertEqual(response_gov.context['selected_method'], 'government_id')

        url_alt = reverse('users:verify_account') + '?method=alternative'
        response_alt = self.client.get(url_alt)
        self.assertEqual(response_alt.status_code, 200)
        self.assertEqual(response_alt.context['selected_method'], 'alternative')

    def test_government_id_wizard_renders_all_seven_steps(self):
        """Verifies that all 7 question steps and camera/selfie elements are rendered."""
        self.client.login(username=self.username, password=self.password)
        url = reverse('users:verify_account') + '?method=government_id'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        # Step 1: Email
        self.assertContains(response, 'Verify Your Email Address')
        # Step 2: Phone with WhatsApp
        self.assertContains(response, 'Verify Your Phone Number')
        self.assertContains(response, 'Send Code via WhatsApp')
        # Step 3: Country
        self.assertContains(response, 'Select Document-Issuing Country')
        # Step 4: Document Type
        self.assertContains(response, 'Select Accepted Document Type')
        # Step 5: Government ID Document (Camera or Upload)
        self.assertContains(response, 'Submit Your Government-issued ID')
        # Step 6: Live Selfie
        self.assertContains(response, 'Complete Selfie Verification Exercise')
        # Step 7: Review & Submit
        self.assertContains(response, 'Review &amp; Submit for Verification')

    def test_phone_otp_send_and_verify_flow(self):
        """Tests sending phone OTP and verifying it successfully updates user.phone_verified."""
        self.client.login(username=self.username, password=self.password)
        # 1. Send OTP
        send_url = reverse('users:send_phone_otp')
        send_resp = self.client.post(send_url, data={'phone': '+2348012345678', 'channel': 'whatsapp'})
        self.assertEqual(send_resp.status_code, 200)
        data = send_resp.json()
        self.assertTrue(data['success'])
        otp_code = self.client.session.get('vng_phone_otp', {}).get('code')
        self.assertTrue(bool(otp_code))

        # 2. Verify OTP
        verify_url = reverse('users:verify_phone_otp')
        verify_resp = self.client.post(verify_url, data={'phone': '+2348012345678', 'code': otp_code})
        self.assertEqual(verify_resp.status_code, 200)
        self.assertTrue(verify_resp.json()['success'])

        self.user.refresh_from_db()
        self.assertTrue(self.user.phone_verified)
        self.assertEqual(self.user.phone_number, '+2348012345678')

    def test_email_otp_send_and_verify_flow(self):
        """Tests sending email OTP and verifying it successfully updates user.email_verified."""
        self.client.login(username=self.username, password=self.password)
        # 1. Send OTP
        send_url = reverse('users:send_email_otp')
        send_resp = self.client.post(send_url)
        self.assertEqual(send_resp.status_code, 200)
        data = send_resp.json()
        self.assertTrue(data['success'])
        otp_code = self.client.session.get('vng_email_otp', {}).get('code')
        self.assertTrue(bool(otp_code))

        # 2. Verify OTP
        verify_url = reverse('users:verify_email_otp')
        verify_resp = self.client.post(verify_url, data={'code': otp_code})
        self.assertEqual(verify_resp.status_code, 200)
        self.assertTrue(verify_resp.json()['success'])

        self.user.refresh_from_db()
        self.assertTrue(self.user.email_verified)

    def test_identity_verification_submission_with_selfie_and_camera_data(self):
        """Tests end-to-end submission with base64 camera image data and phone verification."""
        self.client.login(username=self.username, password=self.password)
        submit_url = reverse('users:verify_identity_submit')

        # 1x1 transparent PNG data URL
        fake_data_url = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

        response = self.client.post(submit_url, {
            'issuing_country': 'NG',
            'id_type': 'nin',
            'id_number': '12345678901',
            'id_document_data': fake_data_url,
            'id_selfie_data': fake_data_url,
            'phone_number': '+2348012345678',
            'phone_verified': 'true',
            'email_verified': 'true',
        })
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.id_type, 'nin')
        self.assertEqual(self.user.id_number, '12345678901')
        self.assertEqual(self.user.id_verification_status, 'pending')
        self.assertTrue(self.user.has_id_document)
        self.assertTrue(self.user.has_selfie)
        self.assertTrue(self.user.phone_verified)
        self.assertEqual(self.user.phone_number, '+2348012345678')

    def test_all_54_african_countries_regional_dropdowns(self):
        """Validates that all 54 African countries have 100% verified cascading dropdowns across both levels."""
        from users.african_regions import get_all_african_regions_catalog
        catalog = get_all_african_regions_catalog()
        self.assertEqual(len(catalog), 54, "Catalog must contain exactly 54 African countries.")

        for country_code, data in catalog.items():
            self.assertEqual(data.get('lga_mode'), 'dropdown', f"{country_code} must have lga_mode='dropdown'")
            states = data.get('states', [])
            self.assertGreater(len(states), 0, f"{country_code} must have non-empty states list")
            lgas = data.get('lgas', {})
            for state in states:
                self.assertIn(state, lgas, f"{country_code} state '{state}' must exist in lgas dict")
                self.assertGreater(len(lgas[state]), 0, f"{country_code} state '{state}' must have non-empty list of subdivisions")

    def test_identity_verification_submission_with_state_and_lga(self):
        """Tests that optional state and LGA fields are saved to User model upon submission."""
        self.client.login(username=self.username, password=self.password)
        submit_url = reverse('users:verify_identity_submit')
        fake_data_url = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

        response = self.client.post(submit_url, {
            'issuing_country': 'NG',
            'id_type': 'nin',
            'id_number': '12345678902',
            'id_document_data': fake_data_url,
            'id_selfie_data': fake_data_url,
            'state': 'Lagos',
            'lga': 'Ikeja',
            'phone_number': '+2348012345679',
            'phone_verified': 'true',
            'email_verified': 'true',
        })
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.state, 'Lagos')
        self.assertEqual(self.user.lga, 'Ikeja')




        