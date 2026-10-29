from functools import wraps
from django.shortcuts import render
from django.contrib import admin
from django.urls import path, include
from django_otp.admin import OTPAdminSite
from django.conf import settings

# Enforce OTP/Two-Factor security on the technical Django Admin in production only.
# In local development (DEBUG=True), standard username/password login is used.
if not settings.DEBUG:
    admin.site.__class__ = OTPAdminSite

# Strictly protect raw technical Django Admin (/admin/) for Superadmins only.
# Sub-admins (moderators, officers) are guided to the custom VerifyNG Admin Portal.
_original_admin_view = admin.site.admin_view

def _restricted_admin_view(view, cacheable=False):
    wrapped = _original_admin_view(view, cacheable)
    @wraps(view)
    def inner(request, *args, **kwargs):
        if request.user.is_authenticated and not request.user.is_superuser:
            return render(
                request,
                'admin_portal/access_denied.html',
                {
                    'section_name': 'Technical Backend (/admin/)',
                    'custom_message': 'You are not authorized to access the technical backend. Please use the VerifyNG Admin Portal.',
                },
                status=403,
            )
        return wrapped(request, *args, **kwargs)
    return inner

admin.site.admin_view = _restricted_admin_view

_api_urls = None

def get_api_urls():
    global _api_urls
    if _api_urls is None:
        from api.api import api
        _api_urls = api.urls
    return _api_urls

urlpatterns = [
    path('admin/', admin.site.urls),
    path('admin-portal/', include('dashboard.admin_urls', namespace='admin_portal')),
    path('api/v1/', get_api_urls()),
    path('users/', include('users.urls', namespace='users')),
    path('reports/', include('reports.urls', namespace='reports')),
    path('dashboard/', include('dashboard.urls', namespace='dashboard')),
    path('verification/', include('verification.urls', namespace='verification')),
    path('notifications/', include('notifications.urls', namespace='notifications')),
    path('payments/', include('payments.urls', namespace='payments')),
    path('employer/', include('employer.urls', namespace='employer')),
    path('accounts/', include('allauth.urls')),
    path('', include('public_website.urls')),
]

if settings.DEBUG:
    from django.conf.urls.static import static
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

