from django.conf import settings
from .base import BaseVerificationProvider
from .mock_provider import MockVerificationProvider
from .smile_id import SmileIDProvider


def get_verification_provider() -> BaseVerificationProvider:
    """
    Factory to return the active pluggable verification provider.
    Can be switched seamlessly via settings.KYC_PROVIDER:
    - 'smile_id' (Default live integration)
    - 'mock' (Testing without live API calls)
    - Future: 'dojah', 'prembly', 'verifyme'
    """
    provider_key = getattr(settings, 'KYC_PROVIDER', 'smile_id').lower().strip()

    if provider_key == 'smile_id':
        return SmileIDProvider()
    elif provider_key == 'mock':
        return MockVerificationProvider()
    else:
        # Fallback to SmileIDProvider (which will gracefully use mock if unconfigured)
        return SmileIDProvider()
