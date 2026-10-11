from django.shortcuts import render
from django.http import HttpResponse
from core.rate_limiting import check_rate_limit
from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView
from notifications.tasks import send_broadcast_email_task
import logging

from django.contrib.auth.views import (
    LoginView,
    LogoutView,
    PasswordResetView,
    PasswordResetDoneView,
    PasswordResetConfirmView,
    PasswordResetCompleteView,
    PasswordChangeView,
)
from django.contrib.auth.mixins import LoginRequiredMixin

from users.forms import (
    CustomUserCreationForm,
    CustomAuthenticationForm,
    CustomPasswordResetForm,
    CustomSetPasswordForm,
    CustomPasswordChangeForm,
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
                status=429
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


# --- Password Reset Flow (unauthenticated — forgot password) ---

class CustomPasswordResetView(PasswordResetView):
    template_name = 'users/password_reset_form.html'
    email_template_name = 'users/password_reset_email.html'
    subject_template_name = 'users/password_reset_subject.txt'
    success_url = reverse_lazy('users:password_reset_done')
    form_class = CustomPasswordResetForm


class CustomPasswordResetDoneView(PasswordResetDoneView):
    template_name = 'users/password_reset_done.html'


class CustomPasswordResetConfirmView(PasswordResetConfirmView):
    template_name = 'users/password_reset_confirm.html'
    success_url = reverse_lazy('users:password_reset_complete')
    form_class = CustomSetPasswordForm

    def form_valid(self, form):
        response = super().form_valid(form)
        user = form.user
        send_broadcast_email_task.delay(
            to_email=user.email,
            subject='Your VerifyNG password has been changed',
            html_body=(
                f"<p>Hello {user.first_name or user.username},</p>"
                "<p>Your VerifyNG account password was successfully changed.</p>"
                "<p>If you did not make this change, please contact us immediately at "
                "<a href='mailto:support@verifyng.com'>support@verifyng.com</a>.</p>"
                "<p>— The VerifyNG Team</p>"
            ),
            text_body=(
                f"Hello {user.first_name or user.username},\n\n"
                "Your VerifyNG account password was successfully changed.\n\n"
                "If you did not make this change, contact us at support@verifyng.com.\n\n"
                "— The VerifyNG Team"
            ),
        )
        return response


class CustomPasswordResetCompleteView(PasswordResetCompleteView):
    template_name = 'users/password_reset_complete.html'


# --- Password Change (authenticated — inside portal) ---

class CustomPasswordChangeView(LoginRequiredMixin, PasswordChangeView):
    """
    In-portal password change for all authenticated user roles.
    Requires current password. Sends security notification email via Celery.
    """
    template_name = 'users/password_change_form.html'
    form_class = CustomPasswordChangeForm
    success_url = reverse_lazy('users:password_change_done')

    def form_valid(self, form):
        response = super().form_valid(form)
        user = self.request.user
        send_broadcast_email_task.delay(
            to_email=user.email,
            subject='Your VerifyNG password has been changed',
            html_body=(
                f"<p>Hello {user.first_name or user.username},</p>"
                "<p>Your VerifyNG account password was just changed from inside your portal.</p>"
                "<p>If you did not make this change, please contact us immediately at "
                "<a href='mailto:support@verifyng.com'>support@verifyng.com</a>.</p>"
                "<p>— The VerifyNG Team</p>"
            ),
            text_body=(
                f"Hello {user.first_name or user.username},\n\n"
                "Your VerifyNG account password was just changed from inside your portal.\n\n"
                "If you did not make this change, contact us at support@verifyng.com.\n\n"
                "— The VerifyNG Team"
            ),
        )
        return response

