from django.urls import path
from django.views.generic import RedirectView
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('business/', views.business, name='business'),
    path('check/', views.check, name='check'),
    path('report/', views.report, name='report'),
    path('verify/', views.verify, name='verify'),
    path('help/', views.help_support, name='help'),
    path('contact/', views.help_support, name='contact'),
    path('contact-us/', views.help_support, name='contact_us'),
    path('safety/', views.safety_security, name='safety'),
    path('security/', views.safety_security, name='security'),
    path('safety-security/', views.safety_security, name='safety_security'),
    path('privacy-legal/', views.privacy_legal, name='privacy_legal'),
    path('privacy/', views.privacy_legal, {'tab': 'privacy'}, name='privacy'),
    path('policy/', views.privacy_legal, {'tab': 'privacy'}, name='policy'),
    path('legal/', views.privacy_legal, {'tab': 'legal'}, name='legal'),
    path('terms/', views.privacy_legal, {'tab': 'legal'}, name='terms'),
    path('terms-of-service/', views.privacy_legal, {'tab': 'legal'}, name='terms_of_service'),
    # Convenient root aliases for authentication entrypoints
    path('login/', RedirectView.as_view(pattern_name='users:login', permanent=False, query_string=True), name='login_redirect'),
    path('signin/', RedirectView.as_view(pattern_name='users:login', permanent=False, query_string=True), name='signin_redirect'),
    path('register/', RedirectView.as_view(pattern_name='users:register_landing', permanent=False, query_string=True), name='register_redirect'),
    path('signup/', RedirectView.as_view(pattern_name='users:register_landing', permanent=False, query_string=True), name='signup_redirect'),
    path('logout/', RedirectView.as_view(pattern_name='users:logout', permanent=False, query_string=True), name='logout_redirect'),
    # Dossier public QR verification alias
    path('verify/dossier/<str:tracking_id>/', RedirectView.as_view(pattern_name='reports:dossier_verify_public', permanent=False), name='dossier_verify_redirect'),
]

