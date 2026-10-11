
# payments/urls.py
from django.urls import path
from . import views

app_name = 'payments'

urlpatterns = [
    path('', views.plans_list, name='plans'),
    path('checkout/<slug:plan_slug>/', views.checkout, name='checkout'),
    path('callback/', views.payment_callback, name='callback'),
    path('webhook/', views.paystack_webhook, name='webhook'),
    path('my-subscription/', views.my_subscription, name='my_subscription'),
    path('cancel/', views.cancel_subscription, name='cancel'),
    path('history/', views.transaction_history, name='history'),
]
