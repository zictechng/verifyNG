from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ('username', 'email', 'first_name', 'last_name', 'role', 'is_verified', 'is_staff')
    list_filter = ('role', 'is_verified', 'is_staff', 'is_superuser', 'is_active')
    search_fields = ('username', 'first_name', 'last_name', 'email')

    fieldsets = BaseUserAdmin.fieldsets + (
        ('VerifyNG RBAC & Verification Status', {
            'fields': ('role', 'is_verified')
        }),
    )

    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ('VerifyNG RBAC & Verification Status', {
            'fields': ('role', 'is_verified')
        }),
    )
