from functools import wraps
from django.core.exceptions import PermissionDenied
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth import get_user_model
from django.contrib import messages
from django.shortcuts import redirect
from django.contrib.auth.views import redirect_to_login
                

def is_moderator(user):
    """
    Returns True if user is authenticated and is a moderator, staff (non-officer), or superuser.
    Verification officers are strictly separated from fraud moderation.
    """
    if not user or not user.is_authenticated:
        return False
    if getattr(user, 'is_superuser', False):
        return True
    if getattr(user, 'role', None) == 'officer':
        return False
    return bool(getattr(user, 'is_staff', False) or getattr(user, 'role', None) == 'moderator')


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


def is_admin_or_subadmin(user) -> bool:
    """
    Returns True if user is an admin or sub-admin:
    - Superusers
    - Staff members
    - Moderator role
    - Verification Officer role
    """
    if not user or not user.is_authenticated:
        return False
    return (
        getattr(user, 'is_superuser', False) is True
        or getattr(user, 'is_staff', False) is True
        or getattr(user, 'role', None) in ('moderator', 'officer')
    )


def get_user_home_url(user) -> str:
    """
    Returns the appropriate destination dashboard URL for a user based on their role:
    - Admin / Sub-admin (Superuser, Staff, Moderator, Officer) -> 'admin_portal:overview'
    - Employer / Agency / Business / Team Member -> 'employer:dashboard'
    - Regular Candidate / Individual -> 'dashboard:index'
    """
    if not user or not user.is_authenticated:
        return 'public:home'
    if is_admin_or_subadmin(user):
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

        # Allow verified merchant owner to view dispute/fraud reports filed against their store
        try:
            from payments.models import MerchantProfile
            from payments.merchant_views import find_merchant_for_report
            merchant = find_merchant_for_report(report)
            if merchant and merchant.user_id == user.id:
                return report.state != 'archived'
            user_merchants = MerchantProfile.objects.filter(user=user)
            for m in user_merchants:
                if (report.target_subject and (
                    report.target_subject.name.lower() == m.store_name.lower() or
                    report.target_subject.name.lower() == m.store_slug.lower()
                )) or (m.store_name.lower() in report.title.lower()):
                    return report.state != 'archived'
        except Exception:
            pass

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
            # Allow merchant owner to inspect evidence filed against their store
            try:
                from payments.merchant_views import find_merchant_for_report
                merchant = find_merchant_for_report(evidence.report)
                if merchant and merchant.user_id == user.id:
                    return True
            except Exception:
                pass
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


class VerificationResult(tuple):
    """
    Dual-nature verification outcome:
    1. In boolean contexts (`if res:`, `bool(res)`), evaluates strictly to `allowed: bool` (prevents truthy-tuple loophole).
    2. In tuple unpacking contexts (`verified, reason = res`), unpacks cleanly as `(allowed, reason)`.
    3. In equality comparisons (`res == True`, `res == False`), compares against boolean `allowed`.
    """
    def __new__(cls, allowed: bool, reason: str = ""):
        obj = super().__new__(cls, (bool(allowed), str(reason)))
        obj.allowed = bool(allowed)
        obj.reason = str(reason)
        return obj

    def __bool__(self):
        return self.allowed

    def __eq__(self, other):
        if isinstance(other, bool):
            return self.allowed == other
        return super().__eq__(other)

    def __ne__(self, other):
        return not self.__eq__(other)


def _check_security_preamble(user):
    """
    Validates user authentication, active state, suspension, and administrative bypass.
    Returns (result, message, unwrapped_user):
      - If result is False: security check failed; caller immediately returns VerificationResult(False, message).
      - If result is True: administrative bypass granted; caller immediately returns VerificationResult(True, "").
      - If result is None: check passed; caller proceeds with tier-specific checks on unwrapped_user.
    """
    if not user or not user.is_authenticated:
        return False, "Authentication is required to access this resource.", user

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
        return False, "Your account has been deactivated. Please contact platform support.", user

    if getattr(user, 'is_suspended', False) is True:
        return False, "Your account is suspended. Platform actions are restricted.", user

    # Administrative bypass: Superusers, staff, verification officers, and moderators
    if (
        getattr(user, 'is_superuser', False) is True
        or getattr(user, 'is_staff', False) is True
        or getattr(user, 'role', None) in ('officer', 'moderator')
    ):
        return True, "", user

    return None, "", user


def has_basic_identity_access(user) -> VerificationResult:
    """
    Permissions check for Basic Identity Evidence Reviewed (Free individual tier).
    Grants access to citizen fraud reporting, trust badges, and standard platform actions.
    """
    bypass, reason, u = _check_security_preamble(user)
    if bypass is not None:
        return VerificationResult(bypass, reason)

    id_status = getattr(u, 'id_verification_status', 'unverified')

    # Explicit non-active lifecycle states always deny access
    if id_status == 'rejected':
        return VerificationResult(False, "Your identity verification was declined by compliance. Please review and re-submit a valid government ID.")
    elif id_status == 'suspended':
        return VerificationResult(False, "Your identity verification has been suspended by compliance. Platform actions are restricted.")
    elif id_status == 'expired':
        return VerificationResult(False, "Your identity document on file has expired. Please submit an updated document to restore access.")

    # Individual assurance level or verified lifecycle status
    if getattr(u, 'assurance_level', None) in ('basic_verified', 'enhanced_verified') and id_status == 'verified':
        return VerificationResult(True, "")

    # Backward compatibility with legacy verified status
    if id_status == 'verified' or getattr(u, 'identity_verified', False) is True:
        return VerificationResult(True, "")

    # Handle case where OTPMiddleware attached a partial to identity_verified
    if getattr(u, 'pk', None):
        try:
            UserModel = get_user_model()
            if UserModel.objects.filter(pk=u.pk, id_verification_status='verified').exists():
                return VerificationResult(True, "")
            if UserModel.objects.filter(pk=u.pk, identity_verified=True).exclude(id_verification_status__in=['rejected', 'suspended', 'expired']).exists():
                return VerificationResult(True, "")
        except Exception:
            pass

    if id_status == 'pending' or getattr(u, 'has_id_document', False):
        return VerificationResult(False, "Your identity verification is currently under compliance review. Platform actions will be unlocked once approved.")
    return VerificationResult(False, "Identity verification required. Please submit your official government ID (NIN, BVN, PVC, or Passport) to verify your profile.")


def has_enhanced_identity_access(user) -> VerificationResult:
    """
    Permissions check for Enhanced Identity Verified (High assurance / Commercial tier).
    Requires authoritative third-party biometric or registry check (e.g. Smile ID, verified national database match).
    """
    bypass, reason, u = _check_security_preamble(user)
    if bypass is not None:
        return VerificationResult(bypass, reason)

    if (
        getattr(u, 'assurance_level', None) == 'enhanced_verified'
        and getattr(u, 'id_verification_status', None) == 'verified'
        and getattr(u, 'identity_verified', False) is True
    ):
        return VerificationResult(True, "")

    id_status = getattr(u, 'id_verification_status', 'unverified')
    if id_status == 'suspended':
        return VerificationResult(False, "Enhanced identity access is unavailable: verification is suspended.")
    elif id_status == 'expired':
        return VerificationResult(False, "Enhanced identity access is unavailable: document has expired.")
    elif id_status == 'rejected':
        return VerificationResult(False, "Enhanced identity access is unavailable: verification was declined.")
    elif getattr(u, 'assurance_level', None) == 'basic_verified':
        return VerificationResult(False, "Enhanced identity verification required. Please complete biometric or authoritative registry verification.")
    return VerificationResult(False, "Enhanced verification required. Please complete verified profile and commercial identity checks.")


def has_verified_business_access(user) -> VerificationResult:
    """
    Permissions check for Corporate / Business Entity Verified (CAC, ORC, RCCM, BRS).
    Independent of director's personal identity. Checks corporate entity incorporation.
    """
    bypass, reason, u = _check_security_preamble(user)
    if bypass is not None:
        return VerificationResult(bypass, reason)

    # Must be an employer/organization user
    if not is_employer(u):
        return VerificationResult(False, "Employer or business account required to access corporate features.")

    profile = getattr(u, 'employer_profile', None)
    if profile and (getattr(profile, 'is_verified', False) is True or getattr(profile, 'verification_status', None) == 'verified'):
        return VerificationResult(True, "")

    # Check if user is an active team member of a verified employer organization
    try:
        active_verified_org = (
            u.employer_memberships.filter(is_active=True, employer__is_verified=True).exists()
            or u.employer_memberships.filter(is_active=True, employer__employer_profile__is_verified=True).exists()
        )
        if active_verified_org:
            return VerificationResult(True, "")
    except Exception:
        pass

    emp_status = getattr(profile, 'verification_status', 'unverified') if profile else 'unverified'
    if emp_status == 'pending' or (profile and getattr(profile, 'cac_document', None)):
        return VerificationResult(False, "Your company CAC verification is currently under compliance review. Platform actions will be unlocked once approved.")
    elif emp_status == 'rejected':
        return VerificationResult(False, "Your company CAC document was declined by compliance. Please review your company profile and submit a valid document.")
    elif emp_status == 'suspended':
        return VerificationResult(False, "Your company business verification has been suspended by compliance.")
    elif emp_status == 'expired':
        return VerificationResult(False, "Your company business verification has expired.")
    return VerificationResult(False, "Company verification required. Please submit your CAC incorporation document to access this service.")


def is_profile_verified(user) -> VerificationResult:
    """
    Backward-compatible verification check for active platform operations.
    Returns VerificationResult:
      - In boolean contexts (`if is_profile_verified(user):`), evaluates strictly to `allowed: bool`
      - In tuple unpacking contexts (`verified, message = is_profile_verified(user)`), unpacks to `(allowed, message)`
      - In equality comparisons (`res == True` or `res == False`), compares against boolean `allowed`.

    Rules:
    1. Unauthenticated or blocked/suspended users -> (False, reason)
    2. Superusers, staff, verification officers, and moderators -> (True, "") [Administrative bypass]
    3. Employers / Agencies / Businesses:
       - Must have verified company CAC profile (or active membership in a verified employer organization)
    4. Individuals / Candidates:
       - Must have verified personal identity (basic or enhanced verified)
    """
    if is_employer(user):
        return has_verified_business_access(user)
    return has_basic_identity_access(user)


def basic_identity_required(view_func=None, redirect_url=None):
    """
    View decorator requiring authenticated user with approved basic identity verification.
    Unauthenticated users are redirected to login.
    Unverified users receive a warning message and are redirected to users:profile.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())

            res = has_basic_identity_access(request.user)
            if not res:
                messages.warning(request, res.reason)
                return redirect(redirect_url or 'users:profile')

            return func(request, *args, **kwargs)
        return wrapper

    if view_func is not None:
        return decorator(view_func)
    return decorator


def enhanced_identity_required(view_func=None, redirect_url=None):
    """
    View decorator requiring authenticated user with approved enhanced identity verification.
    Unauthenticated users are redirected to login.
    Unverified or basic-only users receive a warning message and are redirected to users:profile.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())

            res = has_enhanced_identity_access(request.user)
            if not res:
                messages.warning(request, res.reason)
                return redirect(redirect_url or 'users:profile')

            return func(request, *args, **kwargs)
        return wrapper

    if view_func is not None:
        return decorator(view_func)
    return decorator


def verified_business_required(view_func=None, redirect_url=None):
    """
    View decorator requiring authenticated user with verified corporate/business entity registration.
    Unauthenticated users are redirected to login.
    Unverified employers receive a warning message and are redirected to employer:profile.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())

            res = has_verified_business_access(request.user)
            if not res:
                messages.warning(request, res.reason)
                return redirect(redirect_url or 'employer:profile')

            return func(request, *args, **kwargs)
        return wrapper

    if view_func is not None:
        return decorator(view_func)
    return decorator


class BasicIdentityRequiredMixin:
    """CBV mixin enforcing basic identity verification."""
    basic_redirect_url = None

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())

        res = has_basic_identity_access(request.user)
        if not res:
            messages.warning(request, res.reason)
            return redirect(self.basic_redirect_url or 'users:profile')

        return super().dispatch(request, *args, **kwargs)


class EnhancedIdentityRequiredMixin:
    """CBV mixin enforcing enhanced identity verification."""
    enhanced_redirect_url = None

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())

        res = has_enhanced_identity_access(request.user)
        if not res:
            messages.warning(request, res.reason)
            return redirect(self.enhanced_redirect_url or 'users:profile')

        return super().dispatch(request, *args, **kwargs)


class VerifiedBusinessRequiredMixin:
    """CBV mixin enforcing verified business/employer status."""
    business_redirect_url = None

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())

        res = has_verified_business_access(request.user)
        if not res:
            messages.warning(request, res.reason)
            return redirect(self.business_redirect_url or 'employer:profile')

        return super().dispatch(request, *args, **kwargs)


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
                return redirect_to_login(request.get_full_path())

            verified, message = is_profile_verified(request.user)
            if not verified:
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
            return redirect_to_login(request.get_full_path())

        verified, message = is_profile_verified(request.user)
        if not verified:
            messages.warning(request, message)

            if self.verified_redirect_url:
                return redirect(self.verified_redirect_url)
            if is_employer(request.user):
                return redirect('employer:profile')
            return redirect('users:profile')

        return super().dispatch(request, *args, **kwargs)


ACCEPTABLE_PATH_A_DOCUMENTS = {
    'nin', 'voters_card', 'passport', 'drivers_license',
    'ghana_card', 'cip', 'cni', 'national_id'
}


def has_strict_path_a_evidence(user) -> VerificationResult:
    """
    Evaluates whether an individual satisfies the strict Path A (Government Identity Evidence)
    criteria for report-publishing eligibility.

    Centralized helper used by:
      1. `can_user_publish_reports()`
      2. Admin Path B revocation handler (when recalculating independent Path A standing)

    Strict Path A Criteria (all 8 must pass):
      1. User is authenticated and active
      2. User account is not suspended (is_suspended == False)
      3. No active 'fraud_report' service restriction in UserServiceAccess
      4. id_verification_status == 'verified'
      5. Accepted identity document type (id_type in ACCEPTABLE_PATH_A_DOCUMENTS; BVN excluded)
      6. Non-empty submitted identity document file (bool(id_document))
      7. Verification timestamp is populated (id_verified_at is not None)
      8. Base identity access check passes (has_basic_identity_access(user).allowed == True)
    """
    if not user or not user.is_authenticated:
        return VerificationResult(False, "Authentication required.")

    # Unwrap lazy user objects
    while hasattr(user, '_wrapped'):
        if hasattr(user, '_is_setup') and not user._is_setup():
            user._setup()
        user = getattr(user, '_wrapped', user)
    if callable(user):
        try:
            user = user()
        except Exception:
            pass

    if not getattr(user, 'is_active', True):
        return VerificationResult(False, "Your account has been deactivated.")

    if getattr(user, 'is_suspended', False) is True:
        return VerificationResult(False, "Your account is suspended. Platform actions are restricted.")

    # Check per-user service access restriction
    try:
        from users.models import UserServiceAccess
        if UserServiceAccess.objects.filter(user=user, service='fraud_report', is_restricted=True).exists():
            return VerificationResult(False, "Access to fraud crime reporting has been restricted for your account by platform administration.")
    except Exception:
        pass

    # Strict lifecycle status
    if getattr(user, 'id_verification_status', None) != 'verified':
        return VerificationResult(False, "Approved government identity verification required.")

    # Strict document type
    doc_type = (getattr(user, 'id_type', '') or '').lower()
    if doc_type not in ACCEPTABLE_PATH_A_DOCUMENTS:
        return VerificationResult(False, "A qualifying physical government identity document is required for report publishing.")

    # Non-empty document file
    doc_file = getattr(user, 'id_document', None)
    if not doc_file or not str(doc_file).strip():
        return VerificationResult(False, "A submitted identity document file is required.")

    # Verification timestamp
    if not getattr(user, 'id_verified_at', None):
        return VerificationResult(False, "Identity verification timestamp is missing.")

    # Base access sanity check
    base_access = has_basic_identity_access(user)
    if not base_access.allowed:
        return VerificationResult(False, base_access.reason)

    return VerificationResult(True, "")


def can_user_publish_reports(user) -> VerificationResult:
    """
    Security gate for publishing community fraud and misconduct reports.

    Enforces:
      Gate 1 (Base Security): Authenticated, active, not suspended.
      Gate 2 (Service Restriction): No 'fraud_report' block in UserServiceAccess.
      Gate 3 (Security Suspension): id_verification_status != 'suspended'.
      Gate 4 (Explicit Eligibility): can_publish_reports == True.
      Gate 5 (Dual-Pathway Evidence):
         - Path B: user.alternative_verification_submissions.filter(status='approved').exists()
           (Preserves existing approval even if subsequent submissions are pending/rejected)
         - Path A: has_strict_path_a_evidence(user).allowed == True
      Gate 6 (Default Denial): Returns failure if neither pathway is valid.

    Note: Superusers, staff, and officers filing personal community reports as complainants
    must meet these same criteria (no staff complainant bypass).
    """
    if not user or not user.is_authenticated:
        return VerificationResult(False, "Authentication required to submit reports.")

    # Unwrap lazy user
    while hasattr(user, '_wrapped'):
        if hasattr(user, '_is_setup') and not user._is_setup():
            user._setup()
        user = getattr(user, '_wrapped', user)
    if callable(user):
        try:
            user = user()
        except Exception:
            pass

    # Gate 1: Base security
    if not getattr(user, 'is_active', True):
        return VerificationResult(False, "Your account has been deactivated.")
    if getattr(user, 'is_suspended', False) is True:
        return VerificationResult(False, "Your account is suspended. Platform actions are restricted.")

    # Gate 2: Service-level restriction
    try:
        from users.models import UserServiceAccess
        if UserServiceAccess.objects.filter(user=user, service='fraud_report', is_restricted=True).exists():
            return VerificationResult(False, "Access to fraud crime reporting has been restricted for your account by platform administration.")
    except Exception:
        pass

    # Gate 3: Security suspension of identity
    if getattr(user, 'id_verification_status', None) == 'suspended':
        return VerificationResult(False, "Your identity verification has been suspended. Platform publishing actions are restricted.")

    # Gate 4: Explicit publishing flag
    if not getattr(user, 'can_publish_reports', False):
        return VerificationResult(False, "Report publishing eligibility required. Please complete identity or community personhood verification.")

    # Gate 5: Dual-Pathway Resolution
    # 5a. Independent Path B (Alternative Personhood)
    try:
        has_active_path_b = user.alternative_verification_submissions.filter(status='approved').exists()
        if has_active_path_b:
            return VerificationResult(True, "")
    except Exception:
        pass

    # 5b. Strict Path A (Government Identity Evidence)
    path_a_result = has_strict_path_a_evidence(user)
    if path_a_result.allowed:
        return VerificationResult(True, "")

    # Gate 6: Default denial
    return VerificationResult(False, path_a_result.reason or "Qualifying identity or community verification required to publish reports.")

