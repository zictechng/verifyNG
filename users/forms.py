from django import forms
from django.contrib.auth.forms import (
    UserCreationForm,
    AuthenticationForm,
    PasswordResetForm,
    SetPasswordForm,
    PasswordChangeForm,  
)
from users.models import User
from employer.models import EmployerProfile

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

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                "An account with this email address already exists. "
                "Please sign in or use a different email."
            )
        return email

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
    Password reset form with Bootstrap styling.
    Overrides send_mail so password-reset emails go through render_email()
    and the Celery three-gate mailer instead of Django's default EmailMessage.
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
        from core.email_utils import render_email
        from core.models import SiteConfiguration
        from notifications.tasks import send_broadcast_email_task

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


class EmployerRegistrationForm(UserCreationForm):
    """
    Registration form for employer accounts.
    Collects company name in addition to standard fields.
    Role is forced to 'employer' server-side — never trust client input.
    """
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Company email address',
        }),
    )
    first_name = forms.CharField(
        max_length=150,
        required=True,
        label='Your First Name',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Contact first name',
        }),
    )
    last_name = forms.CharField(
        max_length=150,
        required=False,
        label='Your Last Name',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Contact last name',
        }),
    )
    company_name = forms.CharField(
        max_length=200,
        required=True,
        label='Company / Organisation Name',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g. Acme Nigeria Limited',
        }),
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'email', 'first_name', 'last_name', 'company_name')
        widgets = {
            'username': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Choose a username',
            }),
        }

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                "An account with this email already exists. Sign in or use a different email."
            )
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        user.first_name = self.cleaned_data.get('first_name', '')
        user.last_name = self.cleaned_data.get('last_name', '')
        user.role = 'employer'   # forced — never trust client
        if commit:
            user.save()
            # Create the EmployerProfile automatically on signup
            try:
                from employer.models import EmployerProfile
                EmployerProfile.objects.get_or_create(
                    user=user,
                    defaults={'company_name': self.cleaned_data.get('company_name', '')},
                )
            except Exception:
                pass
        return user


class AgencyRegistrationForm(UserCreationForm):
    """
    Registration form for security / authorized agency accounts.
    Role forced to 'agency' server-side.
    """
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Agency email address',
        }),
    )
    first_name = forms.CharField(
        max_length=150,
        required=True,
        label='Contact First Name',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'First name',
        }),
    )
    last_name = forms.CharField(
        max_length=150,
        required=False,
        label='Contact Last Name',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Last name',
        }),
    )
    agency_name = forms.CharField(
        max_length=200,
        required=True,
        label='Agency / Organisation Name',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g. Secure Guard Nigeria Ltd',
        }),
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'email', 'first_name', 'last_name', 'agency_name')
        widgets = {
            'username': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Choose a username',
            }),
        }

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                "An account with this email already exists. Sign in or use a different email."
            )
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        user.first_name = self.cleaned_data.get('first_name', '')
        user.last_name = self.cleaned_data.get('last_name', '')
        user.role = 'agency'   # forced — never trust client
        if commit:
            user.save()
        # Auto-provision organization profile on agency registration
            try:
                EmployerProfile.objects.get_or_create(
                    user=user,
                    defaults={'company_name': self.cleaned_data.get('agency_name', '')},
                )
            except Exception:
                pass
        return user


