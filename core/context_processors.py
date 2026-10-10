
from core.models import SiteConfiguration


def site_configuration(request):
    """
    Injects 'site_config' into template contexts.
    Requires database tables to be migrated. Does not silently suppress database outages.
    """
    return {
        'site_config': SiteConfiguration.get_solo()
    }

