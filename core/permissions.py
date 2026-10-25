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

