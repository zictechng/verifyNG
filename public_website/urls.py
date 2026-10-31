from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('business/', views.business, name='business'),
    path('check/', views.check, name='check'),
    path('report/', views.report, name='report'),
    path('verify/', views.verify, name='verify'),
    path('help/', views.help_support, name='help'),
    path('safety/', views.safety_security, name='safety'),
    path('security/', views.safety_security, name='security'),
    path('safety-security/', views.safety_security, name='safety_security'),
    path('privacy-legal/', views.privacy_legal, name='privacy_legal'),
    path('privacy/', views.privacy_legal, {'tab': 'privacy'}, name='privacy'),
    path('policy/', views.privacy_legal, {'tab': 'privacy'}, name='policy'),
    path('legal/', views.privacy_legal, {'tab': 'legal'}, name='legal'),
    path('terms/', views.privacy_legal, {'tab': 'legal'}, name='terms'),
    path('terms-of-service/', views.privacy_legal, {'tab': 'legal'}, name='terms_of_service'),
]
