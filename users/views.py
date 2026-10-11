from django.shortcuts import render
from django.http import HttpResponse
from core.rate_limiting import check_rate_limit
from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView
from django.contrib.auth.views import (
    LoginView,
    LogoutView,
    PasswordResetView,
    PasswordResetDoneView,
    PasswordResetConfirmView,
    PasswordResetCompleteView,
)
from django.contrib.auth.mixins import LoginRequiredMixin

from users.forms import CustomUserCreationForm, CustomAuthenticationForm
from users.models import User


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
                "Too many login attempts. Please wait 15 minutes before trying again."
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


# --- Password Reset Flow Views ---

class CustomPasswordResetView(PasswordResetView):
    template_name = 'users/password_reset_form.html'
    email_template_name = 'users/password_reset_email.html'
    subject_template_name = 'users/password_reset_subject.txt'
    success_url = reverse_lazy('users:password_reset_done')


class CustomPasswordResetDoneView(PasswordResetDoneView):
    template_name = 'users/password_reset_done.html'


class CustomPasswordResetConfirmView(PasswordResetConfirmView):
    template_name = 'users/password_reset_confirm.html'
    success_url = reverse_lazy('users:password_reset_complete')


class CustomPasswordResetCompleteView(PasswordResetCompleteView):
    template_name = 'users/password_reset_complete.html'
