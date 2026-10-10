from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView
from reports.models import FraudReport, Dispute
from verification.models import VerificationRequest
from core.permissions import is_moderator, is_verification_officer


class DashboardIndexView(LoginRequiredMixin, TemplateView):
    template_name = "dashboard/index.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user

        # User's submitted reports and filed disputes
        ctx['user_reports'] = (
            FraudReport.objects.filter(reporter=user)
            .select_related('target_subject')
            .order_by('-created_at')[:10]
        )
        ctx['user_disputes'] = (
            Dispute.objects.filter(disputant=user)
            .select_related('report', 'report__target_subject')
            .order_by('-created_at')[:10]
        )
        ctx['user_verifications'] = (
            VerificationRequest.objects.filter(requester=user)
            .select_related('target_subject')
            .prefetch_related('result')
            .order_by('-created_at')[:10]
        )

        # Moderator queue counters
        ctx['is_moderator'] = is_moderator(user)
        if ctx['is_moderator']:
            ctx['pending_moderation_count'] = FraudReport.objects.filter(
                state__in=['submitted', 'under_review']
            ).count()
            ctx['open_disputes_count'] = Dispute.objects.filter(
                status__in=['opened', 'under_review']
            ).count()

        # Verification Officer queue counter
        ctx['is_officer'] = is_verification_officer(user) or user.is_superuser
        if ctx['is_officer']:
            ctx['pending_verification_count'] = VerificationRequest.objects.filter(
                status__in=['pending', 'in_progress']
            ).count()

        return ctx

