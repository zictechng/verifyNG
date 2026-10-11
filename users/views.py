import logging

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import (
    LoginView,
    LogoutView,
    PasswordChangeView,
    PasswordResetView,
    PasswordResetDoneView,
    PasswordResetConfirmView,
    PasswordResetCompleteView,
)
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse_lazy
from django.utils.timezone import localtime, now
from django.views.generic import CreateView, DetailView

from core.email_utils import render_email
from core.models import SiteConfiguration
from core.rate_limiting import check_rate_limit
from notifications.tasks import send_broadcast_email_task
from users.forms import (
    CustomAuthenticationForm,
    CustomPasswordChangeForm,
    CustomPasswordResetForm,
    CustomSetPasswordForm,
    CustomUserCreationForm,
)
from users.models import User

logger = logging.getLogger(__name__)


class RegisterView(CreateView):
    """
    Public registration view. Uses CustomUserCreationForm to register individual users.
    """
    form_class = CustomUserCreationForm
    template_name = 'users/register.html'
    success_url = reverse_lazy('users:login')


class UserLoginView(LoginView):
    """
    Standard authentication login view.
    Rate limited: max 10 login attempts per IP per 15 minutes.
    """
    form_class = CustomAuthenticationForm
    template_name = 'users/login.html'

    def dispatch(self, request, *args, **kwargs):
        is_limited, retry_after = check_rate_limit(
            request, namespace='login', limit=10, window=900
        )
        if is_limited:
            return HttpResponse(
                "Too many login attempts. Please wait 15 minutes before trying again.",
                status=429,
            )
        return super().dispatch(request, *args, **kwargs)


class UserLogoutView(LogoutView):
    """
    POST-based logout view redirecting to login.
    """
    next_page = reverse_lazy('users:login')


class UserProfileView(LoginRequiredMixin, DetailView):
    """
    Authenticated user profile view.
    Strictly forces the object to be request.user so users cannot view other profiles.
    """
    model = User
    template_name = 'users/profile.html'
    context_object_name = 'user_profile'

    def get_object(self, queryset=None):
        return self.request.user


# ── Password Reset Flow ───────────────────────────────────────────────────────

class CustomPasswordResetView(PasswordResetView):
    """
    Sends a branded password-reset email using the emails/password_reset.html template.
    Django's built-in PasswordResetView renders email_template_name using its own
    context (uid, token, domain, protocol). We override send_mail to intercept and
    route through render_email() + Celery.
    """
    template_name = 'users/password_reset_form.html'
    email_template_name = 'users/password_reset_email.html'   # kept for Django's text fallback
    subject_template_name = 'users/password_reset_subject.txt'
    success_url = reverse_lazy('users:password_reset_done')
    form_class = CustomPasswordResetForm
    html_email_template_name = 'emails/password_reset.html'   # new styled HTML template

    def send_mail(self, subject_template_name, email_template_name, context,
                  from_email, to_email, html_email_template_name=None):
        """
        Override to inject site config and send via the three-gate Celery task.
        """
        config = SiteConfiguration.get_solo()
        uid = context.get('uid', '')
        token = context.get('token', '')
        protocol = context.get('protocol', 'https')
        domain = context.get('domain', config.base_url.replace('https://', '').replace('http://', ''))
        reset_url = f"{protocol}://{domain}/users/password-reset/confirm/{uid}/{token}/"

        user_obj = context.get('user')
        user_name = ''
        if user_obj:
            user_name = user_obj.first_name or user_obj.username

        html_body, text_body = render_email('password_reset', {
            'user_name': user_name,
            'reset_url': reset_url,
        })

        send_broadcast_email_task.delay(
            to_email=to_email,
            subject=f'Reset your {config.site_name} password',
            html_body=html_body,
            text_body=text_body,
        )


class CustomPasswordResetDoneView(PasswordResetDoneView):
    template_name = 'users/password_reset_done.html'


class CustomPasswordResetConfirmView(PasswordResetConfirmView):
    template_name = 'users/password_reset_confirm.html'
    success_url = reverse_lazy('users:password_reset_complete')
    form_class = CustomSetPasswordForm

    def form_valid(self, form):
        response = super().form_valid(form)
        user = form.user
        config = SiteConfiguration.get_solo()
        try:
            html_body, text_body = render_email('password_changed', {
                'user_name': user.first_name or user.username,
                'changed_at': localtime(now()).strftime('%d %b %Y, %I:%M %p'),
            })
            send_broadcast_email_task.delay(
                to_email=user.email,
                subject=f'Your {config.site_name} password has been changed',
                html_body=html_body,
                text_body=text_body,
            )
        except Exception:
            logger.exception(
                "Failed to send password-change confirmation email to user %s", user.pk
            )
        return response


class CustomPasswordResetCompleteView(PasswordResetCompleteView):
    template_name = 'users/password_reset_complete.html'


# ── Password Change (logged-in portal) ───────────────────────────────────────

class CustomPasswordChangeView(LoginRequiredMixin, PasswordChangeView):
    """
    Allows an authenticated user to change their own password from inside the portal.
    Sends a branded security notification email via Celery on success.
    """
    template_name = 'users/password_change_form.html'
    form_class = CustomPasswordChangeForm
    success_url = reverse_lazy('users:password_change_done')

    def form_valid(self, form):
        response = super().form_valid(form)
        user = self.request.user
        config = SiteConfiguration.get_solo()
        try:
            html_body, text_body = render_email('password_changed', {
                'user_name': user.first_name or user.username,
                'changed_at': localtime(now()).strftime('%d %b %Y, %I:%M %p'),
            })
            send_broadcast_email_task.delay(
                to_email=user.email,
                subject=f'Your {config.site_name} password has been changed',
                html_body=html_body,
                text_body=text_body,
            )
        except Exception:
            logger.exception(
                "Failed to send password-change confirmation email to user %s", user.pk
            )
        return response
