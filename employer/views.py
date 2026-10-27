import csv
import hashlib
import io
import json
import logging
import mimetypes
import re
from datetime import timedelta
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.mail import EmailMultiAlternatives, send_mail
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_POST

from core.audit_utils import log_admin_action
from core.email_utils import render_email
from core.permissions import employer_required, verified_profile_required
from core.rate_limiting import get_client_ip
from identities.models import Identifier, SubjectEntity
from identities.utils import hash_identifier_value
from payments.models import Subscription
from payments.services import check_user_entitlement, consume_user_entitlement, initialize_service_checkout
from payments.models import SiteSettings
from reports.models import AuditLog, FraudReport, ReportEvidence
from reports.services import generate_report_reference_number
from reports.storage_services import get_storage_service, StorageError
from verification.models import CertificateQueryLog, VerificationCertificate, VerificationRequest
from .models import (
    BulkCheckRow,
    BulkCheckUpload,
    EmployerProfile,
    StaffCheckMonitor,
    StaffCheckRequest,
    TeamInvite,
    TeamMember,
)
from .tasks import process_bulk_upload_task, process_single_staff_check_task

logger = logging.getLogger(__name__)


def _get_or_create_employer_profile(user) -> EmployerProfile:
    """
    Return existing employer profile for an account owner,
    or the organization's EmployerProfile if user is an active TeamMember.
    Creates a minimal profile on first visit if user is an employer.
    """
    # 1. Primary owner profile
    profile = EmployerProfile.objects.filter(user=user, is_active=True).first()
    if profile:
        return profile

    # 2. Check if user is an active member of an employer's team
    membership = (
        TeamMember.objects
        .filter(user=user, is_active=True)
        .select_related('employer')
        .first()
    )
    if membership:
        return membership.employer

    # 3. Fallback: initialize a new profile for the employer user
    profile, _ = EmployerProfile.objects.get_or_create(
        user=user,
        defaults={'company_name': user.get_full_name() or user.username},
    )
    return profile


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@login_required
@employer_required
def employer_dashboard(request):
    profile = _get_or_create_employer_profile(request.user)

    recent_uploads = (
        BulkCheckUpload.objects.filter(employer=profile)
        .order_by('-created_at')[:5]
    )
    team_members_count = TeamMember.objects.filter(employer=profile, is_active=True).count()
    pending_invites_count = TeamInvite.objects.filter(employer=profile, status='pending').count()
    team_count = team_members_count + pending_invites_count
    total_uploads = BulkCheckUpload.objects.filter(employer=profile).count()

    # Staff check stats
    staff_checks_total     = StaffCheckRequest.objects.filter(employer=profile, is_active=True).count()
    staff_checks_pending   = StaffCheckRequest.objects.filter(employer=profile, is_active=True, status='pending').count()
    staff_checks_completed = StaffCheckRequest.objects.filter(employer=profile, is_active=True, status='completed').count()
    verifications_total    = VerificationRequest.objects.filter(requester=request.user).count()

    recent_checks = (
        StaffCheckRequest.objects
        .filter(employer=profile, is_active=True)
        .order_by('-created_at')[:5]
    )
    recent_misconduct_reports = (
        FraudReport.objects
        .filter(reporter=request.user)
        .select_related('target_subject')
        .order_by('-created_at')[:5]
    )

    # Subscription / Plan widget — Batch 9
   
    active_subscription = (
        Subscription.objects
        .filter(user=request.user, status='active', is_active=True)
        .select_related('plan')
        .order_by('-created_at')
        .first()
    )
    allowed, entitlement_reason, entitlement_info = check_user_entitlement(request.user)

    if request.GET.get('dismiss_prepaid'):
        request.session['dismissed_employer_prepaid_banner'] = True

    from payments.models import Transaction
    unconsumed_employer_orders = []
    is_dismissed = request.session.get('dismissed_employer_prepaid_banner', False)
    if not is_dismissed:
        for tx in Transaction.objects.filter(user=request.user, status='success', is_active=True).order_by('-created_at'):
            meta = (tx.paystack_response or {}).get('data', {}).get('metadata', {})
            serv = meta.get('service') or ''
            tier = meta.get('tier') or ''
            if serv == 'staff_check':
                unconsumed_employer_orders.append({
                    'title': 'Staff Background Check',
                    'reference': tx.reference,
                    'amount_naira': tx.amount_naira,
                    'action_url': f"/employer/checks/new/?paid_ref={tx.reference}&tier={tier}",
                    'created_at': tx.created_at,
                })
            elif serv == 'certificate_verify':
                unconsumed_employer_orders.append({
                    'title': 'Certificate Status Check',
                    'reference': tx.reference,
                    'amount_naira': tx.amount_naira,
                    'action_url': f"/employer/certificate/verify/?paid_ref={tx.reference}",
                    'created_at': tx.created_at,
                })
            elif serv in ('certificate', 'certificate_apply'):
                unconsumed_employer_orders.append({
                    'title': 'TrustPass Background Clearance',
                    'reference': tx.reference,
                    'amount_naira': tx.amount_naira,
                    'action_url': f"/verification/certificate/apply/?paid_ref={tx.reference}&level={tier}",
                    'created_at': tx.created_at,
                })
            elif serv in ('verification', 'business_verification'):
                unconsumed_employer_orders.append({
                    'title': 'Due Diligence Verification',
                    'reference': tx.reference,
                    'amount_naira': tx.amount_naira,
                    'action_url': f"/verification/new/?paid_ref={tx.reference}&type={tier}",
                    'created_at': tx.created_at,
                })

    context = {
        'profile':                profile,
        'recent_uploads':         recent_uploads,
        'recent_misconduct_reports': recent_misconduct_reports,
        'team_count':             team_count,
        'total_uploads':          total_uploads,
        'staff_checks_total':     staff_checks_total,
        'staff_checks_pending':   staff_checks_pending,
        'staff_checks_completed': staff_checks_completed,
        'verifications_total':    verifications_total,
        'recent_checks':          recent_checks,
        'active_subscription':    active_subscription,
        'entitlement_reason':     entitlement_reason,
        'entitlement_info':       entitlement_info,
        'unconsumed_employer_orders': unconsumed_employer_orders,
        'page_title':             'Employer Dashboard',
    }
    return render(request, 'employer/dashboard.html', context)

# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

@login_required
@employer_required
def employer_profile(request):
    profile = _get_or_create_employer_profile(request.user)

    if request.method == 'POST':
        # If company identity is verified, lock legal company name and CAC RC number
        if not profile.is_verified:
            profile.company_name = request.POST.get('company_name', profile.company_name).strip()
            profile.company_rc_number = request.POST.get('company_rc_number', '').strip()

        profile.industry = request.POST.get('industry', '').strip()
        profile.company_address = request.POST.get('company_address', '').strip()
        profile.contact_phone = request.POST.get('contact_phone', '').strip()

        cac_file = request.FILES.get('cac_document')
        file_uploaded = False

        if cac_file:
            if cac_file.size > 5 * 1024 * 1024:
                messages.error(request, 'The uploaded CAC document exceeds the 5MB size limit. Please upload a smaller file.')
                return redirect('employer:profile')
            ext = cac_file.name.split('.')[-1].lower() if '.' in cac_file.name else ''
            if ext not in ('pdf', 'jpg', 'jpeg', 'png'):
                messages.error(request, 'Invalid file format. Please upload a PDF, JPG, or PNG document.')
                return redirect('employer:profile')
            profile.cac_document = cac_file
            profile.cac_uploaded_at = timezone.now()
            file_uploaded = True
            if not profile.is_verified:
                profile.verification_status = 'pending'
                profile.rejection_reason = ''

        if request.POST.get('resubmit_review') == '1' and not profile.is_verified and profile.has_cac_document:
            profile.verification_status = 'pending'
            profile.rejection_reason = ''

        profile.save()

        if file_uploaded:
            if not profile.is_verified:
                messages.success(request, 'Company profile updated and CAC incorporation document submitted for compliance verification.')
            else:
                messages.success(request, 'Company profile and updated CAC document saved successfully.')
        elif request.POST.get('resubmit_review') == '1':
            messages.success(request, 'Your company profile has been resubmitted for verification review.')
        else:
            messages.success(request, 'Company profile updated successfully.')

        return redirect('employer:profile')


    context = {
        'profile': profile,
        'page_title': 'Company Profile',
    }
    return render(request, 'employer/profile.html', context)



@login_required
@employer_required
@xframe_options_sameorigin
def employer_cac_document_view(request):
    """In-browser document stream for the employer to preview their own CAC proof."""
    profile = _get_or_create_employer_profile(request.user)
    if not profile.cac_document:
        raise Http404("No CAC document on file.")

    try:
        doc_file = profile.cac_document.open('rb')
    except Exception:
        raise Http404("Document could not be accessed.")

    ext = profile.cac_document.name.split('.')[-1].lower() if '.' in profile.cac_document.name else 'pdf'
    content_type, _ = mimetypes.guess_type(profile.cac_document.name)
    if not content_type:
        content_type = 'application/pdf' if ext == 'pdf' else 'image/jpeg'

    response = HttpResponse(doc_file.read(), content_type=content_type)
    response['Content-Disposition'] = f'inline; filename="CAC_document.{ext}"'
    response['X-Frame-Options'] = 'SAMEORIGIN'
    doc_file.close()
    return response

# ---------------------------------------------------------------------------
# Bulk Checks — Upload list
# ---------------------------------------------------------------------------

@login_required
@employer_required
def bulk_upload_list(request):
    profile = _get_or_create_employer_profile(request.user)

    uploads_qs = (
        BulkCheckUpload.objects.filter(employer=profile)
        .order_by('-created_at')
    )
    paginator = Paginator(uploads_qs, 20)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    context = {
        'profile': profile,
        'page_obj': page_obj,
        'page_title': 'Bulk Check Uploads',
    }
    return render(request, 'employer/bulk_upload_list.html', context)


# ---------------------------------------------------------------------------
# Bulk Checks — Upload detail / row list
# ---------------------------------------------------------------------------

@login_required
@employer_required
def bulk_upload_detail(request, upload_id):
    profile = _get_or_create_employer_profile(request.user)
    upload = get_object_or_404(BulkCheckUpload, id=upload_id, employer=profile)

    rows_qs = upload.rows.order_by('row_number')
    paginator = Paginator(rows_qs, 50)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    context = {
        'profile': profile,
        'upload': upload,
        'page_obj': page_obj,
        'page_title': f'Upload — {upload.original_filename}',
    }
    return render(request, 'employer/bulk_upload_detail.html', context)


# ---------------------------------------------------------------------------
# Team Management
# ---------------------------------------------------------------------------

@login_required
@employer_required
def team_list(request):
    profile = _get_or_create_employer_profile(request.user)
    members_qs = (
        TeamMember.objects.filter(employer=profile, is_active=True)
        .select_related('user', 'invited_by')
        .order_by('-created_at')
    )
    invites_qs = (
        TeamInvite.objects.filter(employer=profile)
        .select_related('invited_by')
        .order_by('-created_at')
    )
    # If employer has no accepted members yet but has invites, default tab to invites
    default_tab = 'invites' if (not members_qs.exists() and invites_qs.exists()) else 'members'
    active_tab = request.GET.get('tab', default_tab)
    if active_tab not in ('members', 'invites'):
        active_tab = default_tab
    members_paginator = Paginator(members_qs, 15)
    members_page = members_paginator.get_page(request.GET.get('mpage', 1))
    invites_paginator = Paginator(invites_qs, 15)
    invites_page = invites_paginator.get_page(request.GET.get('ipage', 1))
    context = {
        'profile': profile,
        'members': members_page,
        'invites': invites_page,
        'members_count': members_qs.count(),
        'invites_count': invites_qs.count(),
        'pending_invites_count': invites_qs.filter(status='pending').count(),
        'active_tab': active_tab,
        'page_title': 'Team Members & Invitations',
    }
    return render(request, 'employer/team_list.html', context)


@login_required
@employer_required
@require_POST
def team_invite_revoke(request, invite_id):
    """Cancel / revoke a pending team invitation."""
    profile = _get_or_create_employer_profile(request.user)
    invite = get_object_or_404(TeamInvite, id=invite_id, employer=profile)
    if invite.status == 'pending':
        invite.status = 'revoked'
        invite.save(update_fields=['status'])
        messages.success(request, f"Invitation to {invite.email} has been cancelled.")
    return redirect(reverse('employer:team_list') + '?tab=invites')


# ---------------------------------------------------------------------------
# Staff Checks — BATCH 1
# ---------------------------------------------------------------------------

def _hash_nin(raw_nin: str) -> str:
    """Peppered HMAC-SHA256 hash of a raw NIN string matching VerifyNG storage standard."""
    if not raw_nin or not raw_nin.strip():
        return ''
    try:
        return hash_identifier_value('nin', raw_nin.strip())
    except Exception:
        return ''

@login_required
@employer_required
def staff_check_list(request):
    profile = _get_or_create_employer_profile(request.user)

    status_filter = request.GET.get('status', '')
    qs = profile.staff_checks.filter(is_active=True).order_by('-created_at')
    if status_filter in ('pending', 'processing', 'completed', 'failed', 'cancelled'):
        qs = qs.filter(status=status_filter)

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    context = {
        'profile':          profile,
        'page_obj':         page_obj,
        'status_filter':    status_filter,
        'check_status_tabs': [
            ('pending',    'Pending'),
            ('processing', 'Processing'),
            ('completed',  'Completed'),
            ('failed',     'Failed'),
            ('cancelled',  'Cancelled'),
        ],
        'page_title':       'Staff Background Checks',
    }
    return render(request, 'employer/staff_check_list.html', context)


@login_required
@employer_required
@verified_profile_required
def staff_check_create(request):
    profile = _get_or_create_employer_profile(request.user)

    allowed, reason, details = check_user_entitlement(request.user, service='staff_check', cost=1)
    if not allowed and reason == 'service_restricted':
        messages.error(request, details.get('message', "Your organization has been restricted from performing staff background checks by platform administration."))
        return redirect('employer:dashboard')

    site_settings = SiteSettings.get()

    if request.method == 'POST':
        full_name    = request.POST.get('full_name', '').strip()
        phone_number = request.POST.get('phone_number', '').strip()
        raw_nin      = request.POST.get('nin', '').strip()
        email        = request.POST.get('email', '').strip()
        check_type   = request.POST.get('check_type', 'standard')
        purpose      = request.POST.get('purpose', '').strip()

        errors = []
        if not full_name:
            errors.append('Full name is required.')
        if not phone_number and not raw_nin:
            errors.append('At least one of phone number or NIN is required.')
        if check_type not in ('standard', 'enhanced'):
            check_type = 'standard'

        if errors:
            context = {
                'profile':        profile,
                'errors':         errors,
                'form_data':      request.POST,
                'has_entitlement': allowed,
                'price_standard': site_settings.price_staff_check_standard,
                'price_enhanced': site_settings.price_staff_check_enhanced,
                'page_title':     'New Staff Check',
            }
            return render(request, 'employer/staff_check_create.html', context)
        
        # Enforce check entitlement before proceeding
        allowed, reason, details = check_user_entitlement(request.user, service='staff_check', cost=1)
        if not allowed and reason == 'service_restricted':
            messages.error(request, details.get('message', "Your organization has been restricted from performing staff background checks by platform administration."))
            return redirect('employer:dashboard')

        # Check for pre-paid Paystack reference or unconsumed credit
        paid_ref = request.GET.get('paid_ref') or request.POST.get('paid_ref')
        has_valid_prepayment = False
        paid_tx = None
        from payments.services import get_user_prepaid_balance, deduct_user_prepaid_balance, get_topup_difference
        user_balance = get_user_prepaid_balance(request.user)
        req_price = site_settings.price_staff_check_enhanced if check_type == 'enhanced' else site_settings.price_staff_check_standard

        if paid_ref:
            from payments.models import Transaction
            paid_tx = Transaction.objects.filter(
                reference=paid_ref,
                user=request.user,
                status='success',
                is_active=True,
            ).first()
            if paid_tx and paid_tx.amount_kobo >= (req_price * 100):
                has_valid_prepayment = True

        if allowed:
            # Subscription entitlement
            check = StaffCheckRequest.objects.create(
                employer     = profile,
                requested_by = request.user,
                full_name    = full_name,
                phone_number = phone_number,
                nin_hash     = _hash_nin(raw_nin) if raw_nin else '',
                email        = email,
                check_type   = check_type,
                purpose      = purpose,
                status       = 'pending',
            )
            consume_user_entitlement(request.user, service='staff_check', cost=1)
            try:
                process_single_staff_check_task.delay(str(check.id))
            except Exception as exc:
                try:
                    process_single_staff_check_task(str(check.id))
                except Exception:
                    pass
            messages.success(request, f'Check request submitted for {full_name} using plan quota.')
            return redirect('employer:staff_check_detail', check_id=check.id)

        elif has_valid_prepayment and paid_tx:
            # Direct pre-paid transaction reference
            paid_tx.is_active = False
            paid_tx.save(update_fields=['is_active'])
            check = StaffCheckRequest.objects.create(
                employer     = profile,
                requested_by = request.user,
                full_name    = full_name,
                phone_number = phone_number,
                nin_hash     = _hash_nin(raw_nin) if raw_nin else '',
                email        = email,
                check_type   = check_type,
                purpose      = purpose,
                status       = 'pending',
            )
            try:
                process_single_staff_check_task.delay(str(check.id))
            except Exception as exc:
                try:
                    process_single_staff_check_task(str(check.id))
                except Exception:
                    pass
            messages.success(request, f'Check request submitted for {full_name} using pre-paid order {paid_ref}.')
            return redirect('employer:staff_check_detail', check_id=check.id)

        elif user_balance >= req_price:
            # Dynamic account balance deduction!
            ok, rem_bal = deduct_user_prepaid_balance(request.user, req_price, f"Staff Check: {check_type}")
            check = StaffCheckRequest.objects.create(
                employer     = profile,
                requested_by = request.user,
                full_name    = full_name,
                phone_number = phone_number,
                nin_hash     = _hash_nin(raw_nin) if raw_nin else '',
                email        = email,
                check_type   = check_type,
                purpose      = purpose,
                status       = 'pending',
            )
            try:
                process_single_staff_check_task.delay(str(check.id))
            except Exception as exc:
                try:
                    process_single_staff_check_task(str(check.id))
                except Exception:
                    pass
            messages.success(request, f'Check request submitted for {full_name}! ₦{req_price:,.0f} paid from your balance (₦{rem_bal:,.0f} remaining).')
            return redirect('employer:staff_check_detail', check_id=check.id)

        else:
            action = request.POST.get('action', 'submit')
            topup_needed = get_topup_difference(user_balance, req_price)

            if action != 'payg':
                context = {
                    'profile':        profile,
                    'form_data':      request.POST,
                    'has_entitlement': False,
                    'quota_exceeded':  True,
                    'user_balance':    user_balance,
                    'topup_needed':    topup_needed,
                    'check_type':      check_type,
                    'selected_price':  req_price,
                    'price_standard': site_settings.price_staff_check_standard,
                    'price_enhanced': site_settings.price_staff_check_enhanced,
                    'page_title':     'New Staff Check',
                }
                return render(request, 'employer/staff_check_create.html', context)

            # User clicked "Pay via Paystack" -> initialize checkout for difference
            check = StaffCheckRequest.objects.create(
                employer     = profile,
                requested_by = request.user,
                full_name    = full_name,
                phone_number = phone_number,
                nin_hash     = _hash_nin(raw_nin) if raw_nin else '',
                email        = email,
                check_type   = check_type,
                purpose      = purpose,
                status       = 'pending_payment',
            )
            if user_balance > 0:
                deduct_user_prepaid_balance(request.user, user_balance, f"Partial top-up for check {check.id}")

            try:
                checkout_data = initialize_service_checkout(
                    user=request.user,
                    service='staff_check',
                    tier=check_type,
                    amount_naira=topup_needed,
                    metadata={
                        'staff_check_id': str(check.id),
                        'check_type': check_type,
                        'full_name': full_name,
                    }
                )
                request.session['vng_pending_ref'] = checkout_data['reference']
                return redirect(checkout_data['authorization_url'])
            except Exception as exc:
                logger.exception("Failed to initialize staff check checkout: %s", exc)
                context = {
                    'profile':        profile,
                    'errors':         [f"{exc}"],
                    'form_data':      request.POST,
                    'has_entitlement': False,
                    'quota_exceeded':  True,
                    'check_type':      check_type,
                    'selected_price':  req_price,
                    'price_standard': site_settings.price_staff_check_standard,
                    'price_enhanced': site_settings.price_staff_check_enhanced,
                    'page_title':     'New Staff Check',
                }
                return render(request, 'employer/staff_check_create.html', context)

    init_check_type = request.GET.get('check_type') or request.GET.get('tier') or 'standard'
    if init_check_type not in ('standard', 'enhanced'):
        init_check_type = 'standard'

    paid_ref = request.GET.get('paid_ref')
    prepaid_active = False
    from payments.models import Transaction
    if paid_ref:
        tx = Transaction.objects.filter(
            reference=paid_ref,
            user=request.user,
            status='success',
            is_active=True,
        ).first()
        if tx:
            prepaid_active = True
    elif request.user.is_authenticated:
        # Auto-detect unconsumed pre-paid staff check
        for unconsumed in Transaction.objects.filter(user=request.user, status='success', is_active=True).order_by('-created_at'):
            meta = (unconsumed.paystack_response or {}).get('data', {}).get('metadata', {})
            if meta.get('service') == 'staff_check':
                paid_ref = unconsumed.reference
                prepaid_active = True
                break

    from payments.services import get_user_prepaid_balance, get_topup_difference
    user_balance = get_user_prepaid_balance(request.user)
    has_entitlement = allowed or prepaid_active or (user_balance >= site_settings.price_staff_check_standard)
    selected_price = site_settings.price_staff_check_enhanced if init_check_type == 'enhanced' else site_settings.price_staff_check_standard
    topup_needed = get_topup_difference(user_balance, selected_price)

    context = {
        'profile':        profile,
        'form_data':      {'check_type': init_check_type},
        'has_entitlement': has_entitlement,
        'user_balance':   user_balance,
        'topup_needed':   topup_needed,
        'selected_price': selected_price,
        'prepaid_reference': paid_ref if prepaid_active else None,
        'entitlement_details': details,
        'price_standard': site_settings.price_staff_check_standard,
        'price_enhanced': site_settings.price_staff_check_enhanced,
        'page_title':     'New Staff Check',
    }
    return render(request, 'employer/staff_check_create.html', context)


@login_required
@employer_required
def staff_check_detail(request, check_id):
    profile = _get_or_create_employer_profile(request.user)
    check = get_object_or_404(StaffCheckRequest, id=check_id, employer=profile)

    # Check if monitoring is active
    monitor = getattr(check, 'monitor', None)

    context = {
        'profile':    profile,
        'check':      check,
        'monitor':    monitor,
        'page_title': f'Check — {check.full_name}',
    }
    return render(request, 'employer/staff_check_detail.html', context)


@login_required
@employer_required
@require_POST
def staff_check_cancel(request, check_id):
    """Fetch + Toast: cancels a pending/processing check request."""
    profile = _get_or_create_employer_profile(request.user)
    check = get_object_or_404(StaffCheckRequest, id=check_id, employer=profile)

    if check.status not in ('pending', 'processing'):
        return JsonResponse({'ok': False, 'message': 'This check cannot be cancelled.'}, status=400)

    check.status = 'cancelled'
    check.save(update_fields=['status', 'updated_at'])

    return JsonResponse({'ok': True, 'message': f'Check for {check.full_name} has been cancelled.'})


# ---------------------------------------------------------------------------
# Staff Monitoring — BATCH 1
# ---------------------------------------------------------------------------

@login_required
@employer_required
def monitoring_list(request):
    profile = _get_or_create_employer_profile(request.user)

    monitors = (
        StaffCheckMonitor.objects
        .filter(employer=profile, is_active=True)
        .select_related('check_request')
        .order_by('-created_at')
    )

    context = {
        'profile':    profile,
        'monitors':   monitors,
        'page_title': 'Staff Monitoring',
    }
    return render(request, 'employer/monitoring_list.html', context)


@login_required
@employer_required
@verified_profile_required
@require_POST
def monitoring_toggle(request, check_id):
    """
    Fetch + Toast: enables or disables monitoring for a completed staff check.
    - If no monitor exists → create one (active).
    - If monitor is active → pause it.
    - If monitor is paused → reactivate it.
    """
    profile = _get_or_create_employer_profile(request.user)

    check = get_object_or_404(StaffCheckRequest, id=check_id, employer=profile)

    if check.status != 'completed':
        return JsonResponse({'ok': False, 'message': 'Monitoring can only be set on completed checks.'}, status=400)

    monitor, created = StaffCheckMonitor.objects.get_or_create(
        check_request=check,
        defaults={'employer': profile, 'monitor_status': 'active'},
    )

    if not created:
        if monitor.monitor_status == 'active':
            monitor.monitor_status = 'paused'
            monitor.save(update_fields=['monitor_status', 'updated_at'])
            msg = f'Monitoring paused for {check.full_name}.'
            new_status = 'paused'
        else:
            allowed, reason, details = check_user_entitlement(request.user, service='monitoring')
            if not allowed:
                if reason == 'service_restricted':
                    return JsonResponse({'ok': False, 'message': 'Staff monitoring has been restricted for your organization by platform administration.'}, status=403)
                from payments.services import initialize_service_checkout
                site_settings = SiteSettings.get()
                amount = site_settings.price_monitoring_annual
                checkout_res = initialize_service_checkout(
                    user=request.user,
                    service='monitoring',
                    tier='annual',
                    amount_naira=amount,
                    metadata={'service': 'monitoring', 'staff_check_id': str(check.id)}
                )
                return JsonResponse({
                    'ok': False,
                    'payg_required': True,
                    'checkout_url': checkout_res['authorization_url'],
                    'message': f"Pay ₦{amount:,.0f}/yr to activate Certificate Monitoring for {check.full_name}."
                }, status=200)
            monitor.monitor_status = 'active'
            monitor.save(update_fields=['monitor_status', 'updated_at'])
            msg = f'Monitoring resumed for {check.full_name}.'
            new_status = 'active'
    else:
        allowed, reason, details = check_user_entitlement(request.user, service='monitoring')
        if not allowed:
            monitor.delete()
            if reason == 'service_restricted':
                return JsonResponse({'ok': False, 'message': 'Staff monitoring has been restricted for your organization by platform administration.'}, status=403)
            from payments.services import initialize_service_checkout
            site_settings = SiteSettings.get()
            amount = site_settings.price_monitoring_annual
            checkout_res = initialize_service_checkout(
                user=request.user,
                service='monitoring',
                tier='annual',
                amount_naira=amount,
                metadata={'service': 'monitoring', 'staff_check_id': str(check.id)}
            )
            return JsonResponse({
                'ok': False,
                'payg_required': True,
                'checkout_url': checkout_res['authorization_url'],
                'message': f"Pay ₦{amount:,.0f}/yr to activate Certificate Monitoring for {check.full_name}."
            }, status=200)
        msg = f'Monitoring started for {check.full_name}.'
        new_status = 'active'
    return JsonResponse({'ok': True, 'message': msg, 'monitor_status': new_status})


# ---------------------------------------------------------------------------
# Bulk Checks — Upload form — BATCH 2
# ---------------------------------------------------------------------------




@login_required
@employer_required
@verified_profile_required
def bulk_upload_create(request):
    """
    GET  — render the upload form with CSV template download link.
    POST — validate uploaded CSV, create BulkCheckUpload + BulkCheckRow records,
           trigger Celery task, redirect to detail page.
    """
    profile = _get_or_create_employer_profile(request.user)

    from payments.services import get_user_prepaid_balance, deduct_user_prepaid_balance
    site_settings = SiteSettings.get()
    price_per_row = site_settings.price_bulk_check_per_row
    user_balance = get_user_prepaid_balance(request.user)

    allowed, reason, details = check_user_entitlement(request.user, service='bulk_upload', cost=1)
    if not allowed and reason == 'service_restricted':
        messages.error(request, details.get('message', "Your organization has been restricted from bulk CSV candidate screening by platform administration."))
        return redirect('employer:dashboard')

    has_entitlement = allowed or (user_balance >= price_per_row)
    remaining_checks = details.get('remaining', 0) if allowed else 0

    if request.method == 'POST':
        uploaded_file = request.FILES.get('csv_file')
        errors = []

        if not uploaded_file:
            errors.append('Please select a CSV file to upload.')
        elif not uploaded_file.name.lower().endswith('.csv'):
            errors.append('Only CSV files are accepted (.csv extension required).')
        elif uploaded_file.size > 5 * 1024 * 1024:  # 5 MB hard limit
            errors.append('File is too large. Maximum size is 5 MB.')

        if errors:
            return render(request, 'employer/bulk_upload_create.html', {
                'profile': profile,
                'has_entitlement': has_entitlement,
                'allowed': allowed,
                'remaining_checks': remaining_checks,
                'user_balance': user_balance,
                'price_per_row': price_per_row,
                'errors': errors,
                'page_title': 'Bulk CSV Upload',
            })

        # Read and validate CSV content
        try:
            raw_bytes = uploaded_file.read()
            text = raw_bytes.decode('utf-8-sig')  # handles BOM from Excel exports
        except UnicodeDecodeError:
            return render(request, 'employer/bulk_upload_create.html', {
                'profile': profile,
                'errors': ['File could not be decoded as UTF-8. Please save as CSV UTF-8 and re-upload.'],
                'page_title': 'Bulk CSV Upload',
            })

        reader = csv.DictReader(io.StringIO(text))
        required_col = 'full_name'
        rows_data = []
        parse_errors = []

        try:
            fieldnames = [f.strip().lower() for f in (reader.fieldnames or [])]
        except Exception:
            fieldnames = []

        if required_col not in fieldnames:
            return render(request, 'employer/bulk_upload_create.html', {
                'profile': profile,
                'errors': [
                    'CSV must contain a "full_name" column. '
                    'Download the template below and use it as your starting point.'
                ],
                'page_title': 'Bulk CSV Upload',
            })

        for row_num, raw_row in enumerate(reader, start=2):
            # Normalise column names
            row = {k.strip().lower(): (v or '').strip() for k, v in raw_row.items() if k}

            full_name = row.get('full_name', '').strip()
            phone_number = row.get('phone_number', '').strip()
            raw_nin = row.get('nin', '').strip()

            if not full_name:
                parse_errors.append(f'Row {row_num}: full_name is empty — row skipped.')
                continue

            nin_hash = ''
            if raw_nin:
                if len(raw_nin) != 11 or not raw_nin.isdigit():
                    parse_errors.append(f'Row {row_num}: NIN "{raw_nin}" is not 11 digits — NIN ignored for this row.')
                else:
                    try:
                        nin_hash = hash_identifier_value('nin', raw_nin)
                    except Exception:
                        parse_errors.append(f'Row {row_num}: Failed to hash NIN — ignored.')

            rows_data.append({
                'full_name': full_name,
                'phone_number': phone_number,
                'nin_hash': nin_hash,
            })

        if not rows_data:
            errors = ['No valid rows found in the CSV.']
            if parse_errors:
                errors += parse_errors[:5]
            return render(request, 'employer/bulk_upload_create.html', {
                'profile': profile,
                'errors': errors,
                'page_title': 'Bulk CSV Upload',
            })

        if len(rows_data) > 500:
            return render(request, 'employer/bulk_upload_create.html', {
                'profile': profile,
                'errors': ['Maximum 500 rows per upload. Split your file and upload in batches.'],
                'page_title': 'Bulk CSV Upload',
            })
        # Enforce check entitlement for bulk check volume
        cost = len(rows_data)
        allowed, reason, details = check_user_entitlement(request.user, service='bulk_upload', cost=cost)
        total_batch_price = cost * price_per_row
        balance_paid = False

        if not allowed and user_balance >= total_batch_price:
            ok, rem_bal = deduct_user_prepaid_balance(request.user, total_batch_price, f"Bulk Screening: {cost} candidates")
            if ok:
                allowed = True
                balance_paid = True

        if not allowed:
            remaining = details.get('remaining', 0)
            return render(request, 'employer/bulk_upload_create.html', {
                'profile': profile,
                'has_entitlement': False,
                'allowed': False,
                'remaining_checks': remaining,
                'user_balance': user_balance,
                'price_per_row': price_per_row,
                'errors': [
                    f'Payment or plan credits required. This bulk upload requires {cost} checks (₦{total_batch_price:,.0f}), '
                    f'but your account only has {remaining} checks remaining (account balance: ₦{user_balance:,.0f}). '
                    f'Please purchase screening credits or upgrade your plan to continue.'
                ],
                'page_title': 'Bulk CSV Upload',
            })
        # Save original file to storage (S3 / local fallback)
        safe_filename = uploaded_file.name.replace(' ', '_')
        storage_path = f'bulk_uploads/{profile.id}/{safe_filename}'
        try:
            saved_path = default_storage.save(storage_path, ContentFile(raw_bytes))
        except Exception:
            saved_path = ''  # non-blocking — task can still run without the stored file
        # Create DB records atomically
        with transaction.atomic():
            upload = BulkCheckUpload.objects.create(
                employer=profile,
                uploaded_by=request.user,
                original_filename=uploaded_file.name,
                file_path=saved_path,
                row_count=len(rows_data),
                status='pending',
            )
            if not balance_paid:
                consume_user_entitlement(request.user, service='bulk_upload', cost=cost)
            BulkCheckRow.objects.bulk_create([
                BulkCheckRow(
                    upload=upload,
                    row_number=i + 1,
                    full_name=r['full_name'],
                    phone_number=r['phone_number'],
                    nin_hash=r['nin_hash'],
                )
                for i, r in enumerate(rows_data)
            ])
    

        # Dispatch Celery task
        try:
            process_bulk_upload_task.delay(str(upload.id))
        except Exception as exc:
            logger.warning("Could not dispatch Celery task for upload %s: %s", upload.id, exc)
            # Resilient fallback: process inline if Celery/Redis is offline in local dev
            try:
                process_bulk_upload_task(str(upload.id))
            except Exception as e:
                logger.exception("Inline execution failed for upload %s: %s", upload.id, e)
        warn_count = len(parse_errors)
        
        if warn_count:
            messages.warning(
                request,
                f'{warn_count} row(s) had minor issues and were skipped or adjusted. '
                'Check the upload detail for per-row results.'
            )
        messages.success(
            request,
            f'Bulk upload queued — {len(rows_data)} candidates. Processing will begin shortly.'
        )
        return redirect('employer:bulk_upload_detail', upload_id=upload.id)

    context = {
        'profile': profile,
        'has_entitlement': has_entitlement,
        'allowed': allowed,
        'remaining_checks': remaining_checks,
        'entitlement_details': details,
        'user_balance': user_balance,
        'price_per_row': price_per_row,
        'page_title': 'Bulk CSV Upload',
    }
    return render(request, 'employer/bulk_upload_create.html', context)


def bulk_csv_template(request):
    """
    Serve a minimal CSV template file for employers to download.
    No login required — it's just column headers.
    """
    content = "full_name,phone_number,nin\nJohn Doe,08012345678,12345678901\n"
    response = HttpResponse(content, content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="verifyng_bulk_check_template.csv"'
    return response



# ---------------------------------------------------------------------------
# Team Management — BATCH 3 (invite + remove)
# ---------------------------------------------------------------------------

@login_required
@employer_required
@verified_profile_required
@require_POST
def team_invite_send(request):
    """
    Fetch + Toast: send a team invitation email to a new member.
    Creates a TeamInvite record with a 7-day expiry token.
    """
    profile = _get_or_create_employer_profile(request.user)
    
    email = request.POST.get('email', '').strip().lower()
    team_role = request.POST.get('team_role', 'checker')

    if not email:
        return JsonResponse({'ok': False, 'message': 'Email address is required.'}, status=400)
    if team_role not in ('admin', 'checker', 'viewer'):
        team_role = 'checker'

    # Reject if already a live team member
    already_member = TeamMember.objects.filter(
        employer=profile, user__email=email, is_active=True
    ).exists()
    if already_member:
        return JsonResponse({'ok': False, 'message': f'{email} is already a team member.'}, status=400)

    # Revoke any existing pending invite for same email+employer before creating a new one
    TeamInvite.objects.filter(employer=profile, email=email, status='pending').update(
        status='revoked', updated_at=timezone.now()
    )

    token = TeamInvite.generate_token()
    invite = TeamInvite.objects.create(
        employer=profile,
        invited_by=request.user,
        email=email,
        team_role=team_role,
        token=token,
        expires_at=timezone.now() + timedelta(days=7),
    )

    # Build accept URL
    accept_url = request.build_absolute_uri(
        f'/employer/invite/accept/{token}/'
    )

    # Send invitation email
        # Send invitation email (HTML + plain text fallback)
    try:

        email_subject = f"You've been invited to join {profile.company_name} on VerifyNG"

        invited_by_name = request.user.get_full_name() or request.user.username

        ctx = {
            'company_name': profile.company_name,
            'invited_by':   invited_by_name,
            'role_display': invite.get_team_role_display(),
            'accept_url':   accept_url,
            'invite_email': email,
            'expires_at':   invite.expires_at.strftime('%d %B %Y'),
            # base_email.html context
            'site_name':    'VerifyNG',
            'site_url':     request.build_absolute_uri('/'),
            'support_email': 'support@verifyng.ng',
            'company_reg':  '',
            'logo_url':     '',
        }

        html_body  = render_to_string('emails/team_invite.html', ctx)
        plain_body = (
            f"Hi,\n\n"
            f"{invited_by_name} has invited you to join {profile.company_name} on VerifyNG "
            f"as a {invite.get_team_role_display()}.\n\n"
            f"Accept the invitation here:\n{accept_url}\n\n"
            f"This invitation expires on {ctx['expires_at']}.\n\n"
            f"If you did not expect this, you can safely ignore this email.\n\n"
            f"— The VerifyNG Team"
        )

        msg = EmailMultiAlternatives(
            subject=email_subject,
            body=plain_body,
            from_email=None,          # uses DEFAULT_FROM_EMAIL from settings
            to=[email],
        )
        msg.attach_alternative(html_body, 'text/html')
        msg.send(fail_silently=False)

    except Exception as exc:
        logger.warning("team_invite_send: email send failed for %s: %s", email, exc)
        # Invitation was created in DB — email failure is non-fatal
        return JsonResponse({
            'ok': True,
            'message': (
                f'Invitation created for {email} but the email could not be sent. '
                'Please share the invite link manually or retry.'
            ),
        })

    return JsonResponse({
        'ok': True,
        'message': f'Invitation sent to {email}. They have 7 days to accept.',
    })


def team_invite_accept(request, token):
    """
    Public view — no login required at URL level.
    The invited user clicks the link from their email.
    - If not logged in → redirect to login with ?next= back to this URL.
    - If logged in → validate token, create TeamMember, mark invite accepted.
    """
    try:
        invite = TeamInvite.objects.select_related('employer').get(token=token)
    except TeamInvite.DoesNotExist:
        return render(request, 'employer/invite_accept.html', {
            'error': 'This invitation link is invalid or has already been used.',
            'page_title': 'Team Invitation',
        })

    if not invite.is_usable:
        status_label = invite.get_status_display()
        if invite.is_expired and invite.status == 'pending':
            invite.status = 'expired'
            invite.save(update_fields=['status', 'updated_at'])
            status_label = 'expired'
        return render(request, 'employer/invite_accept.html', {
            'error': f'This invitation is no longer valid ({status_label}).',
            'page_title': 'Team Invitation',
        })

    if not request.user.is_authenticated:
        login_url = f"/users/login/?next=/employer/invite/accept/{token}/"
        return _redirect(login_url)

    # Check email matches logged-in user
    if request.user.email.lower() != invite.email.lower():
        return render(request, 'employer/invite_accept.html', {
            'error': (
                f'This invitation was sent to {invite.email}. '
                f'You are currently logged in as {request.user.email}. '
                'Please log in with the correct account to accept.'
            ),
            'page_title': 'Team Invitation',
        })

    if request.method == 'POST':
        with transaction.atomic():
            # Avoid duplicate
            member, created = TeamMember.objects.get_or_create(
                employer=invite.employer,
                user=request.user,
                defaults={
                    'team_role': invite.team_role,
                    'invited_by': invite.invited_by,
                    'joined_at': timezone.now(),
                    'is_active': True,
                },
            )
            if not created:
                # Already a member — reactivate + update role
                member.is_active = True
                member.team_role = invite.team_role
                member.joined_at = member.joined_at or timezone.now()
                member.save(update_fields=['is_active', 'team_role', 'joined_at', 'updated_at'])

            invite.status = 'accepted'
            invite.accepted_by = request.user
            invite.save(update_fields=['status', 'accepted_by', 'updated_at'])

        messages.success(
            request,
            f"You have joined {invite.employer.company_name} as a {invite.get_team_role_display()}."
        )
        return redirect('employer:team_list')

    # GET — show confirmation screen
    return render(request, 'employer/invite_accept.html', {
        'invite': invite,
        'page_title': 'Accept Team Invitation',
    })


@login_required
@employer_required
@require_POST
def team_member_remove(request, member_id):
    """
    Fetch + Toast: soft-delete a team member (sets is_active=False).
    Cannot remove yourself.
    """
    profile = _get_or_create_employer_profile(request.user)

    member = get_object_or_404(TeamMember, id=member_id, employer=profile, is_active=True)

    if member.user == request.user:
        return JsonResponse({'ok': False, 'message': 'You cannot remove yourself from the team.'}, status=400)

    name = member.user.get_full_name() or member.user.username
    member.is_active = False
    member.save(update_fields=['is_active', 'updated_at'])

    return JsonResponse({'ok': True, 'message': f'{name} has been removed from the team.'})




# ---------------------------------------------------------------------------
# Person / Landlord Quick-Check — BATCH 4
# ---------------------------------------------------------------------------

@login_required
@employer_required
def person_check_search(request):
    """
    Quick-check a person by phone number or NIN.
    Returns trust summary from SubjectEntity + TrustScore + FraudReport.
    Supports subscription quota AND direct Paystack Pay-As-You-Go checkout.
    """
    from payments.models import Transaction
    profile = _get_or_create_employer_profile(request.user)
    site_settings = SiteSettings.get()
    payg_price = site_settings.get_service_price('person_check')

    from payments.services import get_user_prepaid_balance, deduct_user_prepaid_balance, get_topup_difference
    user_balance = get_user_prepaid_balance(request.user)
    topup_needed = get_topup_difference(user_balance, payg_price)

    allowed, reason, details = check_user_entitlement(request.user, service='person_check', cost=1)

    result = None
    query = request.GET.get('query', '').strip()
    query_type = ''

    # Check if returning from a verified direct PAYG payment
    paid_ref = request.GET.get('paid_ref', '').strip()
    is_direct_paid = False
    if paid_ref and query:
        trx = Transaction.objects.filter(reference=paid_ref, user=request.user, status='success').first()
        if trx:
            is_direct_paid = True
            allowed = True
            if trx.is_active:
                trx.is_active = False
                trx.save(update_fields=['is_active'])

    if request.method == 'POST' or (is_direct_paid and query):
        raw_query = request.POST.get('query', query).strip()
        query = raw_query
        action = request.POST.get('action', 'search')

        if not raw_query:
            result = {'error': 'Please enter a phone number or NIN to search.'}
        else:
            digits_only = ''.join(c for c in raw_query if c.isdigit())

            if len(digits_only) != 11:
                result = {
                    'error': (
                        'Enter exactly 11 digits — a Nigerian phone number '
                        '(e.g. 08012345678) or an 11-digit NIN.'
                    )
                }
            elif not allowed and reason == 'service_restricted':
                result = {
                    'error': details.get('message', 'Access to person quick-checks has been restricted for your account by platform administration.'),
                    'subscription_required': False,
                }
            elif not allowed and action == 'payg':
                import uuid
                # 1. Full coverage from user available account balance
                if user_balance >= payg_price:
                    ok, rem_bal = deduct_user_prepaid_balance(request.user, payg_price, "Person Quick-Check")
                    if ok:
                        paid_token = f"VNG-BAL-{uuid.uuid4().hex[:12].upper()}"
                        Transaction.objects.create(
                            user=request.user,
                            reference=paid_token,
                            amount_kobo=payg_price * 100,
                            status='success',
                            is_active=False,
                            paystack_response={
                                'data': {
                                    'metadata': {
                                        'service': 'person_check',
                                        'query': digits_only,
                                        'payment_method': 'account_balance',
                                    }
                                }
                            }
                        )
                        messages.success(
                            request,
                            f"₦{payg_price:,.0f} paid from your account balance (Remaining balance: ₦{rem_bal:,.0f}). "
                            "Person quick-check unlocked."
                        )
                        is_direct_paid = True
                        allowed = True

                if not is_direct_paid:
                    # 2. Partial coverage from balance + top-up difference via Paystack
                    checkout_amount = payg_price
                    covered_amount = 0
                    if 0 < user_balance < payg_price:
                        covered_amount = user_balance
                        checkout_amount = topup_needed
                        deduct_user_prepaid_balance(request.user, user_balance, "Partial top-up for Person Quick-Check")

                    try:
                        checkout_data = initialize_service_checkout(
                            user=request.user,
                            service='person_check',
                            tier='standard',
                            amount_naira=checkout_amount,
                            metadata={
                                'service': 'person_check',
                                'query': digits_only,
                                'covered_by_balance': covered_amount,
                            }
                        )
                        request.session['vng_pending_ref'] = checkout_data['reference']
                        request.session['pending_person_check_query'] = digits_only
                        return redirect(checkout_data['authorization_url'])
                    except Exception as exc:
                        if covered_amount > 0:
                            # Refund partially deducted balance on checkout initialization failure
                            Transaction.objects.create(
                                user=request.user,
                                reference=f"VNG-REFUND-{uuid.uuid4().hex[:12].upper()}",
                                amount_kobo=covered_amount * 100,
                                status='success',
                                is_active=True,
                                paystack_response={
                                    'data': {
                                        'metadata': {
                                            'service': 'topup',
                                            'reason': 'Checkout initialization failure refund'
                                        }
                                    }
                                }
                            )
                        logger.exception("Failed to initialize person check checkout: %s", exc)
                        result = {
                            'error': f"Payment gateway error: {exc}",
                            'subscription_required': True,
                            'can_payg': True,
                            'payg_price': payg_price,
                            'user_balance': user_balance,
                            'topup_needed': topup_needed,
                            'query': raw_query,
                        }
            elif not allowed:
                # Quota exhausted: display error with clear Pay-As-You-Go option
                result = {
                    'error': (
                        'You have reached your check limit or require an active subscription '
                        'to perform person quick-checks.'
                    ),
                    'subscription_required': True,
                    'can_payg': True,
                    'payg_price': payg_price,
                    'user_balance': user_balance,
                    'topup_needed': topup_needed,
                    'query': raw_query,
                }
            else:
                # Execute search
                phone_prefixes = ('070', '080', '081', '090', '091', '071', '091')
                if digits_only[:3] in phone_prefixes:
                    query_type = 'phone'
                    id_type    = 'phone'
                else:
                    query_type = 'nin'
                    id_type    = 'nin'

                try:
                    value_hash = hash_identifier_value(id_type, digits_only)
                except ValueError as val_err:
                    result = {'error': str(val_err)}
                    value_hash = None

                ident = None
                if value_hash:
                    ident = (
                        Identifier.objects
                        .filter(type=id_type, value_hash=value_hash)
                        .select_related('subject')
                        .first()
                    )

                if not is_direct_paid:
                    consume_user_entitlement(request.user, service='person_check', cost=1)

                if ident is None:
                    result = {
                        'found':      False,
                        'query':      raw_query,
                        'query_type': query_type,
                    }
                else:
                    subject = ident.subject
                    trust_score = getattr(subject, 'trust_score', None)
                    fraud_reports = []
                    fraud_count   = 0
                    try:
                        fraud_qs = (
                            FraudReport.objects
                            .filter(
                                target_subject=subject,
                                state='published',
                            )
                            .order_by('-created_at')[:5]
                        )
                        fraud_count   = fraud_qs.count()
                        fraud_reports = list(fraud_qs)
                    except Exception:
                        pass
                    result = {
                        'found':         True,
                        'subject':       subject,
                        'trust_score':   trust_score,
                        'fraud_reports': fraud_reports,
                        'fraud_count':   fraud_count,
                        'query':         raw_query,
                        'query_type':    query_type,
                    }

    context = {
        'profile':         profile,
        'result':          result,
        'query':           query,
        'has_entitlement': allowed,
        'payg_price':      payg_price,
        'page_title':      'Person Quick-Check',
    }
    return render(request, 'employer/person_check.html', context)


# ---------------------------------------------------------------------------
# Staff Misconduct Reporting on Clearance Certificate (DBS)
# ---------------------------------------------------------------------------
@login_required
@employer_required
@verified_profile_required
def staff_misconduct_report(request):
    """
    Legally-grounded 4-step wizard for an employer to report workplace misconduct
    against a staff member holding a VerifyNG Clearance Certificate.
    Enforces mandatory documentary proof, legal indemnity warranty, and audit logging.
    """
    allowed, reason, details = check_user_entitlement(request.user, service='misconduct_report')
    if not allowed and reason == 'service_restricted':
        messages.error(request, details.get('message', "Your organization has been restricted from submitting staff misconduct reports by platform administration."))
        return redirect('employer:dashboard')

    profile = _get_or_create_employer_profile(request.user)
    certificate_id_prefill = request.GET.get('certificate_id', '').strip()
    if request.method == 'POST':
        cert_id = request.POST.get('certificate_id', '').strip().upper()
        staff_name = request.POST.get('staff_name', '').strip()
        job_role = request.POST.get('job_role', '').strip()
        incident_date = request.POST.get('incident_date') or None
        misconduct_category = request.POST.get('misconduct_category', 'theft')
        financial_loss = request.POST.get('financial_loss', '').strip()
        allegation = request.POST.get('allegation', '').strip()
        evidence_doc_type = request.POST.get('evidence_doc_type', 'internal_query')
        evidence_file = request.FILES.get('evidence_file')
        warrant_truth = request.POST.get('warrant_truth') == 'on'
        indemnify_platform = request.POST.get('indemnify_platform') == 'on'
        errors = []
        if not cert_id:
            errors.append("Staff Clearance Certificate ID is required.")
        if not staff_name:
            errors.append("Staff member's legal name is required.")
        if not allegation or len(allegation) < 30:
            errors.append("Please provide a factual, detailed chronological statement (at least 30 characters).")
        if not evidence_file:
            errors.append("Mandatory documentary proof (Internal Query, Police FIR, or Audit Sheet) is required.")
        if not (warrant_truth and indemnify_platform):
            errors.append("You must warrant the truth of this report and accept the legal indemnity agreement.")
        certificate = None
        if cert_id:
            certificate = VerificationCertificate.objects.filter(certificate_id=cert_id).select_related('subject', 'holder').first()
            if not certificate:
                errors.append(f"Clearance Certificate [{cert_id}] was not found on the VerifyNG registry. Please verify the ID.")
        if errors:
            context = {
                'profile': profile,
                'errors': errors,
                'form_data': request.POST,
                'certificate': certificate,
                'certificate_id_prefill': cert_id or certificate_id_prefill,
                'page_title': 'Report Staff Misconduct',
            }
            return render(request, 'employer/staff_misconduct_report.html', context)
        # Upload documentary evidence to secure cloud/local storage
        evidence_public_id = ''
        if evidence_file:
            try:
                storage = get_storage_service()
                res = storage.upload_evidence(evidence_file, folder_prefix='misconduct_evidence')
                evidence_public_id = res.get('public_id', '')
            except StorageError as e:
                messages.error(request, f"Evidence upload failed: {e}")
                return redirect('employer:staff_misconduct_report')
        # Create the FraudReport tied directly to the Certificate's SubjectEntity
        target_subject = certificate.subject if certificate else None
        if not target_subject:
            target_subject = SubjectEntity.objects.create(name=staff_name, type='person')
        category_labels = {
            'theft': 'Financial Misappropriation & Cash Theft',
            'absconded': 'Absconded with Company Property or Goods',
            'inventory': 'Inventory Diversion / Stock Shortage',
            'forgery': 'Falsification of Business Records / Forgery',
            'violence': 'Workplace Violence / Safety Threat',
        }
        title = f"Staff Misconduct [{cert_id}]: {category_labels.get(misconduct_category, 'Workplace Misconduct')}"
        report_ref = generate_report_reference_number()
        full_allegation = (
            f"WORKPLACE MISCONDUCT REPORT\n"
            f"Employer: {profile.company_name} (RC: {profile.company_rc_number or 'N/A'})\n"
            f"Certificate ID: {cert_id}\n"
            f"Role: {job_role or 'Staff'}\n"
            f"Category: {category_labels.get(misconduct_category, misconduct_category)}\n"
            f"Estimated Loss: {financial_loss or 'Not specified'}\n"
            f"Evidence Type: {evidence_doc_type}\n\n"
            f"Factual Timeline & Details:\n{allegation}"
        )
        with transaction.atomic():
            report = FraudReport.objects.create(
                reference_number=report_ref,
                reporter=request.user,
                target_subject=target_subject,
                title=title,
                allegation=full_allegation,
                incident_date=incident_date,
                state='submitted',
            )
            if evidence_public_id or evidence_file:
                ReportEvidence.objects.create(
                    report=report,
                    file=evidence_file,
                    file_type='document',
                    description=f"{evidence_doc_type} uploaded by employer {profile.company_name}",
                    storage_public_id=evidence_public_id,
                    is_confidential=True,
                )
            # Log complete audit trail with IP, Device, Browser, OS, and Location
            log_admin_action(
                action='STAFF_MISCONDUCT_REPORTED',
                action_type='REPORT',
                performed_by=request.user,
                report=report,
                request=request,
                details={
                    'certificate_id': cert_id,
                    'staff_name': staff_name,
                    'employer': profile.company_name,
                    'misconduct_category': misconduct_category,
                    'estimated_loss': financial_loss,
                    'evidence_public_id': evidence_public_id,
                }
            )
        # 1. Dispatch Employer Confirmation Receipt via built-in email template
        try:
            emp_html, emp_text = render_email('misconduct_receipt', {
                'employer_name': profile.company_name,
                'staff_name': staff_name,
                'certificate_id': cert_id,
                'report_ref': report_ref,
                'category_display': category_labels.get(misconduct_category, misconduct_category),
                'submitted_at': timezone.now().strftime('%d %B %Y, %H:%M UTC'),
            })
            emp_msg = EmailMultiAlternatives(
                subject=f"Misconduct Report Received [{report_ref}] — VerifyNG Compliance Desk",
                body=emp_text,
                from_email=None,
                to=[request.user.email],
            )
            emp_msg.attach_alternative(emp_html, 'text/html')
            emp_msg.send(fail_silently=True)
        except Exception as exc:
            logger.warning("Failed to dispatch employer misconduct receipt email: %s", exc)
        # 2. Dispatch 7-Day Due Process Notice to Certificate Holder (if registered)
        if certificate and certificate.holder and certificate.holder.email:
            try:
                deadline_str = (timezone.now() + timedelta(days=7)).strftime('%d %B %Y')
                dispute_url = request.build_absolute_uri(
                    reverse('reports:create_dispute', kwargs={'reference_number': report_ref})
                )
                staff_html, staff_text = render_email('misconduct_notice', {
                    'staff_name': certificate.holder.get_full_name() or certificate.holder.username,
                    'certificate_id': cert_id,
                    'employer_name': profile.company_name,
                    'category_display': category_labels.get(misconduct_category, misconduct_category),
                    'report_ref': report_ref,
                    'dispute_deadline': deadline_str,
                    'dispute_url': dispute_url,
                })
                staff_msg = EmailMultiAlternatives(
                    subject=f"Important Notice Regarding Your Workforce Clearance Certificate [{cert_id}]",
                    body=staff_text,
                    from_email=None,
                    to=[certificate.holder.email],
                )
                staff_msg.attach_alternative(staff_html, 'text/html')
                staff_msg.send(fail_silently=True)
            except Exception as exc:
                logger.warning("Failed to dispatch employee 7-day misconduct notice email: %s", exc)

            # In-app notification for the certificate holder
            try:
                from notifications.services import dispatch_notification
                dispatch_notification(
                    recipient=certificate.holder,
                    event_type='REPORT_SUBMITTED',
                    title=f"Workplace Misconduct Filing [{report_ref}]",
                    body=(
                        f"A workplace misconduct report [{report_ref}] has been filed by {profile.company_name} "
                        f"regarding certificate [{cert_id}]. "
                        f"You have 7 days to review and submit your formal right-of-response."
                    ),
                    object_reference=report_ref,
                )
            except Exception as notif_err:
                logger.warning("Failed to dispatch in-app misconduct notice: %s", notif_err)
        
        messages.success(
            request,
            f"Workplace misconduct report [{report_ref}] submitted successfully. "
            "Our compliance desk will review your documentary proof before initiating due-process notification."
        )
        return redirect('employer:dashboard')
    context = {
        'profile': profile,
        'certificate_id_prefill': certificate_id_prefill,
        'page_title': 'Report Staff Misconduct',
    }
    return render(request, 'employer/staff_misconduct_report.html', context)


@login_required
@employer_required
def staff_misconduct_list(request):
    """
    Dedicated paginated list of all workplace misconduct reports filed by the employer.
    Mobile-first with quick status filtering and search.
    """
    profile = _get_or_create_employer_profile(request.user)
    status_filter = request.GET.get('status', '').strip()
    search_query = request.GET.get('q', '').strip()
    qs = (
        FraudReport.objects
        .filter(reporter=request.user)
        .select_related('target_subject')
        .order_by('-created_at')
    )
    if status_filter in ('submitted', 'under_review', 'published', 'resolved', 'rejected'):
        qs = qs.filter(state=status_filter)
    if search_query:
        qs = qs.filter(
            Q(reference_number__icontains=search_query) |
            Q(target_subject__name__icontains=search_query) |
            Q(title__icontains=search_query)
        )
    paginator = Paginator(qs, 15)
    page_obj = paginator.get_page(request.GET.get('page', 1))
    status_tabs = [
        ('submitted', 'Under Review'),
        ('under_review', '7-Day Notice'),
        ('published', 'Published'),
        ('resolved', 'Resolved'),
    ]
    context = {
        'profile': profile,
        'page_obj': page_obj,
        'status_filter': status_filter,
        'search_query': search_query,
        'status_tabs': status_tabs,
        'page_title': 'Filed Misconduct Reports',
    }
    return render(request, 'employer/staff_misconduct_list.html', context)

# ---------------------------------------------------------------------------
# CSV Export — BATCH 8
# ---------------------------------------------------------------------------

@login_required
@employer_required
def staff_check_export_csv(request):
    """
    Stream the employer's staff check history as a downloadable CSV file.
    NIN hashes are NEVER exported — only non-sensitive fields.
    """
    profile = _get_or_create_employer_profile(request.user)

    qs = (
        StaffCheckRequest.objects
        .filter(employer=profile, is_active=True)
        .order_by('-created_at')
    )

    # Apply the same status filter if passed via query param
    status_filter = request.GET.get('status', '')
    if status_filter in ('pending', 'processing', 'completed', 'failed', 'cancelled'):
        qs = qs.filter(status=status_filter)

    response = HttpResponse(content_type='text/csv')
    filename = f"verifyng_staff_checks_{timezone.now().strftime('%Y%m%d_%H%M')}.csv"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)
    writer.writerow([
        'Reference ID',
        'Full Name',
        'Phone Number',
        'Email',
        'Check Type',
        'Purpose',
        'Status',
        'Fraud Flags',
        'Result Summary',
        'Submitted Date',
        'Completed Date',
    ])

    for check in qs:
        writer.writerow([
            str(check.id)[:8].upper(),
            check.full_name,
            check.phone_number or '—',
            check.email or '—',
            check.get_check_type_display(),
            check.purpose or '—',
            check.get_status_display(),
            check.fraud_flags,
            check.result_summary or '—',
            check.created_at.strftime('%Y-%m-%d %H:%M') if check.created_at else '—',
            check.completed_at.strftime('%Y-%m-%d %H:%M') if check.completed_at else '—',
        ])


    return response


# ---------------------------------------------------------------------------
# Workforce Clearance Certificate (DBS) Verification
# ---------------------------------------------------------------------------

@login_required
@employer_required
def employer_certificate_verify(request):
    """
    UK DBS Online Status Check equivalent for employers, agencies, and screening teams.
    Allows an employer to enter a candidate's Certificate ID (e.g. WCC-XXXX-YYYY / VNG-YYYY-XXXXXXXX)
    and candidate Surname and Date of Birth. All three fields are required.
    Supports subscription quota AND direct Paystack Pay-As-You-Go checkout.
    """
    from payments.models import Transaction
    profile = _get_or_create_employer_profile(request.user)
    site_settings = SiteSettings.get()
    payg_price = site_settings.get_service_price('certificate_verify')

    result = None
    cert_id_input = request.GET.get('certificate_id', '').strip().upper()
    surname_input = request.GET.get('surname', '').strip()
    dob_input = request.GET.get('date_of_birth', '').strip()

    # Check if returning from a direct Paystack payment, unconsumed credit, or active account balance
    paid_ref = request.GET.get('paid_ref', '').strip()
    is_direct_paid = False
    paid_tx = None
    from payments.services import get_user_prepaid_balance, deduct_user_prepaid_balance, get_topup_difference
    user_balance = get_user_prepaid_balance(request.user)
    topup_needed = get_topup_difference(user_balance, payg_price)

    if request.user.is_authenticated:
        if paid_ref:
            cand = Transaction.objects.filter(reference=paid_ref, user=request.user, status='success', is_active=True).first()
            if cand:
                meta = (cand.paystack_response or {}).get('data', {}).get('metadata', {})
                if meta.get('service') == 'certificate_verify':
                    paid_tx = cand
                    is_direct_paid = True
        if not is_direct_paid and user_balance >= payg_price:
            is_direct_paid = True

    allowed, reason, details = check_user_entitlement(request.user, service='certificate_verify', cost=1)
    if is_direct_paid:
        allowed = True

    from core.permissions import is_profile_verified
    is_company_verified, _ = is_profile_verified(request.user)

    if request.method == 'POST' or (is_direct_paid and cert_id_input):
        if request.method == 'POST':
            cert_id_input = request.POST.get('certificate_id', '').strip().upper()
            surname_input = request.POST.get('surname', '').strip()
            dob_input = request.POST.get('date_of_birth', '').strip()
        action = request.POST.get('action', 'verify')

        missing = []
        if not cert_id_input:
            missing.append("Certificate Reference ID")
        if not surname_input:
            missing.append("Candidate Surname")
        if not dob_input:
            missing.append("Date of Birth")

        if missing:
            result = {
                'lookup_state': 'VALIDATION_ERROR',
                'message': f"All three fields are required to match the record: {', '.join(missing)}.",
            }
        elif not allowed and reason == 'service_restricted':
            result = {
                'lookup_state': 'ACCESS_RESTRICTED',
                'message': details.get('message', 'Access to certificate verification has been restricted for your account by platform administration.'),
            }
        elif not allowed and action == 'payg':
            import uuid
            # 1. Full coverage from user available account balance
            if user_balance >= payg_price:
                if not is_company_verified:
                    result = {
                        'lookup_state': 'COMPANY_VERIFICATION_REQUIRED',
                        'certificate_id': cert_id_input,
                        'message': (
                            "Company Profile Verification Required: Candidate workforce clearance records cannot be revealed "
                            "until your company's CAC incorporation documents are verified by platform compliance officers. "
                            "No funds were deducted from your wallet balance."
                        ),
                        'wallet_credited': False,
                        'payg_price': payg_price,
                        'user_balance': user_balance,
                    }
                elif True:
                    ok, rem_bal = deduct_user_prepaid_balance(request.user, payg_price, "Certificate Verification")
                if ok:
                    paid_token = f"VNG-BAL-{uuid.uuid4().hex[:12].upper()}"
                    Transaction.objects.create(
                        user=request.user,
                        reference=paid_token,
                        amount_kobo=payg_price * 100,
                        status='success',
                        is_active=False,
                        paystack_response={
                            'data': {
                                'metadata': {
                                    'service': 'certificate_verify',
                                    'certificate_id': cert_id_input,
                                    'surname': surname_input,
                                    'dob': dob_input,
                                    'payment_method': 'account_balance',
                                }
                            }
                        }
                    )
                    messages.success(
                        request,
                        f"₦{payg_price:,.0f} paid from your account balance (Remaining balance: ₦{rem_bal:,.0f}). "
                        "Certificate check unlocked."
                    )
                    is_direct_paid = True
                    allowed = True

            if not is_direct_paid:
                # 2. Partial coverage from balance + top-up difference via Paystack
                checkout_amount = payg_price
                covered_amount = 0
                if 0 < user_balance < payg_price:
                    covered_amount = user_balance
                    checkout_amount = topup_needed
                    deduct_user_prepaid_balance(request.user, user_balance, "Partial top-up for Certificate Verification")

                try:
                    checkout_data = initialize_service_checkout(
                        user=request.user,
                        service='certificate_verify',
                        tier='standard',
                        amount_naira=checkout_amount,
                        metadata={
                            'service': 'certificate_verify',
                            'certificate_id': cert_id_input,
                            'surname': surname_input,
                            'dob': dob_input,
                            'covered_by_balance': covered_amount,
                        }
                    )
                    request.session['vng_pending_ref'] = checkout_data['reference']
                    return redirect(checkout_data['authorization_url'])
                except Exception as exc:
                    if covered_amount > 0:
                        # Refund partially deducted balance on checkout initialization failure
                        Transaction.objects.create(
                            user=request.user,
                            reference=f"VNG-REFUND-{uuid.uuid4().hex[:12].upper()}",
                            amount_kobo=covered_amount * 100,
                            status='success',
                            is_active=True,
                            paystack_response={
                                'data': {
                                    'metadata': {
                                        'service': 'topup',
                                        'reason': 'Checkout initialization failure refund'
                                    }
                                }
                            }
                        )
                    logger.exception("Failed to initialize certificate verify checkout: %s", exc)
                    result = {
                        'lookup_state': 'QUOTA_EXCEEDED',
                        'message': f"Payment gateway error: {exc}",
                        'subscription_required': True,
                        'can_payg': True,
                        'payg_price': payg_price,
                        'user_balance': user_balance,
                        'topup_needed': topup_needed,
                    }
        elif not allowed:
            result = {
                'lookup_state': 'QUOTA_EXCEEDED',
                'message': (
                    'You have reached your verification check limit or require an active subscription '
                    'to perform live certificate status checks.'
                ),
                'subscription_required': True,
                'can_payg': True,
                'payg_price': payg_price,
                'user_balance': user_balance,
                'topup_needed': topup_needed,
            }
        else:
            if not is_company_verified:
                # Unverified employers cannot inspect candidate clearance records.
                # If Paystack payment was made, ensure it remains active to credit wallet.
                if is_direct_paid and paid_tx:
                    paid_tx.is_active = True
                    paid_tx.save(update_fields=['is_active'])

                current_balance = get_user_prepaid_balance(request.user)
                result = {
                    'lookup_state': 'COMPANY_VERIFICATION_REQUIRED',
                    'certificate_id': cert_id_input,
                    'message': (
                        "Company Profile Verification Required: Candidate workforce clearance records cannot be revealed "
                        "until your company's CAC incorporation documents are verified by platform compliance officers. "
                        + ("Your payment of ₦{:,.0f} has been credited to your account wallet balance.".format(payg_price) if is_direct_paid else "")
                    ),
                    'wallet_credited': bool(is_direct_paid),
                    'payg_price': payg_price,
                    'user_balance': current_balance,
                }
            else:
                # Query registry for certificate
                cert = (
                    VerificationCertificate.objects
                    .filter(certificate_id=cert_id_input)
                    .select_related('holder', 'subject')
                    .first()
                )

                if not cert:
                    lookup_state = 'NOT_FOUND'
                else:
                    # Retrieve application metadata for surname / DOB verification
                    app_log = None
                    for l in AuditLog.objects.filter(action="TRUSTPASS_APPLICATION_SUBMITTED").order_by('-timestamp')[:50]:
                        d = l.details if isinstance(l.details, dict) else {}
                        if d.get('certificate_id') == cert.certificate_id:
                            app_log = l
                            break
                    det = app_log.details if (app_log and isinstance(app_log.details, dict)) else {}

                    # Candidate full name
                    cand_name = (cert.subject.name if cert.subject else None) or det.get('full_name') or ''
                    if not cand_name and cert.holder:
                        cand_name = cert.holder.get_full_name() or cert.holder.username

                    # Validate required surname against candidate tokens & holder name
                    cand_tokens = [t.lower() for t in re.split(r'[\s,\.-]+', cand_name) if t]
                    holder_last = (cert.holder.last_name or '').lower() if cert.holder else ''
                    surname_clean = surname_input.lower().strip()
                    surname_matches = (
                        surname_clean in cand_tokens
                        or surname_clean == holder_last
                        or (len(surname_clean) >= 3 and any(surname_clean in tok or tok in surname_clean for tok in cand_tokens))
                    )

                    # Validate required DOB
                    reg_dob = str(det.get('date_of_birth', '')).strip()
                    if not reg_dob and getattr(cert.holder, 'date_of_birth', None):
                        reg_dob = cert.holder.date_of_birth.strftime('%Y-%m-%d')

                    dob_matches = True
                    if reg_dob:
                        dob_matches = (dob_input.strip() == reg_dob)

                    if not surname_matches or not dob_matches:
                        lookup_state = 'SURNAME_DOB_MISMATCH'
                    elif cert.status == 'revoked':
                        lookup_state = 'REVOKED'
                    elif cert.status == 'suspended':
                        lookup_state = 'SUSPENDED'
                    elif not cert.is_valid:
                        lookup_state = 'EXPIRED'
                    elif not cert.is_live_searchable:
                        lookup_state = 'GRACE_EXPIRED_MONITORING_REQUIRED'
                    else:
                        lookup_state = 'ACTIVE_VALID'

                # Consume entitlement upon successful query attempt if not direct paid, or consume direct pre-paid credit
                if is_direct_paid and paid_tx:
                    paid_tx.is_active = False
                    paid_tx.save(update_fields=['is_active'])
                elif is_direct_paid and user_balance >= payg_price:
                    deduct_user_prepaid_balance(request.user, payg_price, "Certificate Verify")
                elif not is_direct_paid:
                    consume_user_entitlement(request.user, service='certificate_verify', cost=1)

                candidate_name = '—'
                nin_masked = 'Verified Record'
                adjudicated_reports = []
                check_level_display = 'Standard Clearance'
                issued_date = None
                expires_at = None

                if cert:
                    candidate_name = (cert.subject.name if cert.subject else None) or det.get('full_name')
                    if not candidate_name and cert.holder:
                        candidate_name = cert.holder.get_full_name() or cert.holder.username

                    nin_raw = det.get('nin', '')
                    nin_masked = det.get('nin_masked')
                    if not nin_masked and nin_raw and len(nin_raw) >= 6:
                        nin_masked = nin_raw[:3] + '****' + nin_raw[-2:]
                    elif not nin_masked:
                        nin_masked = 'Verified Record'

                    check_level_display = (
                        cert.get_check_level_display()
                        if hasattr(cert, 'get_check_level_display')
                        else cert.check_level.title()
                    )
                    issued_date = cert.issued_at or cert.created_at
                    expires_at = cert.expires_at

                    if cert.subject:
                        adjudicated_reports = list(
                            FraudReport.objects
                            .filter(target_subject=cert.subject, state='published')
                            .order_by('-created_at')[:5]
                        )

                    # Log query in CertificateQueryLog so candidate has a complete transparency record
                    try:
                        CertificateQueryLog.objects.create(
                            certificate=cert,
                            queried_by=request.user,
                            payment=None,
                            ip_address=get_client_ip(request),
                            purpose='hiring',
                            organisation_name=profile.company_name,
                            result_snapshot={
                                'lookup_state': lookup_state,
                                'status': cert.status,
                                'is_live_searchable': cert.is_live_searchable,
                                'misconduct_count': len(adjudicated_reports),
                                'employer_company': profile.company_name,
                                'employer_username': request.user.username,
                                'timestamp': timezone.now().isoformat(),
                            }
                        )
                    except Exception as log_err:
                        logger.warning("Could not create CertificateQueryLog: %s", log_err)

                # Log admin audit trail
                try:
                    AuditLog.objects.create(
                        report=None,
                        action="EMPLOYER_CERTIFICATE_DBS_CHECK",
                        performed_by=request.user,
                        ip_address=get_client_ip(request),
                        details={
                            "certificate_id": cert_id_input,
                            "employer": profile.company_name,
                            "lookup_state": lookup_state,
                        }
                    )
                except Exception:
                    pass

                result = {
                    'lookup_state': lookup_state,
                    'cert': cert,
                    'certificate_id': cert_id_input,
                    'candidate_name': candidate_name,
                    'nin_masked': nin_masked,
                    'check_level': check_level_display,
                    'issued_date': issued_date,
                    'expires_at': expires_at,
                    'adjudicated_reports': adjudicated_reports,
                    'has_misconduct': len(adjudicated_reports) > 0,
                    'in_grace_period': cert.in_grace_period if cert else False,
                    'grace_days_remaining': cert.grace_days_remaining if cert else 0,
                    'is_monitoring_valid': cert.is_monitoring_valid if cert else False,
                }

    context = {
        'profile': profile,
        'result': result,
        'cert_id_input': cert_id_input,
        'surname_input': surname_input,
        'dob_input': dob_input,
        'has_entitlement': allowed,
        'payg_price': payg_price,
        'page_title': 'Verify Workforce Certificate (TrustPass)',
        'is_company_verified': is_company_verified,
        'user_balance': user_balance,
        'topup_needed': topup_needed,
    }
    return render(request, 'employer/certificate_verify.html', context)
