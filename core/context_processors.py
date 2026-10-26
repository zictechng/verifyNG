from core.models import SiteConfiguration


def site_configuration(request):
    """
    Injects 'site_config', 'site_settings', 'user_active_subscription',
    and 'user_free_quota' into all template contexts.
    Safely handles DB states without breaking unmigrated/test environments.
    """
    ctx = {
        'site_config': SiteConfiguration.get_solo()
    }

    try:
        from payments.models import SiteSettings
        ctx['site_settings'] = SiteSettings.get()
    except Exception:
        ctx['site_settings'] = None

    if hasattr(request, 'user') and request.user.is_authenticated:
        try:
            from payments.services import get_active_subscription
            from payments.models import FreeUsageQuota
            ctx['user_active_subscription'] = get_active_subscription(request.user)
            ctx['user_free_quota'] = FreeUsageQuota.for_user(request.user)
        except Exception:
            ctx['user_active_subscription'] = None
            ctx['user_free_quota'] = None
    else:
        ctx['user_active_subscription'] = None
        ctx['user_free_quota'] = None

    return ctx
