from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('business/', views.business, name='business'),
    path('check/', views.check, name='check'),
    path('report/', views.report, name='report'),
    path('verify/', views.verify, name='verify'),
    path('help/', views.help_support, name='help'),
    path('privacy-legal/', views.privacy_legal, name='privacy_legal'),
    path('privacy/', views.privacy_legal, {'tab': 'privacy'}, name='privacy'),
    path('legal/', views.privacy_legal, {'tab': 'legal'}, name='legal'),
]
