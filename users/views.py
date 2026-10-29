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
from django.shortcuts import render, redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.timezone import localtime, now
from django.views.generic import CreateView, DetailView, TemplateView, View, FormView
from django.urls import reverse

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.http import HttpResponseRedirect
from django.urls import reverse_lazy
from django import forms as dj_forms
import secrets
from django.core.files.storage import default_storage
import os
import re
import mimetypes
from django.http import Http404
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.utils.decorators import method_decorator
from reports.models import AuditLog

from core.email_utils import render_email
from core.models import SiteConfiguration
from core.rate_limiting import check_rate_limit, get_client_ip
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
    Public registration view. Sends a branded welcome email via Celery on success.
    """
    form_class = CustomUserCreationForm
    template_name = 'users/register.html'
    success_url = reverse_lazy('users:login')

    def form_valid(self, form):
        response = super().form_valid(form)
        user = self.object
        try:
            html_body, text_body = render_email('generic_notification', {
                'user_name': user.get_full_name() or user.username,
                'heading': 'Welcome to VerifyNG!',
                'body_html': (
                    f'<p>Your VerifyNG account has been created successfully. '
                    f'You can now sign in and start using the platform.</p>'
                    f'<p>Your username is: <strong>{user.username}</strong></p>'
                    f'<p>If you did not create this account, please contact us immediately.</p>'
                ),
                'subject': 'Welcome to VerifyNG — Your account is ready',
            })
            send_broadcast_email_task.delay(
                to_email=user.email,
                subject='Welcome to VerifyNG — Your account is ready',
                html_body=html_body,
                text_body=text_body,
            )
        except Exception:
            logger.warning("Failed to send welcome email to new user %s", user.pk)

        messages.success(
            self.request,
            f'Account created! Welcome, {user.get_full_name() or user.username}. Please sign in.'
        )
        return response

class UserLoginView(LoginView):
    """
    Standard authentication login view.
    Rate limited: max 10 login attempts per IP per 15 minutes.
    Routes each role to their correct portal on login.
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

    def get_success_url(self):
        """Route to the correct portal based on user role."""
        user = self.request.user
        redirect_to = self.get_redirect_url()
        from core.permissions import get_user_home_url, is_employer, is_admin_or_subadmin

        if redirect_to:
            # If an admin or sub-admin user was redirected with next pointing to candidate dashboard/profile, root, or non-admin URLs,
            # reroute them directly to the admin portal overview.
            if is_admin_or_subadmin(user):
                if redirect_to.rstrip('/') in ('', '/dashboard', '/users/profile') or not redirect_to.startswith('/admin-portal'):
                    return reverse('admin_portal:overview')
                return redirect_to

            # If an employer/agency/business user was redirected with next pointing to candidate dashboard/profile,
            # reroute them to their appropriate employer portal instead.
            if is_employer(user) and redirect_to.rstrip('/') in ('/dashboard', '/users/profile'):
                return reverse('employer:dashboard')
            return redirect_to

        return reverse(get_user_home_url(user))


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

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            from core.permissions import is_admin_or_subadmin
            if is_admin_or_subadmin(request.user):
                return redirect('admin_portal:profile')
        return super().dispatch(request, *args, **kwargs)

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

class AccountHubView(LoginRequiredMixin, TemplateView):
    """
    Mobile-first Account & Settings Hub inspired by modern digital identity apps.
    Serves Individual, Employer, Agency, and Business accounts with single-touch navigation.
    Desktop access is redirected to the role-specific dashboard.
    """
    template_name = 'users/account_hub.html'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)

        # Account Hub is exclusively designed for mobile & tablet interfaces.
        # Detect User-Agent and redirect desktop users to their role-specific dashboard.
        user_agent = request.META.get('HTTP_USER_AGENT', '').lower()
        mobile_keywords = (
            'mobile', 'android', 'iphone', 'ipad', 'ipod', 'tablet',
            'silk/', 'kindle', 'opera mini', 'blackberry', 'touch', 'iemobile'
        )
        is_mobile = any(k in user_agent for k in mobile_keywords)

        if not is_mobile and request.GET.get('view') != 'mobile':
            user = request.user
            if getattr(user, 'role', '') in ('employer', 'agency', 'business'):
                return redirect('employer:dashboard')
            elif user.is_staff or getattr(user, 'role', '') in ('moderator', 'officer'):
                return redirect('admin_portal:overview')
            else:
                return redirect('dashboard:index')

        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        employer_profile = None
        if hasattr(user, 'employer_profile'):
            employer_profile = user.employer_profile
        elif user.employer_memberships.filter(is_active=True).exists():
            employer_profile = user.employer_memberships.filter(is_active=True).first().employer
        ctx['employer_profile'] = employer_profile
        return ctx

class UserProfileUpdateView(LoginRequiredMixin, View):
    """
    Allows authenticated users to update first_name, last_name, and email.
    Username and role are read-only.
    """
    template_name = 'users/profile.html'

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            from core.permissions import is_admin_or_subadmin
            if is_admin_or_subadmin(request.user):
                return redirect('admin_portal:profile')
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
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
            # If identity is verified, strictly preserve legal first and last name from tampering
            if request.user.identity_verified:
                form.instance.first_name = request.user.first_name
                form.instance.last_name = request.user.last_name

            form.save()
            messages.success(request, 'Profile updated successfully.')
            return HttpResponseRedirect(reverse_lazy('users:profile'))
        return render(request, self.template_name, {'form': form, 'user_profile': request.user})



class LegalNameChangeRequestView(LoginRequiredMixin, View):
    """
    Handles submission of official legal name or corporate entity change requests.
    Validates uploaded legal proof (CAC Certificate, Marriage Gazette, Court Affidavit)
    and logs a pending compliance audit record.
    """
    def post(self, request):
        user = request.user
        request_type = request.POST.get('request_type', 'personal')
        requested_name = request.POST.get('requested_name', '').strip()
        requested_rc = request.POST.get('requested_rc', '').strip()
        reason_category = request.POST.get('reason_category', '').strip()
        reason_text = request.POST.get('reason_text', '').strip()
        proof_file = request.FILES.get('proof_document')

        redirect_url = 'employer:profile' if request_type == 'company' else 'users:profile'

        if not requested_name:
            messages.error(request, "Please enter the requested new legal name.")
            return redirect(redirect_url)

        doc_url = ''
        doc_name = ''
        if proof_file:
            ext = os.path.splitext(proof_file.name)[1].lower()
            if ext not in ('.pdf', '.jpg', '.jpeg', '.png'):
                messages.error(request, "Supporting document must be a PDF, JPG, or PNG file.")
                return redirect(redirect_url)
            if proof_file.size > 10 * 1024 * 1024:
                messages.error(request, "Document file size must be under 10MB.")
                return redirect(redirect_url)

            clean_filename = f"lnc_{user.id}_{timezone.now().strftime('%Y%m%d%H%M%S')}{ext}"
            saved_path = default_storage.save(f"legal_name_changes/{clean_filename}", proof_file)
            doc_url = default_storage.url(saved_path)
            doc_name = proof_file.name

        ref_number = f"LNC-{timezone.now().year}-{secrets.token_hex(3).upper()}"

        current_name = (
            getattr(getattr(user, 'employer_profile', None), 'company_name', '')
            if request_type == 'company' else user.get_full_name() or user.username
        )
        current_rc = (
            getattr(getattr(user, 'employer_profile', None), 'company_rc_number', '')
            if request_type == 'company' else ''
        )

        AuditLog.objects.create(
            report=None,
            action="LEGAL_NAME_CHANGE_REQUESTED",
            performed_by=user,
            ip_address=get_client_ip(request),
            details={
                "reference_number": ref_number,
                "request_type": request_type,
                "current_name": current_name,
                "requested_name": requested_name,
                "current_rc": current_rc,
                "requested_rc": requested_rc,
                "reason_category": reason_category,
                "reason_text": reason_text,
                "document_url": doc_url,
                "document_name": doc_name,
                "status": "pending",
                "submitted_at": timezone.now().isoformat(),
            }
        )

        target_label = "company details" if request_type == 'company' else "legal name"
        messages.success(
            request,
            f"Your request to update your {target_label} has been submitted (Ref: {ref_number}). Our compliance team will review your supporting documents within 24–48 business hours."
        )
        return redirect(redirect_url)

class UserIdentityVerificationSubmitView(LoginRequiredMixin, View):
    """Handles submission of personal government ID verification credentials."""
    def post(self, request):
        user = request.user
        id_type = request.POST.get('id_type', '').strip()
        id_number = request.POST.get('id_number', '').strip()
        id_doc = request.FILES.get('id_document')

        valid_types = [c[0] for c in User.ID_TYPE_CHOICES]
        if id_type not in valid_types:
            messages.error(request, "Please select a valid government identity document type.")
            return redirect('users:profile')

        if not id_number:
            messages.error(request, "Please enter your official identification number.")
            return redirect('users:profile')

        # NIN specific validation: 11 digits
        if id_type == 'nin':
            cleaned_nin = re.sub(r'\D', '', id_number)
            if len(cleaned_nin) != 11:
                messages.error(request, "A National Identity Number (NIN) must contain exactly 11 digits.")
                return redirect('users:profile')
            id_number = cleaned_nin

        file_uploaded = False
        if id_doc:
            if id_doc.size > 5 * 1024 * 1024:
                messages.error(request, "Uploaded document exceeds the 5MB size limit. Please upload a smaller file.")
                return redirect('users:profile')
            ext = os.path.splitext(id_doc.name)[1].lower()
            if ext not in ('.pdf', '.jpg', '.jpeg', '.png'):
                messages.error(request, "Invalid file format. Please upload a PDF, JPG, or PNG document.")
                return redirect('users:profile')

            user.id_document = id_doc
            file_uploaded = True
        elif not user.has_id_document:
            messages.error(request, "Please attach a verifiable photo or scan of your government identity document.")
            return redirect('users:profile')

        user.id_type = id_type
        user.id_number = id_number
        user.id_verification_status = 'pending'
        user.id_submitted_at = timezone.now()
        user.id_rejection_reason = ''
        user.save()

        AuditLog.objects.create(
            action="USER_IDENTITY_VERIFICATION_SUBMITTED",
            performed_by=user,
            ip_address=get_client_ip(request),
            details={
                "id_type": id_type,
                "has_new_document": file_uploaded,
            }
        )

        messages.success(
            request,
            "Your identity credentials and document have been submitted. Our compliance team will review your submission."
        )
        return redirect('users:profile')


@method_decorator(xframe_options_sameorigin, name='dispatch')
class UserIdentityDocumentView(LoginRequiredMixin, View):
    """In-browser document stream for the user to view their own uploaded identity document."""
    def get(self, request):
        user = request.user
        if not user.has_id_document:
            raise Http404("No identity document uploaded.")

        try:
            doc_file = user.id_document.open('rb')
        except Exception:
            raise Http404("Document could not be opened.")

        ext = user.id_document.name.split('.')[-1].lower() if '.' in user.id_document.name else 'pdf'
        content_type, _ = mimetypes.guess_type(user.id_document.name)
        if not content_type:
            content_type = 'application/pdf' if ext == 'pdf' else 'image/jpeg'

        response = HttpResponse(doc_file.read(), content_type=content_type)
        response['Content-Disposition'] = f'inline; filename="ID_proof.{ext}"'
        response['X-Frame-Options'] = 'SAMEORIGIN'
        doc_file.close()
        return response


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



class RegisterLandingView(View):
    """
    Registration landing page — lets the visitor choose their account type
    before seeing a registration form. No login required.
    """
    template_name = 'users/register_landing.html'

    def get(self, request):
        if request.user.is_authenticated:
            return HttpResponseRedirect(reverse_lazy('dashboard:index'))
        return render(request, self.template_name)


class EmployerRegisterView(CreateView):
    """
    Employer account registration.
    Creates user with role='employer' and auto-creates EmployerProfile.
    """
    from users.forms import EmployerRegistrationForm
    form_class = EmployerRegistrationForm
    template_name = 'users/register_employer.html'
    success_url = reverse_lazy('users:login')

    def get_form_class(self):
        from users.forms import EmployerRegistrationForm
        return EmployerRegistrationForm

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return HttpResponseRedirect(reverse_lazy('dashboard:index'))
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)
        user = self.object
        try:
            html_body, text_body = render_email('generic_notification', {
                'user_name': user.get_full_name() or user.username,
                'heading': 'Welcome to VerifyNG — Employer Account',
                'body_html': (
                    f'<p>Your VerifyNG employer account has been created successfully.</p>'
                    f'<p>You can now sign in and access the Employer Portal to run background checks, '
                    f'manage your team, and upload bulk verification requests.</p>'
                    f'<p>Your username is: <strong>{user.username}</strong></p>'
                ),
                'subject': 'Welcome to VerifyNG — Employer Account Ready',
            })
            send_broadcast_email_task.delay(
                to_email=user.email,
                subject='Welcome to VerifyNG — Employer Account Ready',
                html_body=html_body,
                text_body=text_body,
            )
        except Exception:
            logger.warning("Failed to send employer welcome email to user %s", user.pk)

        messages.success(
            self.request,
            f'Employer account created! Welcome, {user.get_full_name() or user.username}. Please sign in.'
        )
        return response


class AgencyRegisterView(CreateView):
    """
    Agency / security organisation account registration.
    Creates user with role='agency'.
    """
    form_class = None   # resolved in get_form_class
    template_name = 'users/register_agency.html'
    success_url = reverse_lazy('users:login')

    def get_form_class(self):
        from users.forms import AgencyRegistrationForm
        return AgencyRegistrationForm

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return HttpResponseRedirect(reverse_lazy('dashboard:index'))
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)
        user = self.object
        try:
            html_body, text_body = render_email('generic_notification', {
                'user_name': user.get_full_name() or user.username,
                'heading': 'Welcome to VerifyNG — Agency Account',
                'body_html': (
                    f'<p>Your VerifyNG agency account has been created successfully.</p>'
                    f'<p>Agency accounts are subject to manual verification by our team before '
                    f'full access is granted. You will be notified by email once your account '
                    f'is approved.</p>'
                    f'<p>Your username is: <strong>{user.username}</strong></p>'
                ),
                'subject': 'Welcome to VerifyNG — Agency Account Pending Verification',
            })
            send_broadcast_email_task.delay(
                to_email=user.email,
                subject='Welcome to VerifyNG — Agency Account Pending Verification',
                html_body=html_body,
                text_body=text_body,
            )
        except Exception:
            logger.warning("Failed to send agency welcome email to user %s", user.pk)

        messages.success(
            self.request,
            'Agency account created. Our team will review and activate your account within 48 hours.'
        )
        return response





def oauth_google_login(request):
    """
    Initiates Google OAuth authentication while storing the user's role intent
    ('employer', 'agency', or 'individual') in the session.
    """
    role = request.GET.get('role', 'individual')
    if role in ('employer', 'agency', 'individual'):
        request.session['oauth_role_intent'] = role
    else:
        request.session['oauth_role_intent'] = 'individual'
    return HttpResponseRedirect(reverse('google_login'))


class RegisterCompanyView(LoginRequiredMixin, FormView):
    """
    Allows an existing Individual user to upgrade or register their organization/company,
    switching their role to 'employer' and initializing their EmployerProfile.
    """
    template_name = 'users/register_company.html'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        from core.permissions import is_admin_or_subadmin, is_employer
        if is_admin_or_subadmin(request.user):
            return HttpResponseRedirect(reverse('admin_portal:overview'))
        if is_employer(request.user):
            return HttpResponseRedirect(reverse('employer:dashboard'))
        return super().dispatch(request, *args, **kwargs)

    def get_form_class(self):
        from django import forms

        class CompanyUpgradeForm(forms.Form):
            company_name = forms.CharField(
                max_length=200,
                required=True,
                label='Company / Organisation Legal Name *',
                widget=forms.TextInput(attrs={
                    'class': 'form-control',
                    'placeholder': 'e.g. Acme Logistics Nigeria Ltd',
                    'autofocus': 'autofocus'
                })
            )
            company_rc_number = forms.CharField(
                max_length=50,
                required=False,
                label='CAC Registration Number (RC / BN)',
                widget=forms.TextInput(attrs={
                    'class': 'form-control',
                    'placeholder': 'RC123456 or BN654321 (optional for now)'
                })
            )
            contact_phone = forms.CharField(
                max_length=30,
                required=False,
                label='Official Phone Number',
                widget=forms.TextInput(attrs={
                    'class': 'form-control',
                    'placeholder': '+234 801 234 5678'
                })
            )

        return CompanyUpgradeForm

    def form_valid(self, form):
        user = self.request.user
        company_name = form.cleaned_data['company_name'].strip()
        rc_number = form.cleaned_data.get('company_rc_number', '').strip()
        phone = form.cleaned_data.get('contact_phone', '').strip()

        # Update role to employer
        user.role = 'employer'
        user.save(update_fields=['role'])

        # Create or update EmployerProfile
        from employer.models import EmployerProfile
        profile, _ = EmployerProfile.objects.get_or_create(user=user)
        profile.company_name = company_name
        if rc_number:
            profile.company_rc_number = rc_number
        if phone:
            profile.contact_phone = phone
        profile.save()

        messages.success(
            self.request,
            f"Welcome to the Employer Portal! Your organisation '{company_name}' is now registered. Please complete your CAC verification to unlock full screening services."
        )
        return HttpResponseRedirect(reverse('employer:dashboard'))
