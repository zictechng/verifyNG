from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from payments.models import Transaction, Plan

User = get_user_model()


class AdminFinancialReportPaginationTests(TestCase):
    """
    Test suite for Admin Financial Reports Pagination:
    - 15 items per page for Revenue by Service & Plan
    - 15 items per page for Transaction Ledger
    - AJAX partial rendering without full page reload
    - Page number navigation and parameter preservation
    """

    def setUp(self):
        self.client = Client()

        # Admin user
        self.admin = User.objects.create_superuser(
            username='fin_admin',
            email='fin_admin@verifyng.com',
            password='AdminPass123!',
        )
        self.admin.is_staff = True
        self.admin.save(update_fields=['is_staff'])

        # Regular user
        self.user = User.objects.create_user(
            username='customer_one',
            email='cust@example.com',
            password='TestPass123!',
        )

        # Create sample subscription plan
        self.plan = Plan.objects.create(
            name='Enterprise Plan',
            slug='enterprise-plan',
            price_kobo=5000000,
            interval='monthly',
            is_active=True,
        )

        # Create 22 dummy successful transactions to ensure > 15 rows for pagination testing
        now = timezone.now()
        for i in range(1, 23):
            Transaction.objects.create(
                user=self.user,
                reference=f"TRX-TEST-PAG-{i:03d}",
                paystack_reference=f"PSTK-{i:03d}",
                amount_kobo=1000000 + (i * 10000),  # e.g. 10,000 + i*100 Naira
                status='success',
                plan=self.plan if i % 2 == 0 else None,
                created_at=now - timezone.timedelta(days=i % 30),
                paystack_response={
                    'data': {
                        'metadata': {
                            'service': f'service_variant_{i}',
                            'item_name': f'Custom Service {i}'
                        }
                    }
                }
            )

    def test_full_page_renders_with_15_per_page(self):
        """Full page GET returns status 200 with 15 transactions on first page."""
        self.client.force_login(self.admin)
        url = reverse('admin_portal:financial_report')
        res = self.client.get(url)

        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, 'admin_portal/financial_report.html')
        self.assertTemplateUsed(res, 'admin_portal/_financial_services_partial.html')
        self.assertTemplateUsed(res, 'admin_portal/_financial_ledger_partial.html')

        # Context pagination assertions
        transactions = res.context['transactions']
        self.assertEqual(len(transactions), 15)  # 15 items per page
        self.assertEqual(transactions.paginator.per_page, 15)
        self.assertEqual(transactions.paginator.count, 22)
        self.assertTrue(transactions.has_next())

        # Services & Plan pagination
        services_page = res.context['plan_breakdown_page']
        self.assertEqual(services_page.paginator.per_page, 15)

    def test_ajax_ledger_partial_returns_page_2(self):
        """
        Requesting ?ajax_section=ledger&page=2 returns ONLY the ledger card
        partial template with the remaining 7 transactions.
        """
        self.client.force_login(self.admin)
        url = reverse('admin_portal:financial_report')
        res = self.client.get(url, {
            'ajax_section': 'ledger',
            'page': 2,
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, 'admin_portal/_financial_ledger_partial.html')
        self.assertTemplateNotUsed(res, 'admin_portal/financial_report.html')
        self.assertTemplateNotUsed(res, 'admin_portal/base_admin.html')

        # 22 total - 15 on page 1 = 7 on page 2
        transactions = res.context['transactions']
        self.assertEqual(transactions.number, 2)
        self.assertEqual(len(transactions), 7)
        self.assertContains(res, 'Showing 16–22 of 22 transaction(s)')

    def test_ajax_services_partial_page_navigation(self):
        """
        Requesting ?ajax_section=services returns ONLY the services partial template.
        """
        self.client.force_login(self.admin)
        url = reverse('admin_portal:financial_report')
        res = self.client.get(url, {
            'ajax_section': 'services',
            'services_page': 1,
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, 'admin_portal/_financial_services_partial.html')
        self.assertTemplateNotUsed(res, 'admin_portal/financial_report.html')
        self.assertContains(res, 'Revenue by Service &amp; Plan')

    def test_export_csv_and_pdf_still_work_unaffected(self):
        """CSV and PDF exports function correctly and are not broken by partial pagination."""
        self.client.force_login(self.admin)
        url = reverse('admin_portal:financial_report')

        res_csv = self.client.get(url, {'download': 'csv'})
        self.assertEqual(res_csv.status_code, 200)
        self.assertEqual(res_csv['Content-Type'], 'text/csv')

        res_pdf = self.client.get(url, {'download': 'pdf'})
        self.assertEqual(res_pdf.status_code, 200)
        self.assertEqual(res_pdf['Content-Type'], 'application/pdf')

    def test_non_admin_cannot_access_financial_report(self):
        """Regular non-staff users cannot access financial report or partials."""
        self.client.force_login(self.user)
        url = reverse('admin_portal:financial_report')
        res = self.client.get(url)
        self.assertIn(res.status_code, (302, 403))

        res_partial = self.client.get(url, {'ajax_section': 'ledger'})
        self.assertIn(res_partial.status_code, (302, 403))
