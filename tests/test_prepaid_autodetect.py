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

    def test_public_check_partial_balance_ui_and_topup(self):
        """User with ₦50 balance against ₦250 check fee sees ₦200 topup difference and ₦50 is applied."""
        from unittest.mock import patch
        self.settings.price_public_check = 250
        self.settings.save()

        # Create ₦50 balance for user
        Transaction.objects.create(
            user=self.user,
            reference='VNG-BAL-50',
            amount_kobo=5000,
            status='success',
            is_active=True,
            paystack_response={'data': {'metadata': {'service': 'topup'}}}
        )
        self.assertEqual(get_user_prepaid_balance(self.user), 50)

        # 1. GET /check/ verifies context and template rendering
        res = self.client.get(reverse('check'))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context['user_balance'], 50)
        self.assertEqual(res.context['topup_needed'], 200)
        content = res.content.decode('utf-8')
        self.assertIn('Account Balance Applied:', content)
        self.assertIn('50', content)
        self.assertIn('200', content)

        # 2. POST action=payg with partial balance: deducts ₦50, initializes checkout for ₦200
        with patch('payments.services.requests.post') as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {
                'status': True,
                'data': {
                    'authorization_url': 'https://checkout.paystack.com/test-url',
                    'access_code': 'test-code',
                    'reference': 'VNG-CHK-TEST-REF',
                }
            }
            post_res = self.client.post(reverse('check'), {
                'action': 'payg',
                'identifier_type': 'nin',
                'identifier_value': '12345678901',
            })
            self.assertEqual(post_res.status_code, 302)
            self.assertEqual(post_res.url, 'https://checkout.paystack.com/test-url')

            # Balance deducted from 50 to 0
            self.assertEqual(get_user_prepaid_balance(self.user), 0)

            # Checkout initialized for ₦200
            called_json = mock_post.call_args[1]['json']
            self.assertEqual(called_json['amount'], 20000)  # 200 NGN in kobo

    def test_public_check_sufficient_balance_post_unlocks_directly(self):
        """User with ₦500 balance against ₦250 check fee unlocks directly from balance without Paystack."""
        self.settings.price_public_check = 250
        self.settings.save()

        Transaction.objects.create(
            user=self.user,
            reference='VNG-BAL-500',
            amount_kobo=50000,
            status='success',
            is_active=True,
            paystack_response={'data': {'metadata': {'service': 'topup'}}}
        )
        self.assertEqual(get_user_prepaid_balance(self.user), 500)

        post_res = self.client.post(reverse('check'), {
            'action': 'payg',
            'identifier_type': 'nin',
            'identifier_value': '12345678901',
        })
        self.assertEqual(post_res.status_code, 302)
        self.assertIn('paid_ref=VNG-BAL-', post_res.url)

        # Balance deducted from 500 to 250
        self.assertEqual(get_user_prepaid_balance(self.user), 250)

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
        self.assertContains(res_sub, '3,500')
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




    def test_update_service_join_with_prepaid_balance(self):
        """User can join Continuous Update Service using available prepaid balance."""
        from verification.models import VerificationCertificate
        from identities.models import SubjectEntity
        from django.utils import timezone
        from datetime import timedelta

        # 1. Give user 5000 NGN prepaid balance
        Transaction.objects.create(
            user=self.user,
            reference='VNG-BAL-TEST-5000',
            amount_kobo=500000,
            status='success',
            is_active=True,
        )
        self.assertEqual(get_user_prepaid_balance(self.user), 5000)

        # 2. Create active certificate within grace period
        subj = SubjectEntity.objects.create(name="Prepaid User", type="person")
        cert = VerificationCertificate.objects.create(
            certificate_id='VNG-CERT-UPDATE-1',
            holder=self.user,
            subject=subj,
            check_level='standard',
            status='active',
            issued_at=timezone.now(),
        )

        join_url = reverse('verification:update_service_join')
        res = self.client.post(join_url, {
            'certificate_id': cert.certificate_id,
            'full_name': 'Prepaid User',
            'email': self.user.email,
            'phone_number': '08012345678',
            'residential_address': '123 Victoria Island, Lagos',
            'declaration': 'on',
        })
        self.assertEqual(res.status_code, 302)
        self.assertIn('/verification/update-service/portal/', res.url)

        # 3. Certificate monitoring should now be active
        cert.refresh_from_db()
        self.assertTrue(cert.is_monitoring_active)
        self.assertTrue(cert.is_monitoring_valid)

        # 4. 3000 NGN deducted from user prepaid balance: 5000 - 3000 = 2000
        new_balance = get_user_prepaid_balance(self.user)
        self.assertEqual(new_balance, 2000)

    def test_paystack_callback_monitoring_sets_transaction_inactive(self):
        """Paying for monitoring via Paystack sets transaction.is_active=False so balance does not inflate."""
        from verification.models import VerificationCertificate
        from identities.models import SubjectEntity
        from django.utils import timezone

        subj = SubjectEntity.objects.create(name="Paystack User", type="person")
        cert = VerificationCertificate.objects.create(
            certificate_id='VNG-CERT-UPDATE-2',
            holder=self.user,
            subject=subj,
            check_level='standard',
            status='active',
            issued_at=timezone.now(),
        )

        initial_balance = get_user_prepaid_balance(self.user)

        tx = Transaction.objects.create(
            user=self.user,
            reference='VNG-PAY-MONITOR-3000',
            amount_kobo=300000,
            status='success',
            is_active=True,
            paystack_response={
                'data': {
                    'metadata': {
                        'service': 'monitoring',
                        'certificate_id': cert.certificate_id,
                        'email': self.user.email,
                    }
                }
            }
        )

        from payments.views import _route_payg_success
        from django.test import RequestFactory
        factory = RequestFactory()
        req = factory.get('/payments/callback/')
        req.user = self.user
        from django.contrib.messages.storage.fallback import FallbackStorage
        setattr(req, 'session', {})
        setattr(req, '_messages', FallbackStorage(req))

        res = _route_payg_success(req, tx)
        self.assertEqual(res.status_code, 302)

        # Transaction MUST be deactivated
        tx.refresh_from_db()
        self.assertFalse(tx.is_active)

        # Balance must NOT be inflated by the monitoring payment
        after_balance = get_user_prepaid_balance(self.user)
        self.assertEqual(after_balance, initial_balance)

    def test_bulk_upload_checkout_review_accessible_to_individual_user(self):
        """A non-employer user can access bulk_upload checkout review without 403."""
        self.client.force_login(self.user)  # Individual user (not employer)
        res = self.client.get(reverse('payments:service_checkout_review', args=['bulk_upload']))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Bulk Candidate Screening (CSV Upload)')
        self.assertContains(res, 'Per-Candidate Batch Screening')

    def test_bulk_upload_payment_routing_by_role(self):
        """After bulk_upload payment, employer redirects to bulk upload tool, individual to dashboard."""
        from payments.views import _route_payg_success
        from django.test import RequestFactory
        from django.contrib.messages.storage.fallback import FallbackStorage

        tx = Transaction.objects.create(
            user=self.user,
            reference='VNG-BULK-TEST-001',
            amount_kobo=25000,
            status='success',
            is_active=True,
            paystack_response={
                'data': {
                    'metadata': {
                        'service': 'bulk_upload',
                    }
                }
            }
        )

        factory = RequestFactory()
        req = factory.get('/payments/callback/')
        req.user = self.user  # individual
        setattr(req, 'session', {})
        setattr(req, '_messages', FallbackStorage(req))

        res_ind = _route_payg_success(req, tx)
        self.assertEqual(res_ind.status_code, 302)
        self.assertEqual(res_ind.url, reverse('dashboard:index'))

        # Employer user
        self.user.role = 'employer'
        self.user.save(update_fields=['role'])

        req2 = factory.get('/payments/callback/')
        req2.user = self.user
        setattr(req2, 'session', {})
        setattr(req2, '_messages', FallbackStorage(req2))

        res_emp = _route_payg_success(req2, tx)
        self.assertEqual(res_emp.status_code, 302)
        self.assertIn(reverse('employer:bulk_upload_create'), res_emp.url)
        self.assertIn(tx.reference, res_emp.url)

    def test_admin_financial_report_filters_payment_types(self):
        """Admin can filter financial reports by specific payment types and plans."""
        self.user.is_staff = True
        self.user.is_superuser = True
        self.user.save(update_fields=['is_staff', 'is_superuser'])
        self.client.force_login(self.user)

        # Create transactions of different types
        tx_bulk = Transaction.objects.create(
            user=self.user,
            reference='VNG-TX-BULK-01',
            amount_kobo=50000,
            status='success',
            paystack_response={'data': {'metadata': {'service': 'bulk_upload'}}}
        )
        tx_mon = Transaction.objects.create(
            user=self.user,
            reference='VNG-TX-MON-01',
            amount_kobo=260000,
            status='success',
            paystack_response={'data': {'metadata': {'service': 'monitoring'}}}
        )

        # Filter bulk_upload
        res_bulk = self.client.get(reverse('admin_portal:financial_report') + '?plan=bulk_upload')
        self.assertEqual(res_bulk.status_code, 200)
        self.assertContains(res_bulk, 'VNG-TX-BULK-01')
        self.assertNotContains(res_bulk, 'VNG-TX-MON-01')

        # Filter monitoring
        res_mon = self.client.get(reverse('admin_portal:financial_report') + '?plan=monitoring')
        self.assertEqual(res_mon.status_code, 200)
        self.assertContains(res_mon, 'VNG-TX-MON-01')
        self.assertNotContains(res_mon, 'VNG-TX-BULK-01')

        # CSV Export with filter
        res_csv = self.client.get(reverse('admin_portal:financial_report') + '?plan=monitoring&download=csv')
        self.assertEqual(res_csv.status_code, 200)
        self.assertEqual(res_csv['Content-Type'], 'text/csv')
        self.assertIn('VNG-TX-MON-01', res_csv.content.decode())
        self.assertNotIn('VNG-TX-BULK-01', res_csv.content.decode())

    def test_update_service_audit_log_unique_employer_grouping(self):
        """Audit log groups repeated queries by the same organisation and displays the count."""
        from verification.models import VerificationCertificate, CertificateQueryLog
        from identities.models import SubjectEntity
        import uuid

        subj = SubjectEntity.objects.create(name="Audit Test", type="person")
        cert = VerificationCertificate.objects.create(
            certificate_id=f"VNG-{uuid.uuid4().hex[:8].upper()}",
            holder=self.user,
            subject=subj,
            check_level='standard',
            status='active',
        )

        # Create 4 queries from "Zictech Technologies" and 1 query from "Acme Corp"
        for _ in range(4):
            CertificateQueryLog.objects.create(
                certificate=cert,
                queried_by=self.user,
                organisation_name='Zictech Technologies',
                purpose='hiring'
            )
        CertificateQueryLog.objects.create(
            certificate=cert,
            queried_by=self.user,
            organisation_name='Acme Corp',
            purpose='tenancy'
        )

        # Set session for update service certificate
        session = self.client.session
        session['update_service_cert_id'] = cert.certificate_id
        session.save()

        res = self.client.get(reverse('verification:update_service_audit_log'))
        self.assertEqual(res.status_code, 200)

        # Context query_logs should have exactly 2 unique entries
        self.assertEqual(len(res.context['query_logs']), 2)

        # Should render Zictech Technologies with count (4)
        self.assertContains(res, 'Zictech Technologies (4)')
        # Should render Acme Corp without multiple count
        self.assertContains(res, 'Acme Corp')
        self.assertNotContains(res, 'Acme Corp (')

    def test_update_service_portal_exit_button_for_authenticated_vs_guest(self):
        """Authenticated users do not see 'Exit Portal'; guests do."""
        from verification.models import VerificationCertificate
        from identities.models import SubjectEntity
        from django.utils import timezone
        from datetime import timedelta
        import uuid

        subj = SubjectEntity.objects.create(name="Portal Test", type="person")
        cert = VerificationCertificate.objects.create(
            certificate_id=f"VNG-{uuid.uuid4().hex[:8].upper()}",
            holder=self.user,
            subject=subj,
            check_level='standard',
            status='active',
            is_monitoring_active=True,
            monitoring_activated_at=timezone.now(),
            monitoring_expires_at=timezone.now() + timedelta(days=365)
        )

        # Authenticated user
        self.client.force_login(self.user)
        res_auth = self.client.get(reverse('verification:update_service_portal') + f"?cert={cert.certificate_id}")
        self.assertEqual(res_auth.status_code, 200)
        self.assertNotContains(res_auth, 'Exit Portal')
        self.assertContains(res_auth, 'My Certificates')

        # Guest user
        self.client.logout()
        session = self.client.session
        session['update_service_cert_id'] = cert.certificate_id
        session.save()

        res_guest = self.client.get(reverse('verification:update_service_portal'))
        self.assertEqual(res_guest.status_code, 200)
        self.assertContains(res_guest, 'Exit Portal')

    def test_update_service_logout_redirects(self):
        """Logged-in users exiting update service go to my_certificates; guests to update_service_login."""
        # Authenticated
        self.client.force_login(self.user)
        res_auth = self.client.get(reverse('verification:update_service_logout'))
        self.assertEqual(res_auth.status_code, 302)
        self.assertEqual(res_auth.url, reverse('verification:my_certificates'))

        # Guest
        self.client.logout()
        res_guest = self.client.get(reverse('verification:update_service_logout'))
        self.assertEqual(res_guest.status_code, 302)
        self.assertEqual(res_guest.url, reverse('verification:update_service_login'))

    def test_employer_certificate_verify_partial_balance(self):
        """Employer with ₦50 balance against ₦250 fee sees ₦200 difference and balance is deducted on checkout."""
        from unittest.mock import patch
        employer = User.objects.create_user(
            username='employer_topup',
            email='employer_topup@example.com',
            password='TestPassword123!',
            role='employer'
        )
        self.client.force_login(employer)
        self.settings.price_certificate_verify = 250
        self.settings.save()

        # Give employer ₦50 balance
        Transaction.objects.create(
            user=employer,
            reference='VNG-EMP-50',
            amount_kobo=5000,
            status='success',
            is_active=True,
            paystack_response={'data': {'metadata': {'service': 'topup'}}}
        )
        self.assertEqual(get_user_prepaid_balance(employer), 50)

        # Post verify search with non-existent cert to trigger quota exceeded
        res = self.client.post(reverse('employer:certificate_verify'), {
            'action': 'verify',
            'certificate_id': 'VNG-2026-99E1E30C',
            'surname': 'Dorris',
            'date_of_birth': '1997-11-03',
        })
        self.assertEqual(res.status_code, 200)
        content = res.content.decode('utf-8')
        self.assertIn('200', content)
        self.assertIn('50', content)
        self.assertIn('Account Balance Applied:', content)

        # Now click PAYG: should deduct ₦50 balance and checkout for ₦200
        with patch('payments.services.requests.post') as mock_post:
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = {
                'status': True,
                'data': {
                    'authorization_url': 'https://checkout.paystack.com/test-cert',
                    'access_code': 'test-code',
                    'reference': 'VNG-CHK-CERT-REF',
                }
            }
            payg_res = self.client.post(reverse('employer:certificate_verify'), {
                'action': 'payg',
                'certificate_id': 'VNG-2026-99E1E30C',
                'surname': 'Dorris',
                'date_of_birth': '1997-11-03',
            })
            self.assertEqual(payg_res.status_code, 302)
            self.assertEqual(payg_res.url, 'https://checkout.paystack.com/test-cert')
            # Balance was deducted from 50 to 0
            self.assertEqual(get_user_prepaid_balance(employer), 0)

    def test_bulk_upload_no_confirm_popup(self):
        """CSV bulk upload should not use window.confirm modal."""
        employer = User.objects.create_user(
            username='emp_csv',
            email='emp_csv@example.com',
            password='TestPassword123!',
            role='employer'
        )
        self.client.force_login(employer)
        res = self.client.get(reverse('employer:bulk_upload_create'))
        self.assertEqual(res.status_code, 200)
        content = res.content.decode('utf-8')
        self.assertNotIn('confirmUpload', content)
        self.assertNotIn('confirm(', content)
