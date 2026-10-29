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
    Ensures safe onboarding: new users always enter as unverified 'individual' role
    and must complete standard KYC/CAC verification before accessing employer or sensitive services.
    """
    def populate_user(self, request, sociallogin, data):
        user = super().populate_user(request, sociallogin, data)
        # Always enforce individual role and unverified KYC status for new social signups
        if not user.pk:
            user.role = 'individual'
            user.id_status = 'unverified'
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
