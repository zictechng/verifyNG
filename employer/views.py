

# employer/views.py
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.decorators import method_decorator
from django.views import View

from core.permissions import employer_required
from .models import BulkCheckUpload, EmployerProfile, TeamMember

logger = logging.getLogger(__name__)


def _get_or_create_employer_profile(user) -> EmployerProfile:
    """Return existing employer profile or create a minimal one on first visit."""
    profile, created = EmployerProfile.objects.get_or_create(
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
    team_count = TeamMember.objects.filter(employer=profile, is_active=True).count()
    total_uploads = BulkCheckUpload.objects.filter(employer=profile).count()

    context = {
        'profile': profile,
        'recent_uploads': recent_uploads,
        'team_count': team_count,
        'total_uploads': total_uploads,
        'page_title': 'Employer Dashboard',
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
        profile.company_name = request.POST.get('company_name', profile.company_name).strip()
        profile.company_rc_number = request.POST.get('company_rc_number', '').strip()
        profile.industry = request.POST.get('industry', '').strip()
        profile.company_address = request.POST.get('company_address', '').strip()
        profile.contact_phone = request.POST.get('contact_phone', '').strip()
        profile.save(update_fields=[
            'company_name', 'company_rc_number', 'industry',
            'company_address', 'contact_phone', 'updated_at',
        ])
        messages.success(request, 'Company profile updated.')
        return redirect('employer:profile')

    context = {
        'profile': profile,
        'page_title': 'Company Profile',
    }
    return render(request, 'employer/profile.html', context)


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

    members = (
        TeamMember.objects.filter(employer=profile, is_active=True)
        .select_related('user', 'invited_by')
        .order_by('-created_at')
    )

    context = {
        'profile': profile,
        'members': members,
        'page_title': 'Team Members',
    }
    return render(request, 'employer/team_list.html', context)


# ---------------------------------------------------------------------------
# Staff Checks — BATCH 1
# ---------------------------------------------------------------------------

import hashlib
import json
from django.http import JsonResponse
from django.views.decorators.http import require_POST


def _hash_nin(raw_nin: str) -> str:
    return hashlib.sha256(raw_nin.strip().encode('utf-8')).hexdigest()


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
def staff_check_create(request):
    profile = _get_or_create_employer_profile(request.user)

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
                'profile':    profile,
                'errors':     errors,
                'form_data':  request.POST,
                'page_title': 'New Staff Check',
            }
            return render(request, 'employer/staff_check_create.html', context)

        from .models import StaffCheckRequest
        check = StaffCheckRequest.objects.create(
            employer     = profile,
            requested_by = request.user,
            full_name    = full_name,
            phone_number = phone_number,
            nin_hash     = _hash_nin(raw_nin) if raw_nin else '',
            email        = email,
            check_type   = check_type,
            purpose      = purpose,
        )

        messages.success(request, f'Check request submitted for {full_name}. Reference: {str(check.id)[:8].upper()}')
        return redirect('employer:staff_check_detail', check_id=check.id)

    context = {
        'profile':    profile,
        'page_title': 'New Staff Check',
    }
    return render(request, 'employer/staff_check_create.html', context)


@login_required
@employer_required
def staff_check_detail(request, check_id):
    profile = _get_or_create_employer_profile(request.user)
    from .models import StaffCheckRequest
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
    from .models import StaffCheckRequest
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
    from .models import StaffCheckMonitor

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
@require_POST
def monitoring_toggle(request, check_id):
    """
    Fetch + Toast: enables or disables monitoring for a completed staff check.
    - If no monitor exists → create one (active).
    - If monitor is active → pause it.
    - If monitor is paused → reactivate it.
    """
    profile = _get_or_create_employer_profile(request.user)
    from .models import StaffCheckRequest, StaffCheckMonitor

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
            monitor.monitor_status = 'active'
            monitor.save(update_fields=['monitor_status', 'updated_at'])
            msg = f'Monitoring resumed for {check.full_name}.'
            new_status = 'active'
    else:
        msg = f'Monitoring started for {check.full_name}.'
        new_status = 'active'

    return JsonResponse({'ok': True, 'message': msg, 'monitor_status': new_status})



