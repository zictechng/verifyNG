

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

