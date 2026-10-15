from django.urls import path

from dashboard.views import DashboardIndexView, WhoCheckedMeView

app_name = "dashboard"

urlpatterns = [
    path("", DashboardIndexView.as_view(), name="index"),
    path("who-checked-me/", WhoCheckedMeView.as_view(), name="who_checked_me"),
]