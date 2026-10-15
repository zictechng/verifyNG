from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.views.generic import TemplateView

from reports.models import FraudReport, Dispute
from verification.models import VerificationRequest
from core.permissions import is_moderator, is_verification_officer
from verification.models import VerificationRequest, VerificationCertificate

# ── Add to top imports ────────────────────────────────────────────────────────
import hashlib
from django.views.generic import FormView
from django import forms as django_forms

from employer.models import StaffCheckRequest, EmployerProfile


# ─── Reusable helpers ────────────────────────────────────────────────────────

def _paginate(request, queryset, per_page=10, param="page"):
    """
    Reusable pagination helper.
    Returns a Page object for the given queryset.
    Uses distinct query-param names so multiple paginators on one page don't
    interfere: pass param='rpage' for reports, param='vpage' for verifications, etc.
    """
    paginator = Paginator(queryset, per_page)
    page_number = request.GET.get(param, 1)
    try:
        return paginator.page(page_number)
    except PageNotAnInteger:
        return paginator.page(1)
    except EmptyPage:
        return paginator.page(paginator.num_pages)


def _get_staff_context(user):
    """
    Returns moderator / officer queue counters for privileged users.
    Isolated so the logic is reusable across any view that needs it
    (dashboard, admin portal, etc.) without duplicating queries.
    """
    ctx = {
        "is_moderator": is_moderator(user),
        "is_officer": is_verification_officer(user) or user.is_superuser,
        "pending_moderation_count": 0,
        "open_disputes_count": 0,
        "pending_verification_count": 0,
    }
    if ctx["is_moderator"]:
        ctx["pending_moderation_count"] = FraudReport.objects.filter(
            state__in=["submitted", "under_review"]
        ).count()
        ctx["open_disputes_count"] = Dispute.objects.filter(
            status__in=["opened", "under_review"]
        ).count()
    if ctx["is_officer"]:
        ctx["pending_verification_count"] = VerificationRequest.objects.filter(
            status__in=["pending", "in_progress"]
        ).count()
    return ctx


def _get_user_summary_counts(user):
    """
    Returns summary stat counts for the dashboard stat strip.
    Kept separate so the numbers can be reused in a future API or widget
    without re-fetching the full queryset.
    """
    return {
        "total_reports": FraudReport.objects.filter(reporter=user).count(),
        "total_verifications": VerificationRequest.objects.filter(requester=user).count(),
        "total_disputes": Dispute.objects.filter(disputant=user).count(),
        "completed_verifications": VerificationRequest.objects.filter(
            requester=user, status="completed"
        ).count(),
    }


# ─── Views ───────────────────────────────────────────────────────────────────

class DashboardIndexView(LoginRequiredMixin, TemplateView):
    template_name = "dashboard/index.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user

        # Paginated querysets — each uses its own page param
        reports_qs = (
            FraudReport.objects.filter(reporter=user)
            .select_related("target_subject")
            .order_by("-created_at")
        )
        verifications_qs = (
            VerificationRequest.objects.filter(requester=user)
            .select_related("target_subject")
            .prefetch_related("result")
            .order_by("-created_at")
        )
        disputes_qs = (
            Dispute.objects.filter(disputant=user)
            .select_related("report", "report__target_subject")
            .order_by("-created_at")
        )

        ctx["user_reports"] = _paginate(self.request, reports_qs, per_page=10, param="rpage")
        ctx["user_verifications"] = _paginate(self.request, verifications_qs, per_page=10, param="vpage")
        ctx["user_disputes"] = _paginate(self.request, disputes_qs, per_page=5, param="dpage")
        
        # User's certificates (most recent 5 for dashboard preview)
        ctx['user_certificates'] = (
            VerificationCertificate.objects
            .filter(holder=user)
            .select_related('subject')
            .order_by('-created_at')[:5]
        )
        # Summary stat strip
        ctx.update(_get_user_summary_counts(user))

        # Staff/officer context
        ctx.update(_get_staff_context(user))

        return ctx


class WhoCheckedMeForm(django_forms.Form):
    nin = django_forms.CharField(
        label='Your NIN (11 digits)',
        max_length=11,
        min_length=11,
        widget=django_forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '12345678901',
            'autocomplete': 'off',
            'inputmode': 'numeric',
            'pattern': r'\d{11}',
        }),
        error_messages={
            'required': 'Please enter your NIN.',
            'min_length': 'NIN must be exactly 11 digits.',
            'max_length': 'NIN must be exactly 11 digits.',
        }
    )

    def clean_nin(self):
        nin = self.cleaned_data['nin'].strip()
        if not nin.isdigit() or len(nin) != 11:
            raise django_forms.ValidationError('NIN must be exactly 11 digits (numbers only).')
        return nin


class WhoCheckedMeView(LoginRequiredMixin, FormView):
    """
    Lets a worker enter their NIN to see which employers ran a background
    check against them via StaffCheckRequest.
    NIN is hashed server-side; raw NIN is never stored or logged.
    """
    template_name = 'dashboard/who_checked_me.html'
    form_class = WhoCheckedMeForm

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['checked_by'] = None   # results not shown until form submitted
        return ctx

    def form_valid(self, form):
        raw_nin = form.cleaned_data['nin']
        # Hash the NIN exactly as the employer side does
        nin_hash = hashlib.sha256(raw_nin.encode('utf-8')).hexdigest()

        checks = (
            StaffCheckRequest.objects
            .filter(nin_hash=nin_hash, is_active=True)
            .select_related('employer')
            .order_by('-created_at')
        )

        # Build a privacy-safe result set — omit result_data / result_summary
        results = [
            {
                'company_name': c.employer.company_name,
                'industry':     c.employer.industry,
                'check_type':   c.get_check_type_display(),
                'purpose':      c.purpose or '—',
                'date':         c.created_at,
                'status':       c.get_status_display(),
            }
            for c in checks
        ]

        return self.render_to_response(self.get_context_data(
            form=form,
            checked_by=results,
            nin_last4=f"****{raw_nin[-4:]}",
        ))



