
"""
users/middleware.py
-------------------
Intercepts requests from suspended users and redirects them to a
dedicated suspended page. Suspended users CAN log in but cannot
access any platform functionality.

Excluded paths (always pass through):
  - /accounts/login/   — must be able to log in
  - /accounts/logout/  — must be able to log out
  - /suspended/        — the suspended message page itself
  - /admin/            — Django admin (staff exempt anyway)
  - /static/           — static assets
  - /media/            — media assets
"""

from django.shortcuts import redirect
from django.urls import reverse


class SuspendedUserMiddleware:
    """
    If the authenticated user has is_suspended=True, redirect every request
    to the suspended notice page, except for the whitelisted paths above.
    """

    ALLOWED_PREFIXES = (
        '/accounts/login/',
        '/accounts/logout/',
        '/suspended/',
        '/admin/',
        '/static/',
        '/media/',
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            request.user.is_authenticated
            and getattr(request.user, 'is_suspended', False)
            and not any(request.path.startswith(p) for p in self.ALLOWED_PREFIXES)
        ):
            return redirect('users:account_suspended')

        # If user navigates away from verification to any other page, clear the pending code
        # so returning later generates a fresh code, while F5 reloads on the page stay stable
        if (
            hasattr(request, 'session')
            and 'vng_path_b_code' in request.session
            and not request.path.startswith(('/users/verify-account', '/users/profile/verify', '/static/', '/media/'))
            and request.headers.get('x-requested-with') != 'XMLHttpRequest'
        ):
            request.session.pop('vng_path_b_code', None)
            request.session.pop('vng_path_b_code_created_at', None)

        return self.get_response(request)

    