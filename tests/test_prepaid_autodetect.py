from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from payments.models import Transaction, SiteSettings, Plan
from payments.services import get_user_prepaid_balance, deduct_user_prepaid_balance, get_topup_difference
from verification.models import VerificationRequest

User = get_user_model()


class PrepaidAutoDetectionTests(TestCase):
    def setUp(self):
        self.client = Client(SERVER_NAME='localhost')
        self.settings = SiteSettings.get()
        self.settings.is_monetization_active = True
        self.settings.free_tier_enabled = False
        self.settings.price_public_check = 500
        self.settings.price_verification_basic = 1500
        self.settings.price_verification_business = 3500
        self.settings.save()

        self.user = User.objects.create_user(
            username='prepaid_user',
            email='prepaid@example.com',
            password='TestPassword123!',
            role='individual'
        )
        self.client.force_login(self.user)

    def test_topup_difference_calculation(self):
        """Top-up difference calculates shortfall while respecting Paystack 100 NGN minimum."""
        # Zero balance, 3500 needed -> 3500
        self.assertEqual(get_topup_difference(0, 3500), 3500)
        # 1500 balance, 3500 needed -> 2000
        self.assertEqual(get_topup_difference(1500, 3500), 2000)
        # 3450 balance, 3500 needed (50 shortfall) -> enforces 100 NGN minimum for Paystack
        self.assertEqual(get_topup_difference(3450, 3500), 100)
        # Exact or surplus balance -> 0 needed
        self.assertEqual(get_topup_difference(3500, 3500), 0)
        self.assertEqual(get_topup_difference(5000, 3500), 0)

    def test_dynamic_balance_cross_service_deduction(self):
        """User pays 3500 NGN and uses portions across different services dynamically."""
        # 1. User deposits / pays 3500
        Transaction.objects.create(
            user=self.user,
            reference='VNG-PAYG-3500',
            amount_kobo=350000,
            status='success',
            is_active=True,
            paystack_response={'data': {'metadata': {'service': 'verification'}}}
        )
        self.assertEqual(get_user_prepaid_balance(self.user), 3500)

        # 2. User spends 1500 on a basic verification
        ok, rem = deduct_user_prepaid_balance(self.user, 1500, "Basic Verification")
        self.assertTrue(ok)
        self.assertEqual(rem, 2000)
        self.assertEqual(get_user_prepaid_balance(self.user), 2000)

        # 3. User spends 1500 on an employer / staff check
        ok2, rem2 = deduct_user_prepaid_balance(self.user, 1500, "Staff Check")
        self.assertTrue(ok2)
        self.assertEqual(rem2, 500)
        self.assertEqual(get_user_prepaid_balance(self.user), 500)

        # 4. User spends the remaining 500 on a public search
        ok3, rem3 = deduct_user_prepaid_balance(self.user, 500, "Public Check")
        self.assertTrue(ok3)
        self.assertEqual(rem3, 0)
        self.assertEqual(get_user_prepaid_balance(self.user), 0)

        # 5. Further spend fails due to insufficient funds
        ok4, rem4 = deduct_user_prepaid_balance(self.user, 500, "Another Check")
        self.assertFalse(ok4)
        self.assertEqual(rem4, 0)

    def test_public_check_with_prepaid_balance(self):
        """User with available balance is recognized as direct paid on /check/."""
        Transaction.objects.create(
            user=self.user,
            reference='VNG-PAYG-1000',
            amount_kobo=100000,
            status='success',
            is_active=True,
            paystack_response={'data': {'metadata': {'service': 'topup'}}}
        )

        res = self.client.get(reverse('check'))
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.context['is_direct_paid'])

    def test_verification_submits_with_prepaid_balance(self):
        """User with 3500 balance submits comprehensive verification; balance is deducted."""
        tx = Transaction.objects.create(
            user=self.user,
            reference='VNG-PAYG-3500-VERIF',
            amount_kobo=350000,
            status='success',
            is_active=True,
            paystack_response={'data': {'metadata': {'service': 'verification'}}}
        )

        # GET verification form
        res = self.client.get(reverse('verification:create'))
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.context['has_balance'])
        self.assertEqual(res.context['user_balance'], 3500)

        # POST form without prior explicit paid_ref; consumes dynamically from available balance
        form_data = {
            'subject_name': 'Sterling Vanguard Properties Ltd',
            'subject_type': 'business',
            'verification_type': 'full_check',
            'identifier_type': 'cac',
            'identifier_value': 'RC-1298492',
            'notes': 'Please perform comprehensive verification.',
            'terms_confirmed': 'on',
        }
        res_post = self.client.post(reverse('verification:create'), form_data)
        self.assertEqual(res_post.status_code, 302)

        # Original transaction consumed, balance is 0
        tx.refresh_from_db()
        self.assertFalse(tx.is_active)
        self.assertEqual(get_user_prepaid_balance(self.user), 0)

        # Verification request created with comprehensive tier
        req = VerificationRequest.objects.filter(requester=self.user).first()
        self.assertIsNotNone(req)
        self.assertIn('Comprehensive Due Diligence Tier', req.notes)

    def test_dashboard_dismissal_and_plans_page_persistence(self):
        """Dashboard alert is dismissible, while Sub/Plans page permanently shows the available balance."""
        Transaction.objects.create(
            user=self.user,
            reference='VNG-PAYG-DASH-3500',
            amount_kobo=350000,
            status='success',
            is_active=True,
            paystack_response={'data': {'metadata': {'service': 'verification'}}}
        )

        # 1. First visit to dashboard: unconsumed order banner is present
        res1 = self.client.get(reverse('dashboard:index'))
        self.assertEqual(res1.status_code, 200)
        self.assertIn('unconsumed_orders', res1.context)
        self.assertEqual(len(res1.context['unconsumed_orders']), 1)
        self.assertContains(res1, 'active payment ready to use')
        self.assertContains(res1, 'btn-outline-primary')

        # 2. User dismisses the banner via /payments/dismiss-banner/ (AJAX request)
        dismiss_res = self.client.post(
            reverse('payments:dismiss_prepaid_banner'),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(dismiss_res.status_code, 200)

        # 3. Next visit to dashboard: banner is suppressed
        res2 = self.client.get(reverse('dashboard:index'))
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(len(res2.context['unconsumed_orders']), 0)
        self.assertNotContains(res2, 'active payment ready to use')

        # 4. Visiting My Subscription page: Available Account Balance is displayed
        res_sub = self.client.get(reverse('payments:my_subscription'))
        self.assertEqual(res_sub.status_code, 200)
        self.assertEqual(res_sub.context['user_balance'], 3500)
        self.assertContains(res_sub, 'Available Account Balance')
        self.assertContains(res_sub, '3500')
        self.assertContains(res_sub, 'This credit is ready to be applied across any services')
        self.assertNotContains(res_sub, 'Unknown Plan')

        # 5. Visiting Plans/Rates page: clean public display without account balance banner
        res_plans = self.client.get(reverse('payments:plans'))
        self.assertEqual(res_plans.status_code, 200)
        self.assertNotContains(res_plans, 'Available Account Balance')

    def test_transaction_item_display_name(self):
        """Transaction item_display_name returns human-friendly service names instead of Unknown Plan."""
        tx_payg = Transaction.objects.create(
            user=self.user,
            reference='VNG-PAYG-TEST',
            amount_kobo=350000,
            paystack_response={'data': {'metadata': {'service': 'verification', 'tier': 'full_check'}}}
        )
        self.assertEqual(tx_payg.item_display_name, "Due Diligence Verification")

        tx_staff = Transaction.objects.create(
            user=self.user,
            reference='VNG-STAFF-TEST',
            amount_kobo=150000,
            paystack_response={'data': {'metadata': {'service': 'staff_check'}}}
        )
        self.assertEqual(tx_staff.item_display_name, "Staff Background Check")

        tx_cert = Transaction.objects.create(
            user=self.user,
            reference='VNG-CERT-TEST',
            amount_kobo=350000,
            paystack_response={'data': {'metadata': {'service': 'certificate'}}}
        )
        self.assertEqual(tx_cert.item_display_name, "TrustPass Clearance Certificate")

        tx_bal = Transaction.objects.create(
            user=self.user,
            reference='VNG-BAL-TEST1234',
            amount_kobo=100000
        )
        self.assertEqual(tx_bal.item_display_name, "Pre-Paid Account Balance")

        tx_direct = Transaction.objects.create(
            user=self.user,
            reference='VNG-GENERIC-TEST',
            amount_kobo=100000
        )
        self.assertEqual(tx_direct.item_display_name, "Direct Payment")

    def test_payment_success_message_format_and_single_display(self):
        """Unified success message format is used and displayed exactly once with close button."""
        tx = Transaction.objects.create(
            user=self.user,
            reference='VNG-71E915A168AF4872',
            amount_kobo=350000,
            status='success',
            is_active=True,
            paystack_response={
                'data': {
                    'metadata': {
                        'service': 'verification',
                        'tier': 'full_check'
                    }
                }
            }
        )
        session = self.client.session
        session['vng_pending_ref'] = tx.reference
        session.save()

        res = self.client.get(reverse('payments:callback') + f"?reference={tx.reference}", follow=True)
        self.assertEqual(res.status_code, 200)

        expected_msg = "Payment Successful! Your payment Reference VNG-71E915A168AF4872 (₦3,500) for Full Comprehensive Due Diligence Verification has been confirmed. You may now proceed with your request."
        self.assertContains(res, expected_msg)

        # Confirm the message appears exactly once in the HTML response (no double message)
        content_str = res.content.decode('utf-8')
        self.assertEqual(content_str.count(expected_msg), 1)

        # Confirm close button is present for dismissal
        self.assertContains(res, 'btn-close')

    def test_payment_failure_message_format(self):
        """Unified failed message format is shown when payment fails."""
        tx = Transaction.objects.create(
            user=self.user,
            reference='VNG-FAIL-1234',
            amount_kobo=350000,
            status='failed',
            is_active=False,
            failure_reason='Card declined by issuer',
            paystack_response={'data': {'metadata': {'service': 'verification'}}}
        )
        session = self.client.session
        session['vng_pending_ref'] = tx.reference
        session.save()

        res = self.client.get(reverse('payments:callback') + f"?reference={tx.reference}", follow=True)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Payment Unsuccessful: Your payment Reference VNG-FAIL-1234 could not be completed.")

    def test_admin_financial_report_shows_item_display_name(self):
        """Admin Financial Report Transaction Ledger and CSV export show item_display_name instead of empty."""
        from django.contrib.auth import get_user_model
        admin_user = get_user_model().objects.create_superuser(
            username='finadmin',
            email='finadmin@example.com',
            password='Password123!'
        )
        tx = Transaction.objects.create(
            user=self.user,
            reference='VNG-FIN-TEST-001',
            amount_kobo=250000,
            status='success',
            is_active=True,
            paystack_response={'data': {'metadata': {'service': 'certificate'}}}
        )
        self.client.force_login(admin_user)

        # 1. Web view test
        res = self.client.get(reverse('admin_portal:financial_report'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Plan / Service')
        self.assertContains(res, 'TrustPass Clearance Certificate')

        # 2. CSV export test
        res_csv = self.client.get(reverse('admin_portal:financial_report') + '?download=csv')
        self.assertEqual(res_csv.status_code, 200)
        csv_content = res_csv.content.decode('utf-8')
        self.assertIn('Plan / Service', csv_content)
        self.assertIn('TrustPass Clearance Certificate', csv_content)

    def test_plan_monthly_wallet_credit_calculation(self):
        """Plan.monthly_wallet_credit returns credit_value_naira if set, else price_naira."""
        plan_custom = Plan.objects.create(
            name="Pro Growth Test",
            slug="pro-growth-test",
            price_kobo=2500000,  # ₦25,000
            credit_value_naira=40000,  # ₦40,000
        )
        self.assertEqual(plan_custom.price_naira, 25000)
        self.assertEqual(plan_custom.monthly_wallet_credit, 40000)

        plan_default = Plan.objects.create(
            name="Standard Default Test",
            slug="standard-default-test",
            price_kobo=1500000,  # ₦15,000
            credit_value_naira=0,
        )
        self.assertEqual(plan_default.monthly_wallet_credit, 15000)

    def test_subscription_activation_loads_wallet_and_deducts_on_service(self):
        """Activating a subscription loads the plan's dynamic wallet credit and allows service consumption."""
        from payments.services import _activate_subscription, get_user_prepaid_balance, check_user_entitlement, consume_user_entitlement
        plan = Plan.objects.create(
            name="Executive Test Plan",
            slug="executive-test-plan",
            price_kobo=2500000,
            credit_value_naira=40000,
        )
        tx = Transaction.objects.create(
            user=self.user,
            plan=plan,
            reference="VNG-SUB-TEST-INVOICE",
            amount_kobo=2500000,
            status="success",
            is_active=True,
        )
        _activate_subscription(tx, {'customer': {'customer_code': 'CUS_123'}, 'subscription_code': 'SUB_123'})

        # 1. Invoice transaction is marked non-active for balance
        tx.refresh_from_db()
        self.assertFalse(tx.is_active)

        # 2. User wallet now holds the ₦40,000 allowance
        user_balance = get_user_prepaid_balance(self.user)
        self.assertEqual(user_balance, 40000)

        # 3. Entitlement check recognizes subscriber's dynamic wallet
        allowed, reason, details = check_user_entitlement(self.user, service='certificate', cost=1)
        self.assertTrue(allowed)
        self.assertEqual(reason, 'subscribed')
        self.assertTrue(details.get('is_wallet'))

        # 4. Service consumption deducts from wallet
        consumed = consume_user_entitlement(self.user, service='certificate', cost=1)
        self.assertTrue(consumed)
        new_balance = get_user_prepaid_balance(self.user)
        price_cert = SiteSettings.get().get_service_price('certificate')
        self.assertEqual(new_balance, 40000 - price_cert)

    def test_admin_wallet_topup_view(self):
        """Admin can top up PAYG wallet balance for user or employer via AdminUserWalletTopupView."""
        admin = User.objects.create_superuser(
            username='superadmin',
            email='admin@example.com',
            password='AdminPassword123!',
        )
        self.client.force_login(admin)

        initial_bal = get_user_prepaid_balance(self.user)
        url = reverse('admin_portal:wallet_topup', kwargs={'public_id': self.user.public_id})

        # Post top-up of 15,000 NGN
        response = self.client.post(url, {
            'amount_naira': '15000',
            'reason': 'Corporate bulk advance credit',
        })
        self.assertEqual(response.status_code, 302)

        # Balance increased by 15,000
        new_bal = get_user_prepaid_balance(self.user)
        self.assertEqual(new_bal, initial_bal + 15000)

        # Transaction exists with type admin_manual_topup and custom reason
        topup_tx = Transaction.objects.filter(user=self.user, reference__startswith='VNG-BAL-').latest('created_at')
        self.assertEqual(topup_tx.amount_kobo, 1500000)
        self.assertTrue(topup_tx.is_active)
        self.assertEqual(topup_tx.item_display_name, "Corporate bulk advance credit")
        self.assertEqual(topup_tx.reason, "Corporate bulk advance credit")

        # Top-up with blank reason defaults to "Admin Wallet Top-Up"
        self.client.post(url, {
            'amount_naira': '5000',
            'reason': '',
        })
        default_tx = Transaction.objects.filter(user=self.user, reference__startswith='VNG-BAL-').latest('created_at')
        self.assertEqual(default_tx.item_display_name, "Admin Wallet Top-Up")



