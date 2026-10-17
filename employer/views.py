

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
from .tasks import process_bulk_upload_task, process_single_staff_check_task
from django.http import HttpResponse
from .models import BulkCheckUpload, BulkCheckRow
from reports.models import FraudReport
from identities.models import Identifier, SubjectEntity
from django.core.mail import EmailMultiAlternatives

from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.shortcuts import redirect as _redirect
from .models import TeamInvite
from datetime import timedelta
from .models import StaffCheckRequest
from payments.models import Subscription

from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone

from core.permissions import employer_required
from .models import BulkCheckUpload, EmployerProfile, TeamMember
import hashlib
import json
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from identities.utils import hash_identifier_value
from payments.services import check_user_entitlement, consume_user_entitlement

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
    team_count = TeamMember.objects.filter(employer=profile, is_active=True).count()
    total_uploads = BulkCheckUpload.objects.filter(employer=profile).count()

    # Staff check stats
    staff_checks_total     = StaffCheckRequest.objects.filter(employer=profile, is_active=True).count()
    staff_checks_pending   = StaffCheckRequest.objects.filter(employer=profile, is_active=True, status='pending').count()
    staff_checks_completed = StaffCheckRequest.objects.filter(employer=profile, is_active=True, status='completed').count()

    recent_checks = (
        StaffCheckRequest.objects
        .filter(employer=profile, is_active=True)
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
    context = {
        'profile':                profile,
        'recent_uploads':         recent_uploads,
        'team_count':             team_count,
        'total_uploads':          total_uploads,
        'staff_checks_total':     staff_checks_total,
        'staff_checks_pending':   staff_checks_pending,
        'staff_checks_completed': staff_checks_completed,
        'recent_checks':          recent_checks,
        'active_subscription':    active_subscription,
        'entitlement_reason':     entitlement_reason,
        'entitlement_info':       entitlement_info,
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
        
        # Enforce check entitlement before proceeding
        allowed, reason, details = check_user_entitlement(request.user, cost=1)
        if not allowed:
            messages.error(
                request,
                "You have reached your check limit or require an active subscription to perform checks. "
                "Please upgrade your plan to continue."
            )
            return redirect('payments:plans')
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
        # Deduct 1 check entitlement
        consume_user_entitlement(request.user, cost=1)

        # Dispatch background check processing task
        try:
            process_single_staff_check_task.delay(str(check.id))
        except Exception as exc:
            logger.warning("Could not dispatch Celery task for check %s: %s", check.id, exc)
            # Resilient fallback: run inline if Celery/Redis is offline in local dev
            try:
                process_single_staff_check_task(str(check.id))
            except Exception as e:
                logger.exception("Inline execution failed for check %s: %s", check.id, e)

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
        allowed, reason, details = check_user_entitlement(request.user, cost=cost)
        if not allowed:
            remaining = details.get('remaining', 0)
            return render(request, 'employer/bulk_upload_create.html', {
                'profile': profile,
                'errors': [
                    f'Insufficient check quota. This bulk upload requires {cost} checks, '
                    f'but your plan only has {remaining} checks remaining. '
                    f'Please upgrade your plan to continue.'
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
            consume_user_entitlement(request.user, cost=cost)
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
    GET  — empty search form.
    POST — run the lookup and display results on the same page.
    """
    profile = _get_or_create_employer_profile(request.user)

    result    = None
    query     = ''
    query_type = ''

    if request.method == 'POST':
        raw_query = request.POST.get('query', '').strip()
        query = raw_query

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
            else:
                # Check credit/subscription entitlement
                allowed, reason, details = check_user_entitlement(request.user, cost=1)
                if not allowed:
                    result = {
                        'error': (
                            'You have reached your check limit or require an active subscription '
                            'to perform person quick-checks. Please upgrade your plan.'
                        ),
                        'subscription_required': True,
                    }
                else:
                    consume_user_entitlement(request.user, cost=1)
                    # Decide identifier type by prefix
                    phone_prefixes = ('070', '080', '081', '090', '091', '071', '091')
                    if digits_only[:3] in phone_prefixes:
                        query_type = 'phone'
                        id_type    = 'phone'
                    else:
                        query_type = 'nin'
                        id_type    = 'nin'

                # Compute peppered HMAC-SHA256 digest matching identities database
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

                if ident is None:
                    result = {
                        'found':      False,
                        'query':      raw_query,
                        'query_type': query_type,
                    }
                else:
                    subject = ident.subject

                    # Trust score (OneToOne relation on SubjectEntity)
                    trust_score = getattr(subject, 'trust_score', None)

                    # Published fraud reports only — never raw allegations
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
        'profile':    profile,
        'result':     result,
        'query':      query,
        'page_title': 'Person Quick-Check',
    }
    return render(request, 'employer/person_check.html', context)


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



