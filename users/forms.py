from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from users.models import User


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
