

# employer/views.py
import logging
import csv
import io
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.decorators import method_decorator
from django.views import View
from django.db import transaction
from .tasks import process_bulk_upload_task
from django.http import HttpResponse
from .models import BulkCheckUpload, BulkCheckRow

from django.core.files.storage import default_storage
from django.core.files.base import ContentFile


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




# ---------------------------------------------------------------------------
# Bulk Checks — Upload form — BATCH 2
# ---------------------------------------------------------------------------




@login_required
@employer_required
def bulk_upload_create(request):
    """
    GET  — render the upload form with CSV template download link.
    POST — validate uploaded CSV, create BulkCheckUpload + BulkCheckRow records,
           trigger Celery task, redirect to detail page.
    """
    profile = _get_or_create_employer_profile(request.user)

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
                    nin_hash = hashlib.sha256(raw_nin.encode('utf-8')).hexdigest()

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
            # Task will need to be triggered manually or via admin — upload still created

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





