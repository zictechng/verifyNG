from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from api.api import api

urlpatterns = [
    path('admin/', admin.site.urls),
    path('admin-portal/', include('dashboard.admin_urls', namespace='admin_portal')),
    path('api/v1/', api.urls),
    path('users/', include('users.urls', namespace='users')),
    path('reports/', include('reports.urls', namespace='reports')),
    path('dashboard/', include('dashboard.urls', namespace='dashboard')),
    path('verification/', include('verification.urls', namespace='verification')),
    path('notifications/', include('notifications.urls', namespace='notifications')),
    path('payments/', include('payments.urls', namespace='payments')),
    path('', include('public_website.urls')),
]

if settings.DEBUG:
    from django.conf.urls.static import static
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

