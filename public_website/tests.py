from django.test import TestCase, Client
from django.urls import reverse

class PublicSiteTestCase(TestCase):
    def setUp(self):
        self.client = Client()

    def test_home_page(self):
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)

    def test_check_page(self):
        response = self.client.get(reverse('check'))
        self.assertEqual(response.status_code, 200)
