# payments/urls.py
from django.urls import path
from . import views
from .merchant_views import MerchantLandingView, MerchantApplyView, MerchantBankChangeRequestView
views.MerchantLandingView = MerchantLandingView
views.MerchantApplyView = MerchantApplyView
views.MerchantBankChangeRequestView = MerchantBankChangeRequestView

app_name = 'payments'

urlpatterns = [
    path('', views.plans_list, name='plans'),
    path('review/<slug:plan_slug>/', views.checkout_review, name='checkout_review'),
    path('review/service/<str:service_key>/', views.service_checkout_review, name='service_checkout_review'),
    path('checkout/service/<str:service_key>/', views.service_checkout_execute, name='service_checkout_execute'),
    path('checkout/<slug:plan_slug>/', views.checkout, name='checkout'),
    path('callback/', views.payment_callback, name='callback'),
    path('webhook/', views.paystack_webhook, name='webhook'),
    path('my-subscription/', views.my_subscription, name='my_subscription'),
    path('cancel/', views.cancel_subscription, name='cancel'),
    path('history/', views.transaction_history, name='history'),
    path('dismiss-banner/', views.dismiss_prepaid_banner, name='dismiss_prepaid_banner'),
    # Verified Merchant Trust Seal URLs
    path('trust-badge/', views.MerchantLandingView.as_view(), name='merchant_landing'),
    path('trust-badge/apply/', views.MerchantApplyView.as_view(), name='merchant_apply'),
    path('trust-badge/request-bank-change/', views.MerchantBankChangeRequestView.as_view(), name='merchant_request_bank_change'),
]
