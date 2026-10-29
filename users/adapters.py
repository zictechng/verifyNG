import logging
from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings
from django.shortcuts import resolve_url
from django.urls import reverse
from core.permissions import get_user_home_url, is_employer, is_admin_or_subadmin

logger = logging.getLogger(__name__)


class CustomAccountAdapter(DefaultAccountAdapter):
    """
    VerifyNG account adapter.
    Dynamically routes logged-in users to their respective portals based on their RBAC role.
    """
    def get_login_redirect_url(self, request) -> str:
        user = request.user
        next_url = request.POST.get('next') or request.GET.get('next')
        if next_url:
            if is_admin_or_subadmin(user):
                if next_url.rstrip('/') in ('', '/dashboard', '/users/profile') or not next_url.startswith('/admin-portal'):
                    return reverse('admin_portal:overview')
                return next_url
            if is_employer(user) and next_url.rstrip('/') in ('/dashboard', '/users/profile'):
                return reverse('employer:dashboard')
            return next_url

        try:
            return reverse(get_user_home_url(user))
        except Exception:
            return resolve_url(settings.LOGIN_REDIRECT_URL)


class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    """
    VerifyNG social account adapter for Google OAuth.
    Ensures safe onboarding:
    - Respects intended signup role ('employer', 'agency', or 'individual') from session.
    - Always initializes KYC status as unverified ('unverified').
    - Auto-initializes minimal EmployerProfile if role is employer/agency.
    """
    def populate_user(self, request, sociallogin, data):
        user = super().populate_user(request, sociallogin, data)
        if not user.pk:
            role_intent = request.session.pop('oauth_role_intent', 'individual') if hasattr(request, 'session') else 'individual'
            if role_intent in ('employer', 'agency', 'individual'):
                user.role = role_intent
            else:
                user.role = 'individual'
            user.id_status = 'unverified'
        return user

    def save_user(self, request, sociallogin, form=None):
        user = super().save_user(request, sociallogin, form)
        if user.role in ('employer', 'agency'):
            try:
                from employer.models import EmployerProfile
                if not EmployerProfile.objects.filter(user=user).exists():
                    company_name = (
                        sociallogin.account.extra_data.get('name')
                        or user.get_full_name()
                        or user.username
                    )
                    EmployerProfile.objects.create(
                        user=user,
                        company_name=company_name,
                        contact_phone='',
                    )
            except Exception as e:
                logger.error("Failed to auto-create EmployerProfile on social signup: %s", e)
        return user

    def on_authentication_error(self, request, provider, error=None, exception=None, extra_context=None):
        logger.warning(
            "Social authentication error for provider %s: error=%s exception=%s",
            getattr(provider, 'id', provider),
            error,
            exception,
        )
        super().on_authentication_error(
            request, provider, error=error, exception=exception, extra_context=extra_context
        )
