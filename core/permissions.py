from functools import wraps
from django.core.exceptions import PermissionDenied
from django.contrib.auth.decorators import user_passes_test


def is_moderator(user):
    """
    Returns True if user is authenticated and is a moderator, staff, or superuser.
    """
    if not user or not user.is_authenticated:
        return False
    return user.is_superuser or user.is_staff or getattr(user, 'role', None) == 'moderator'


def is_verification_officer(user):
    """
    Returns True if user is authenticated and has explicit role 'officer'.
    Does NOT automatically allow staff/superuser per Batch 4.1 rule.
    """
    if not user or not user.is_authenticated:
        return False
    return getattr(user, 'role', None) == 'officer'


def is_employer(user):
    if not user or not user.is_authenticated:
        return False
    # Allow direct employers, screening/authorized agencies, and business entities
    if getattr(user, 'role', None) in ('employer', 'agency', 'business') or user.is_superuser:
        return True
    try:
        return user.employer_memberships.filter(is_active=True).exists()
    except Exception:
        return False


# Semantic aliases for multi-entity B2B access
is_organization_user = is_employer


def is_business(user):
    if not user or not user.is_authenticated:
        return False
    return getattr(user, 'role', None) == 'business'


def is_agency(user):
    if not user or not user.is_authenticated:
        return False
    return getattr(user, 'role', None) == 'agency'


def get_user_home_url(user) -> str:
    """
    Returns the appropriate destination dashboard URL for a user based on their role:
    - Employer / Agency / Business / Team Member -> 'employer:dashboard'
    - Staff / Superuser -> 'admin_portal:overview'
    - Regular Candidate / Individual -> 'dashboard:index'
    """
    if not user or not user.is_authenticated:
        return 'public:home'
    if getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False):
        return 'admin_portal:overview'
    if is_employer(user):
        return 'employer:dashboard'
    return 'dashboard:index'


def can_view_report(user, report):
    """
    Report visibility policy:
    1. Superuser, Staff, or Moderator: can view reports in ANY state.
    2. Reporter (report.reporter == user): can view their own report UNLESS state is 'archived'.
    3. Disputant or Accused party: can view report in submitted, under_review, published, or disputed states.
    4. Anonymous / Public / Other users: can view report ONLY if state is 'published'.
    """
    if not report:
        return False

    if is_moderator(user):
        return True

    if user and user.is_authenticated:
        if report.reporter_id == user.id:
            return report.state != 'archived'

        # Allow user who filed a right-of-response dispute to view the report
        if hasattr(report, 'disputes') and report.disputes.filter(disputant=user).exists():
            return report.state != 'archived'

        # Allow accused user matching suspect email to view report to respond
        suspect_email = getattr(report, 'suspect_email', None)
        if suspect_email and user.email and suspect_email.strip().lower() == user.email.strip().lower():
            return report.state != 'archived'

        # Allow workplace certificate holder to view report
        if report.is_misconduct and hasattr(report, 'misconduct_profile'):
            cert = getattr(report.misconduct_profile, 'certificate', None)
            if cert and getattr(cert, 'user_id', None) == user.id:
                return report.state != 'archived'

    return report.state == 'published'


def can_view_evidence(user, evidence):
    """
    Confidential evidence policy:
    1. Must be able to view the underlying report first.
    2. If is_confidential is True: accessible to Moderators/Staff/Superusers, original Reporter,
       or the accused respondent/certificate holder inspecting allegations under due process.
    3. If is_confidential is False: accessible if user has access to view report.
    """
    if not evidence or not getattr(evidence, 'report', None):
        return False

    if not can_view_report(user, evidence.report):
        return False

    if evidence.is_confidential:
        if is_moderator(user):
            return True
        if user and user.is_authenticated:
            if evidence.report.reporter_id == user.id:
                return True
            # Accused party or disputant under fair-hearing review
            if hasattr(evidence.report, 'disputes') and evidence.report.disputes.filter(disputant=user).exists():
                return True
            suspect_email = getattr(evidence.report, 'suspect_email', None)
            if suspect_email and user.email and suspect_email.strip().lower() == user.email.strip().lower():
                return True
            if evidence.report.is_misconduct and hasattr(evidence.report, 'misconduct_profile'):
                cert = getattr(evidence.report.misconduct_profile, 'certificate', None)
                if cert and getattr(cert, 'user_id', None) == user.id:
                    return True
        return False

    return True


# --- Standard Django View Decorators ---

def role_required(*allowed_roles):
    """
    View decorator requiring authenticated user with an allowed role OR superuser bypass.
    Does NOT automatically allow staff users unless staff is explicitly in allowed_roles or superuser.
    Unauthenticated users are redirected to login by user_passes_test; unauthorized users get HTTP 403.
    """
    def check_role(u):
        if not u.is_authenticated:
            return False
        if u.is_superuser:
            return True
        if getattr(u, 'role', None) in allowed_roles:
            return True
        raise PermissionDenied("You do not have permission to access this resource.")

    return user_passes_test(check_role)


def moderator_required(view_func):
    """
    View decorator allowing moderators, staff, and superusers.
    """
    def check_moderator(u):
        if not u.is_authenticated:
            return False
        if is_moderator(u):
            return True
        raise PermissionDenied("Moderator access required.")

    return user_passes_test(check_moderator)(view_func)


def officer_required(view_func):
    """
    View decorator restricting access strictly to verification officers (role='officer' or superuser bypass in role_required).
    """
    return role_required('officer')(view_func)


def employer_required(view_func):
    """
    View decorator allowing employers, superusers, and active team members.
    """
    def check_employer(u):
        if not u.is_authenticated:
            return False
        if is_employer(u):
            return True
        raise PermissionDenied("You do not have permission to access the Employer Portal.")

    return user_passes_test(check_employer)(view_func)


def business_required(view_func):
    return role_required('business')(view_func)


def agency_required(view_func):
    return role_required('agency')(view_func)


def is_superadmin(user):
    """Returns True if user is authenticated and is a superuser or staff member."""
    if not user or not user.is_authenticated:
        return False
    return user.is_superuser or user.is_staff



def is_account_blocked(user) -> bool:
    """
    Returns True if user is unauthenticated, deactivated (is_active=False),
    or suspended by administration (is_suspended=True).
    """
    if not user or not user.is_authenticated:
        return True
    if not getattr(user, 'is_active', True):
        return True
    if getattr(user, 'is_suspended', False):
        return True
    return False


def is_profile_verified(user) -> tuple[bool, str]:
    """
    Central, reusable verification check for active platform operations.
    Returns (is_verified: bool, reason_message: str).

    Rules:
    1. Unauthenticated or blocked/suspended users -> (False, reason)
    2. Superusers, staff, verification officers, and moderators -> (True, "") [Administrative bypass]
    3. Employers / Agencies / Businesses:
       - Must have verified company CAC profile (employer_profile.is_verified=True or verification_status='verified')
       - Or active membership in a verified employer organization
    4. Individuals / Candidates:
       - Must have verified personal identity (user.identity_verified=True or id_verification_status='verified')
    """
    if not user or not user.is_authenticated:
        return False, "Authentication is required to access this resource."

    # Recursively unwrap SimpleLazyObject and OTPMiddleware partials
    while hasattr(user, '_wrapped'):
        if hasattr(user, '_is_setup') and not user._is_setup():
            user._setup()
        user = getattr(user, '_wrapped', user)
    if callable(user):
        try:
            user = user()
        except Exception:
            pass
    while hasattr(user, '_wrapped'):
        if hasattr(user, '_is_setup') and not user._is_setup():
            user._setup()
        user = getattr(user, '_wrapped', user)

    if not getattr(user, 'is_active', True):
        return False, "Your account has been deactivated. Please contact platform support."

    if getattr(user, 'is_suspended', False) is True:
        return False, "Your account is suspended. Platform actions are restricted."

    # Administrative bypass: Superusers, staff, verification officers, and moderators
    if (
        getattr(user, 'is_superuser', False) is True
        or getattr(user, 'is_staff', False) is True
        or getattr(user, 'role', None) in ('officer', 'moderator')
    ):
        return True, ""

    # Check Employer / Organization accounts
    if is_employer(user):
        profile = getattr(user, 'employer_profile', None)
        if profile and (getattr(profile, 'is_verified', False) is True or getattr(profile, 'verification_status', None) == 'verified'):
            return True, ""

        # Check if user is an active team member of a verified employer organization
        try:
            active_verified_org = user.employer_memberships.filter(
                is_active=True,
                employer__employer_profile__is_verified=True
            ).exists()
            if active_verified_org:
                return True, ""
        except Exception:
            pass

        return False, "Company verification required. Please submit your CAC incorporation document to access this service."

    # Individual / Candidate accounts
    if getattr(user, 'id_verification_status', None) == 'verified':
        return True, ""

    raw_verified = getattr(user, 'identity_verified', False)
    if isinstance(raw_verified, bool) and raw_verified is True:
        return True, ""

    # Handle case where OTPMiddleware attached a partial to identity_verified
    if getattr(user, 'pk', None):
        try:
            from django.contrib.auth import get_user_model
            UserModel = get_user_model()
            if UserModel.objects.filter(pk=user.pk, identity_verified=True).exists():
                return True, ""
            if UserModel.objects.filter(pk=user.pk, id_verification_status='verified').exists():
                return True, ""
        except Exception:
            pass

    return False, "Identity verification required. Please submit your official government ID (NIN, BVN, PVC, or Passport) to verify your profile."


def verified_profile_required(view_func=None, redirect_url=None):
    """
    View decorator requiring authenticated user with an active, verified profile.
    Unauthenticated users are redirected to login.
    Unverified users are flashed a warning and redirected to their profile verification page.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                from django.contrib.auth.views import redirect_to_login
                return redirect_to_login(request.get_full_path())

            verified, message = is_profile_verified(request.user)
            if not verified:
                from django.contrib import messages
                from django.shortcuts import redirect
                messages.warning(request, message)

                if redirect_url:
                    return redirect(redirect_url)
                if is_employer(request.user):
                    return redirect('employer:profile')
                return redirect('users:profile')

            return func(request, *args, **kwargs)
        return wrapper

    if view_func is not None:
        return decorator(view_func)
    return decorator


class VerifiedProfileRequiredMixin:
    """
    CBV mixin that enforces that the user's account is active and verified.
    Unauthenticated users are redirected to login.
    Unverified users receive an alert message and are redirected to their profile verification page.
    """
    verified_redirect_url = None

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login
            return redirect_to_login(request.get_full_path())

        verified, message = is_profile_verified(request.user)
        if not verified:
            from django.contrib import messages
            from django.shortcuts import redirect
            messages.warning(request, message)

            if self.verified_redirect_url:
                return redirect(self.verified_redirect_url)
            if is_employer(request.user):
                return redirect('employer:profile')
            return redirect('users:profile')

        return super().dispatch(request, *args, **kwargs)
