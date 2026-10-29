from django.urls import path
from users.views import (
    LegalNameChangeRequestView,
    RegisterView,
    RegisterLandingView,
    EmployerRegisterView,
    AgencyRegisterView,
    UserLoginView,
    UserLogoutView,
    UserProfileView,
    AccountHubView,
    UserProfileUpdateView,
    DeleteAccountView,
    UserIdentityVerificationSubmitView,
    UserIdentityDocumentView,
    CustomPasswordResetView,
    CustomPasswordResetDoneView,
    CustomPasswordResetConfirmView,
    CustomPasswordResetCompleteView,
    CustomPasswordChangeView,
    oauth_google_login,
    RegisterCompanyView,
)
from django.contrib.auth.views import PasswordChangeDoneView
from django.views.generic import TemplateView

app_name = 'users'

urlpatterns = [
    # Registration — landing + role-specific
    path('register/', RegisterLandingView.as_view(), name='register_landing'),
    path('register/individual/', RegisterView.as_view(), name='register'),
    path('register/employer/', EmployerRegisterView.as_view(), name='register_employer'),
    path('register/agency/', AgencyRegisterView.as_view(), name='register_agency'),
    path('register/company/', RegisterCompanyView.as_view(), name='register_company'),
    path('oauth/google/', oauth_google_login, name='oauth_google_login'),

    path('login/', UserLoginView.as_view(), name='login'),
    path('logout/', UserLogoutView.as_view(), name='logout'),
    path('account/', AccountHubView.as_view(), name='account_hub'),
    path('profile/', UserProfileUpdateView.as_view(), name='profile'),
    path('profile/legal-name-change/', LegalNameChangeRequestView.as_view(), name='legal_name_change_request'),
    path('profile/verify-identity/', UserIdentityVerificationSubmitView.as_view(), name='verify_identity_submit'),
    path('profile/id-document/', UserIdentityDocumentView.as_view(), name='id_document_preview'),
    path('delete-account/', DeleteAccountView.as_view(), name='delete_account'),
    path(
        'suspended/',
        TemplateView.as_view(template_name='users/account_suspended.html'),
        name='account_suspended',
    ),

    # Password Reset (unauthenticated — forgot password)
    path('password-reset/', CustomPasswordResetView.as_view(), name='password_reset'),
    path('password-reset/done/', CustomPasswordResetDoneView.as_view(), name='password_reset_done'),
    path('password-reset/confirm/<uidb64>/<token>/', CustomPasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('password-reset/complete/', CustomPasswordResetCompleteView.as_view(), name='password_reset_complete'),

    # Password Change (authenticated — inside portal)
    path('password-change/', CustomPasswordChangeView.as_view(), name='password_change'),
    path('password-change/done/', PasswordChangeDoneView.as_view(
        template_name='users/password_change_done.html'
    ), name='password_change_done'),
]


