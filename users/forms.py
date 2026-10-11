from django import forms
from django.contrib.auth.forms import (
    UserCreationForm,
    AuthenticationForm,
    PasswordResetForm,
    SetPasswordForm,
    PasswordChangeForm,  
)
from users.models import User

from core.email_utils import render_email
from core.models import SiteConfiguration
from notifications.tasks import send_broadcast_email_task

class CustomUserCreationForm(UserCreationForm):
    """
    Form for public user registration.
    Enforces required email validation and forces role assignment to 'individual'.
    """
    email = forms.EmailField(
        required=True,
        help_text="Required. Enter a valid email address."
    )
    first_name = forms.CharField(
        max_length=150,
        required=False,
        help_text="Optional."
    )
    last_name = forms.CharField(
        max_length=150,
        required=False,
        help_text="Optional."
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'email', 'first_name', 'last_name')

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        user.first_name = self.cleaned_data.get('first_name', '')
        user.last_name = self.cleaned_data.get('last_name', '')
        # Force 'individual' role on server side, ignoring any tampered inputs
        user.role = 'individual'
        if commit:
            user.save()
        return user


class CustomAuthenticationForm(AuthenticationForm):
    """
    Standard login form customizing widget placeholders for username/password login.
    """
    username = forms.CharField(
        widget=forms.TextInput(attrs={'placeholder': 'Username', 'class': 'form-control'})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'placeholder': 'Password', 'class': 'form-control'})
    )


class CustomPasswordResetForm(PasswordResetForm):
    """
    Password reset form with Bootstrap styling applied to the email widget.
    """
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your registered email address',
            'autocomplete': 'email',
        })
    )

    def send_mail(self, subject_template_name, email_template_name, context,
                  from_email, to_email, html_email_template_name=None):

        config = SiteConfiguration.get_solo()
        uid = context.get('uid', '')
        token = context.get('token', '')
        protocol = context.get('protocol', 'https')
        domain = context.get('domain', '')
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


class CustomSetPasswordForm(SetPasswordForm):
    """
    Set-password form (used on the reset confirm page) with Bootstrap styling
    applied to both password widgets.
    """
    new_password1 = forms.CharField(
        label='New Password',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter a strong new password',
            'autocomplete': 'new-password',
        }),
        strip=False,
    )
    new_password2 = forms.CharField(
        label='Confirm New Password',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Repeat your new password',
            'autocomplete': 'new-password',
        }),
        strip=False,
    )

class CustomPasswordChangeForm(PasswordChangeForm):
    """
    In-portal change-password form with Bootstrap styling on all three widgets.
    Requires the user's current (old) password before accepting a new one.
    """
    old_password = forms.CharField(
        label='Current Password',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your current password',
            'autocomplete': 'current-password',
        }),
        strip=False,
    )
    new_password1 = forms.CharField(
        label='New Password',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter a strong new password',
            'autocomplete': 'new-password',
        }),
        strip=False,
    )
    new_password2 = forms.CharField(
        label='Confirm New Password',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Repeat your new password',
            'autocomplete': 'new-password',
        }),
        strip=False,
    )
