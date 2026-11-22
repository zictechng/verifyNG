from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, AlternativeVerificationSubmission, UserServiceAccess


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = (
        'username', 'email', 'first_name', 'last_name',
        'role', 'country', 'state', 'lga',
        'id_verification_status', 'identity_verified', 'is_staff'
    )
    list_filter = (
        'role', 'id_verification_status', 'identity_verified',
        'country', 'state', 'is_staff', 'is_superuser', 'is_active'
    )
    search_fields = (
        'username', 'first_name', 'last_name', 'email',
        'country', 'state', 'lga', 'id_number'
    )

    def get_search_results(self, request, queryset, search_term):
        queryset, use_distinct = super().get_search_results(request, queryset, search_term)
        if search_term:
            from users.country_config import get_country_codes_for_query
            matching_codes = get_country_codes_for_query(search_term)
            if matching_codes:
                queryset |= self.model.objects.filter(country__in=matching_codes)
        return queryset, use_distinct

    fieldsets = BaseUserAdmin.fieldsets + (
        ('VerifyNG RBAC & Verification Standing', {
            'fields': ('role', 'identity_verified', 'assurance_level')
        }),
        ('Regional & Government Identity Details', {
            'fields': (
                'country', 'state', 'lga',
                'id_type', 'id_number', 'id_verification_status',
                'id_submitted_at', 'id_verified_at', 'id_rejection_reason'
            )
        }),
    )

    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ('VerifyNG RBAC & Regional Details', {
            'fields': ('role', 'country', 'state', 'lga', 'identity_verified')
        }),
    )


@admin.register(AlternativeVerificationSubmission)
class AlternativeVerificationSubmissionAdmin(admin.ModelAdmin):
    list_display = (
        'user', 'status', 'evidence_type',
        'residential_country', 'submitted_at', 'reviewed_by', 'reviewed_at'
    )
    list_filter = ('status', 'evidence_type', 'residential_country')
    search_fields = ('user__username', 'user__email', 'residential_country', 'residential_address')
    readonly_fields = ('submitted_at',)


@admin.register(UserServiceAccess)
class UserServiceAccessAdmin(admin.ModelAdmin):
    list_display = ('user', 'service', 'is_restricted', 'restricted_at', 'restricted_by')
    list_filter = ('is_restricted', 'service')
    search_fields = ('user__username', 'user__email', 'service')
