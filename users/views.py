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
from django.views.generic import CreateView, DetailView, View

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.http import HttpResponseRedirect
from django.urls import reverse_lazy

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
    Also passes email notification preferences so they render on the same page.
    """
    template_name = 'users/password_change_form.html'
    form_class = CustomPasswordChangeForm
    success_url = reverse_lazy('users:password_change_done')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from notifications.models import NotificationPreference
        context['prefs'] = NotificationPreference.for_user(self.request.user)
        context['prefs_fields'] = [
            ('email_report_submitted', 'Fraud report received'),
            ('email_report_published', 'Report published'),
            ('email_report_rejected', 'Report rejected'),
            ('email_dispute_opened', 'Dispute filed on my report'),
            ('email_dispute_resolved', 'Dispute resolved'),
            ('email_verification_completed', 'Verification completed'),
            ('email_verification_rejected', 'Verification rejected'),
            ('email_broadcast', 'Platform announcements'),
        ]
        return context

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
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from notifications.models import NotificationPreference
        prefs, _ = NotificationPreference.objects.get_or_create(user=self.request.user)
        context['prefs'] = prefs
        context['prefs_fields'] = [
            ('email_on_report_submitted', 'Report submitted'),
            ('email_on_report_published', 'Report published'),
            ('email_on_report_rejected', 'Report rejected'),
            ('email_on_dispute_opened', 'Dispute opened'),
            ('email_on_dispute_resolved', 'Dispute resolved'),
            ('email_on_verification_completed', 'Verification completed'),
        ]
        return context


class UserProfileUpdateView(LoginRequiredMixin, View):
    """
    Allows authenticated users to update first_name, last_name, and email.
    Username and role are read-only.
    """
    template_name = 'users/profile.html'

    def get(self, request):
        from django import forms as dj_forms

        class ProfileForm(dj_forms.ModelForm):
            class Meta:
                model = User
                fields = ['first_name', 'last_name', 'email']
                widgets = {
                    'first_name': dj_forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'First name'}),
                    'last_name': dj_forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Last name'}),
                    'email': dj_forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'email@example.com'}),
                }

        form = ProfileForm(instance=request.user)
        return render(request, self.template_name, {'form': form, 'user_profile': request.user})

    def post(self, request):
        from django import forms as dj_forms

        class ProfileForm(dj_forms.ModelForm):
            class Meta:
                model = User
                fields = ['first_name', 'last_name', 'email']
                widgets = {
                    'first_name': dj_forms.TextInput(attrs={'class': 'form-control'}),
                    'last_name': dj_forms.TextInput(attrs={'class': 'form-control'}),
                    'email': dj_forms.EmailInput(attrs={'class': 'form-control'}),
                }

        form = ProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Profile updated successfully.')
            return HttpResponseRedirect(reverse_lazy('users:profile'))
        return render(request, self.template_name, {'form': form, 'user_profile': request.user})


class DeleteAccountView(LoginRequiredMixin, View):
    """
    Requires password confirmation and checkbox before permanently deleting the account.
    Soft-deletes by deactivating (is_active=False) rather than hard-deleting,
    preserving fraud report integrity per CLAUDE.md data retention requirements.
    """
    template_name = 'users/delete_account.html'

    def get(self, request):
        return render(request, self.template_name)

    def post(self, request):
        password = request.POST.get('password', '')
        confirmed = request.POST.get('confirm_delete') == 'on'

        if not confirmed:
            messages.error(request, 'You must check the confirmation box.')
            return render(request, self.template_name)

        if not request.user.check_password(password):
            messages.error(request, 'Incorrect password. Please try again.')
            return render(request, self.template_name)

        # Soft delete — deactivate account, preserve fraud report data
        user = request.user
        user.is_active = False
        user.save(update_fields=['is_active'])

        from django.contrib.auth import logout
        logout(request)
        messages.success(request, 'Your account has been deleted.')
        return HttpResponseRedirect(reverse_lazy('home'))


