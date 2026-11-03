import urllib.parse
import json
import logging
from datetime import timedelta
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404, JsonResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.generic import View, TemplateView

from core.rate_limiting import get_client_ip
from core.audit_utils import log_admin_action
from dashboard.admin_views import SuperAdminRequiredMixin
from notifications.email_templates import build_merchant_badge_approved, build_merchant_badge_rejected
from notifications.services import dispatch_notification
from payments.models import MerchantProfile, NigerianBank, SiteSettings
from payments.merchant_forms import MerchantApplicationForm
from reports.models import FraudReport
from reports.services import parse_client_device
from identities.models import Identifier
from identities.utils import hash_identifier_value

from payments.bank_services import resolve_bank_account

logger = logging.getLogger(__name__)


class ResolveBankAjaxView(View):
    """
    AJAX endpoint for instant real-time bank resolution on application and verification forms.
    Uses multi-tier caching (Redis -> Database Vault -> Paystack API).
    """
    def get(self, request, *args, **kwargs):
        account_number = request.GET.get('account_number', '').strip()
        bank_name = request.GET.get('bank_name', '').strip()
        if not account_number or not bank_name:
            return JsonResponse({'success': False, 'message': 'Account number and bank name are required.'}, status=400)
        
        result = resolve_bank_account(account_number, bank_name)
        return JsonResponse(result)


def get_merchant_fraud_reports(merchant: MerchantProfile):
    """
    Looks up any published or disputed fraud reports filed against the merchant's
    settlement bank account number or phone number via hashed identifiers.
    """
    hashes = []
    if merchant.bank_account:
        hashes.append(hash_identifier_value('account', merchant.bank_account))
    if merchant.whatsapp_number:
        clean_phone = merchant.whatsapp_number.replace('+', '').replace(' ', '').strip()
        hashes.append(hash_identifier_value('phone', clean_phone))

    if not hashes:
        return FraudReport.objects.none()

    matched_subject_ids = Identifier.objects.filter(
        value_hash__in=hashes
    ).values_list('subject_id', flat=True)

    return FraudReport.objects.filter(
        target_subject_id__in=matched_subject_ids,
        state__in=['published', 'disputed', 'under_review']
    )


class MerchantLandingView(View):
    """
    Public explanatory & onboarding landing page for the Verified Merchant Seal program.
    Educates vendors on benefits (building customer trust, avoiding imposter scams, conversion boost).
    Checks Tier 1 KYC eligibility and SiteSettings dynamic toggles/pricing.
    """
    template_name = "payments/merchant_landing.html"

    def get(self, request, *args, **kwargs):
        site_settings = SiteSettings.get()
        if not site_settings.merchant_badge_enabled:
            return render(request, "payments/merchant_disabled.html", {
                'site_settings': site_settings,
                'page_title': "Merchant Trust Badge Program Unavailable"
            })

        user = request.user if request.user.is_authenticated else None
        existing_profile = None
        tier1_verified = False
        employer_verified = False

        if user:
            existing_profile = MerchantProfile.objects.filter(user=user).first()
            tier1_verified = (user.id_verification_status == 'verified' or getattr(user, 'identity_verified', False))
            
            # Check employer CAC verification if applicable
            employer_prof = getattr(user, 'employer_profile', None)
            if employer_prof and employer_prof.is_verified:
                employer_verified = True

        context = {
            'site_settings': site_settings,
            'existing_profile': existing_profile,
            'tier1_verified': tier1_verified,
            'employer_verified': employer_verified,
            'is_free': site_settings.is_service_free('merchant_badge'),
            'price': site_settings.get_service_price('merchant_badge'),
            'trial_days': site_settings.merchant_badge_trial_days,
            'nigerian_banks': NigerianBank.objects.filter(is_active=True).order_by('name'),
        }
        return render(request, self.template_name, context)


class MerchantApplyView(LoginRequiredMixin, View):
    """
    Tier 2 Merchant Application portal.
    Requires prior Tier 1 KYC verification.
    Supports webcam photo capture, dropzone upload, and bank resolution.
    """
    template_name = "payments/merchant_apply.html"

    def dispatch(self, request, *args, **kwargs):
        site_settings = SiteSettings.get()
        if not site_settings.merchant_badge_enabled:
            messages.warning(request, "The Verified Merchant Seal program is currently closed to new applications.")
            return redirect('merchant_landing')

        # Check Tier 1 KYC gate
        user = request.user
        tier1_verified = (user.id_verification_status == 'verified' or getattr(user, 'identity_verified', False))
        
        employer_prof = getattr(user, 'employer_profile', None)
        employer_verified = bool(employer_prof and employer_prof.is_verified)

        if not (tier1_verified or employer_verified):
            messages.error(request, "You must complete Tier 1 identity verification before applying for a Verified Merchant Seal.")
            return redirect('users:profile')

        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        profile = MerchantProfile.objects.filter(user=request.user).first()
        form = MerchantApplicationForm(instance=profile, user=request.user)
        site_settings = SiteSettings.get()
        employer_prof = getattr(request.user, 'employer_profile', None)

        context = {
            'form': form,
            'profile': profile,
            'site_settings': site_settings,
            'is_free': site_settings.is_service_free('merchant_badge'),
            'price': site_settings.get_service_price('merchant_badge'),
            'trial_days': site_settings.merchant_badge_trial_days,
            'nigerian_banks': NigerianBank.objects.filter(is_active=True).order_by('name'),
            'employer_prof': employer_prof,
            'has_cac': bool(employer_prof and (employer_prof.company_rc_number or employer_prof.is_verified)),
        }
        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        profile = MerchantProfile.objects.filter(user=request.user).first()
        form = MerchantApplicationForm(request.POST, request.FILES, instance=profile, user=request.user)
        site_settings = SiteSettings.get()
        employer_prof = getattr(request.user, 'employer_profile', None)

        if form.is_valid():
            merchant = form.save(commit=False)
            merchant.user = request.user

            # If the profile was already active & verified, preserve active status so cosmetic updates don't revoke the badge!
            was_active = bool(profile and profile.status == 'active')
            if was_active:
                merchant.status = 'active'
                msg = f"Your Verified Merchant Seal profile details for '{merchant.store_name}' have been updated successfully."
            else:
                merchant.status = 'pending'
                merchant.rejection_reason = ""
                msg = f"Your application for '{merchant.store_name}' has been submitted successfully! Our compliance desk will review your details."

            # Telemetry collection
            user_agent = request.META.get('HTTP_USER_AGENT', '')
            client_ip = get_client_ip(request)
            device_info = parse_client_device(user_agent)

            merchant.submission_ip = client_ip
            merchant.submission_device = f"{device_info.get('device_type', 'Desktop')} - {device_info.get('os_family', 'Unknown OS')}"
            merchant.submission_browser = f"{device_info.get('browser_family', 'Unknown Browser')} {device_info.get('browser_version', '')}".strip()

            merchant.save()
            messages.success(request, msg)
            return redirect('merchant_apply')

        messages.error(request, "Please review the errors highlighted below.")
        context = {
            'form': form,
            'profile': profile,
            'site_settings': site_settings,
            'is_free': site_settings.is_service_free('merchant_badge'),
            'price': site_settings.get_service_price('merchant_badge'),
            'trial_days': site_settings.merchant_badge_trial_days,
            'nigerian_banks': NigerianBank.objects.filter(is_active=True).order_by('name'),
            'employer_prof': employer_prof,
            'has_cac': bool(employer_prof and (employer_prof.company_rc_number or employer_prof.is_verified)),
        }
        return render(request, self.template_name, context)


class MerchantBankChangeRequestView(LoginRequiredMixin, View):
    """
    Handles merchant submission to update their verified settlement bank account.
    Validates new NUBAN via live NIBSS resolution and files a pending change request
    for admin review and approval without interrupting their active public seal.
    """
    def post(self, request, *args, **kwargs):
        profile = get_object_or_404(MerchantProfile, user=request.user)

        new_bank_name = request.POST.get('new_bank_name', '').strip()
        new_bank_account = request.POST.get('new_bank_account', '').strip()

        if not new_bank_name or len(new_bank_account) != 10 or not new_bank_account.isdigit():
            messages.error(request, "Please enter a valid bank name and 10-digit NUBAN account number.")
            return redirect('merchant_apply')

        # Prevent duplicate identical requests
        if new_bank_account == profile.bank_account and new_bank_name.lower() == profile.bank_name.lower():
            messages.info(request, "This account is already your active verified settlement bank.")
            return redirect('merchant_apply')

        # Live NIBSS resolution
        from payments.merchant_forms import resolve_bank_account
        res = resolve_bank_account(new_bank_account, new_bank_name)
        if not res.get('success'):
            messages.error(request, res.get('message', 'Unable to verify account details with bank. Please check account number.'))
            return redirect('merchant_apply')

        resolved_name = res.get('account_name', '')
        bank_code = res.get('bank_code', '')

        profile.has_pending_bank_change = True
        profile.pending_bank_name = new_bank_name
        profile.pending_bank_code = bank_code
        profile.pending_bank_account = new_bank_account
        profile.pending_bank_account_name = resolved_name
        profile.pending_bank_requested_at = timezone.now()
        profile.pending_bank_rejection_reason = ""
        profile.save(update_fields=[
            'has_pending_bank_change',
            'pending_bank_name',
            'pending_bank_code',
            'pending_bank_account',
            'pending_bank_account_name',
            'pending_bank_requested_at',
            'pending_bank_rejection_reason'
        ])

        messages.success(
            request,
            f"Your request to update settlement bank to {new_bank_name} ({resolved_name}) has been submitted! "
            "Our compliance team will review and approve it. Your current verified bank remains active on your public seal."
        )
        return redirect('merchant_apply')


class PublicMerchantTrustView(View):
    """
    Public Verification Seal & Trust Dossier (/v/<slug>/).
    High reassurance trust page for buyers scanning the seal from Instagram bio, WhatsApp, or website badge.
    Displays:
    - Official Verified Status (Active / Under Dispute / Suspended)
    - Merchant Type (Individual Solopreneur or CAC Registered Entity)
    - Verified Settlement Bank Account (Masked NUBAN + Resolved NIBSS Name)
    - Active Fraud Reports count (0 reports = Safe to Transact)
    - Verified Social Channels (preventing clone account impersonation)
    - Embed code & Shareable bio links
    """
    template_name = "payments/public_merchant_trust.html"

    def get(self, request, slug, *args, **kwargs):
        merchant = get_object_or_404(MerchantProfile.objects.select_related('user'), store_slug__iexact=slug)

        # Count active/verified fraud petitions on this user or their bank account
        fraud_reports_count = get_merchant_fraud_reports(merchant).count()

        site_settings = SiteSettings.get()
        full_bio_url = request.build_absolute_uri(f"/trust-seal/v/{merchant.store_slug}/")
        embed_script_tag = f'<script src="{request.build_absolute_uri("/static/js/verifyng-badge.js")}" data-merchant="{merchant.store_slug}"></script>'

        # Professional Share Links & WhatsApp message
        wa_text = f"Buy with confidence! Check our official Verified Merchant Badge & verified payout bank on VerifyNG:\n{full_bio_url}"
        whatsapp_share_url = f"https://api.whatsapp.com/send?text={urllib.parse.quote(wa_text)}"
        
        tw_text = f"Check out our verified store trust seal on @VerifyNG: {full_bio_url}"
        twitter_share_url = f"https://twitter.com/intent/tweet?text={urllib.parse.quote(tw_text)}"
        
        fb_share_url = f"https://www.facebook.com/sharer/sharer.php?u={urllib.parse.quote(full_bio_url)}"
        linkedin_share_url = f"https://www.linkedin.com/sharing/share-offsite/?url={urllib.parse.quote(full_bio_url)}"

        context = {
            'merchant': merchant,
            'fraud_reports_count': fraud_reports_count,
            'full_bio_url': full_bio_url,
            'embed_script_tag': embed_script_tag,
            'site_settings': site_settings,
            'whatsapp_share_url': whatsapp_share_url,
            'twitter_share_url': twitter_share_url,
            'fb_share_url': fb_share_url,
            'linkedin_share_url': linkedin_share_url,
            'share_text': wa_text,
        }
        return render(request, self.template_name, context)


# ─────────────────────────────────────────────────────────────────────────────
# Admin Moderation Desk
# ─────────────────────────────────────────────────────────────────────────────

class AdminMerchantListView(SuperAdminRequiredMixin, TemplateView):
    """
    Admin Moderation Queue for Merchant Trust Badge Applications.
    Filter by status: pending, active, under_dispute, suspended, rejected.
    """
    template_name = "admin_portal/merchants.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        status_filter = self.request.GET.get('status', 'pending')
        search_query = self.request.GET.get('q', '').strip()

        qs = MerchantProfile.objects.select_related('user').order_by('-updated_at')

        if status_filter == 'bank_change':
            qs = qs.filter(has_pending_bank_change=True)
        elif status_filter and status_filter != 'all':
            qs = qs.filter(status=status_filter)

        if search_query:
            qs = qs.filter(
                Q(store_name__icontains=search_query) |
                Q(store_slug__icontains=search_query) |
                Q(user__email__icontains=search_query) |
                Q(bank_account__icontains=search_query) |
                Q(bank_account_name__icontains=search_query)
            )

        try:
            per_page = int(self.request.GET.get('per_page', 15))
        except (ValueError, TypeError):
            per_page = 15
        if per_page not in (15, 25, 50, 75, 100):
            per_page = 15

        paginator = Paginator(qs, per_page)
        page_num = self.request.GET.get('page', 1)
        page_obj = paginator.get_page(page_num)

        ctx['merchants'] = page_obj
        ctx['page_obj'] = page_obj
        ctx['per_page'] = per_page
        ctx['per_page_options'] = [15, 25, 50, 75, 100]
        ctx['status_filter'] = status_filter
        ctx['search_query'] = search_query
        ctx['pending_count'] = MerchantProfile.objects.filter(status='pending').count()
        ctx['active_count'] = MerchantProfile.objects.filter(status='active').count()
        ctx['dispute_count'] = MerchantProfile.objects.filter(status='under_dispute').count()
        ctx['suspended_count'] = MerchantProfile.objects.filter(status='suspended').count()
        ctx['bank_change_count'] = MerchantProfile.objects.filter(has_pending_bank_change=True).count()
        return ctx


class AdminMerchantDetailView(SuperAdminRequiredMixin, View):
    """
    Comprehensive Merchant Verification Moderation Desk:
    - Compare User Tier 1 Legal Identity vs Store Details
    - Check CAC registration if corporate
    - Inspect Live Webcam selfie photo
    - Inspect NIBSS/Paystack resolved account name
    - Device Telemetry: IP, Device Type, Browser
    - Approve / Put Under Dispute / Suspend / Reject with Reason
    - Dispatches custom transactional emails
    """
    template_name = "admin_portal/merchant_detail.html"

    def get(self, request, pk, *args, **kwargs):
        merchant = get_object_or_404(MerchantProfile.objects.select_related('user'), pk=pk)
        
        # Associated reports on this merchant
        reports = get_merchant_fraud_reports(merchant).order_by('-created_at')[:10]

        context = {
            'merchant': merchant,
            'reports': reports,
            'user_obj': merchant.user,
            'employer_profile': getattr(merchant.user, 'employer_profile', None),
        }
        return render(request, self.template_name, context)

    def post(self, request, pk, *args, **kwargs):
        merchant = get_object_or_404(MerchantProfile.objects.select_related('user'), pk=pk)
        action = request.POST.get('action')
        reason = request.POST.get('reason', '').strip()
        site_settings = SiteSettings.get()

        if action == 'approve':
            merchant.status = 'active'
            merchant.rejection_reason = ""
            merchant.approved_at = timezone.now()
            merchant.approved_by = request.user

            # If trial is configured, set trial ends at
            if site_settings.merchant_badge_trial_days:
                merchant.trial_ends_at = timezone.now() + timedelta(days=site_settings.merchant_badge_trial_days)

            merchant.save()

            # Dispatch notification & email
            subject, html_body, text_body = build_merchant_badge_approved(
                store_name=merchant.store_name,
                username=merchant.user.get_full_name() or merchant.user.username,
                store_slug=merchant.store_slug
            )
            dispatch_notification(
                recipient=merchant.user,
                event_type='merchant_badge_approved',
                title="Verified Merchant Seal Approved! 🟢",
                body=f"Congratulations! Your Verified Merchant Seal for '{merchant.store_name}' is now active and live to the public.",
                object_reference=f"merchant:{merchant.pk}",
                subject=subject,
                html_body=html_body,
                text_body=text_body
            )

            log_admin_action(
                request=request,
                action='MERCHANT_BADGE_APPROVE',
                target_user=merchant.user,
                details={'merchant_id': merchant.pk, 'store_name': merchant.store_name, 'slug': merchant.store_slug}
            )
            messages.success(request, f"Merchant '{merchant.store_name}' has been approved and public seal is active.")

        elif action == 'reject':
            merchant.status = 'rejected'
            merchant.rejection_reason = reason or "Verification details could not be validated."
            merchant.save()

            subject, html_body, text_body = build_merchant_badge_rejected(
                store_name=merchant.store_name,
                username=merchant.user.get_full_name() or merchant.user.username,
                reason=merchant.rejection_reason
            )
            dispatch_notification(
                recipient=merchant.user,
                event_type='merchant_badge_rejected',
                title="Merchant Verification Update",
                body=f"Your application for '{merchant.store_name}' was not approved: {merchant.rejection_reason}",
                object_reference=f"merchant:{merchant.pk}",
                subject=subject,
                html_body=html_body,
                text_body=text_body
            )

            log_admin_action(
                request=request,
                action='MERCHANT_BADGE_REJECT',
                target_user=merchant.user,
                details={'merchant_id': merchant.pk, 'store_name': merchant.store_name, 'reason': merchant.rejection_reason}
            )
            messages.warning(request, f"Merchant '{merchant.store_name}' application marked as rejected.")

        elif action == 'dispute':
            merchant.status = 'under_dispute'
            merchant.save()
            messages.info(request, f"Merchant '{merchant.store_name}' status updated to 🟡 Under Dispute.")

        elif action == 'pending':
            merchant.status = 'pending'
            merchant.save()
            messages.info(request, f"Merchant '{merchant.store_name}' status returned to ⏳ In Compliance Review.")

        elif action == 'suspend':
            merchant.status = 'suspended'
            merchant.rejection_reason = reason or "Verification seal suspended by compliance administrator."
            merchant.save()

            # Dispatch notification & email to merchant
            try:
                from notifications.email_templates import build_merchant_badge_revoked
                subject, html_body, text_body = build_merchant_badge_revoked(
                    store_name=merchant.store_name,
                    username=merchant.user.get_full_name() or merchant.user.username,
                    reason=merchant.rejection_reason
                )
                dispatch_notification(
                    recipient=merchant.user,
                    event_type='merchant_badge_suspended',
                    title="Verified Merchant Seal Suspended 🔴",
                    body=f"Your Verified Merchant Seal for '{merchant.store_name}' has been suspended: {merchant.rejection_reason}",
                    object_reference=f"merchant:{merchant.pk}",
                    subject=subject,
                    html_body=html_body,
                    text_body=text_body
                )
            except Exception as e:
                logger.warning(f"Failed to dispatch merchant suspension email: {e}")

            log_admin_action(
                request=request,
                action='MERCHANT_BADGE_SUSPEND',
                target_user=merchant.user,
                details={'merchant_id': merchant.pk, 'store_name': merchant.store_name, 'reason': merchant.rejection_reason}
            )
            messages.error(request, f"Merchant '{merchant.store_name}' status updated to 🔴 Suspended. Notification email dispatched.")

        elif action == 'reactivate':
            merchant.status = 'active'
            merchant.save()
            messages.success(request, f"Merchant '{merchant.store_name}' reactivated to 🟢 Active.")

        elif action == 'approve_bank_change':
            if not merchant.has_pending_bank_change:
                messages.warning(request, "There is no pending bank change request for this merchant.")
            else:
                old_bank = f"{merchant.bank_name} ({merchant.bank_account})"
                merchant.bank_name = merchant.pending_bank_name
                merchant.bank_code = merchant.pending_bank_code
                merchant.bank_account = merchant.pending_bank_account
                merchant.bank_account_name = merchant.pending_bank_account_name

                # Clear pending change
                merchant.has_pending_bank_change = False
                merchant.pending_bank_name = ''
                merchant.pending_bank_code = ''
                merchant.pending_bank_account = ''
                merchant.pending_bank_account_name = ''
                merchant.pending_bank_rejection_reason = ''
                merchant.save()

                # Dispatch notification & email to merchant
                try:
                    from notifications.email_templates import build_merchant_bank_approved
                    subject, html_body, text_body = build_merchant_bank_approved(
                        store_name=merchant.store_name,
                        username=merchant.user.get_full_name() or merchant.user.username,
                        new_bank=merchant.bank_name,
                        new_account=merchant.masked_bank_account,
                        account_name=merchant.bank_account_name
                    )
                    dispatch_notification(
                        recipient=merchant.user,
                        event_type='merchant_bank_approved',
                        title="Settlement Bank Update Approved 🟢",
                        body=f"Your payout bank account for '{merchant.store_name}' has been updated to {merchant.bank_name} ({merchant.masked_bank_account}).",
                        object_reference=f"merchant:{merchant.pk}",
                        subject=subject,
                        html_body=html_body,
                        text_body=text_body
                    )
                except Exception as e:
                    logger.warning(f"Failed to dispatch bank change approval email: {e}")

                log_admin_action(
                    request=request,
                    action='MERCHANT_BANK_CHANGE_APPROVE',
                    target_user=merchant.user,
                    details={'merchant_id': merchant.pk, 'store_name': merchant.store_name, 'old_bank': old_bank, 'new_bank': f"{merchant.bank_name} ({merchant.bank_account})"}
                )
                messages.success(request, f"Settlement bank for '{merchant.store_name}' successfully updated and verified on live public seal.")

        elif action == 'reject_bank_change':
            if not merchant.has_pending_bank_change:
                messages.warning(request, "There is no pending bank change request for this merchant.")
            else:
                rejection_reason = reason or "Bank account name does not match verified legal identity."
                requested_bank = f"{merchant.pending_bank_name} ({merchant.pending_bank_account})"

                merchant.has_pending_bank_change = False
                merchant.pending_bank_rejection_reason = rejection_reason
                merchant.save()

                try:
                    from notifications.email_templates import build_merchant_bank_rejected
                    subject, html_body, text_body = build_merchant_bank_rejected(
                        store_name=merchant.store_name,
                        username=merchant.user.get_full_name() or merchant.user.username,
                        requested_bank=requested_bank,
                        reason=rejection_reason
                    )
                    dispatch_notification(
                        recipient=merchant.user,
                        event_type='merchant_bank_rejected',
                        title="Settlement Bank Update Declined",
                        body=f"Your request to update payout bank for '{merchant.store_name}' was not approved: {rejection_reason}",
                        object_reference=f"merchant:{merchant.pk}",
                        subject=subject,
                        html_body=html_body,
                        text_body=text_body
                    )
                except Exception as e:
                    logger.warning(f"Failed to dispatch bank change rejection email: {e}")

                log_admin_action(
                    request=request,
                    action='MERCHANT_BANK_CHANGE_REJECT',
                    target_user=merchant.user,
                    details={'merchant_id': merchant.pk, 'store_name': merchant.store_name, 'reason': rejection_reason}
                )
                messages.warning(request, f"Settlement bank update for '{merchant.store_name}' was declined. Current verified bank remains active.")

        return redirect('admin_portal:merchant_detail', pk=merchant.pk)
