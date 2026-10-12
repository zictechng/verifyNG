from django.contrib import admin
from .models import (
    VerificationRequest,
    VerificationResult,
    VerificationCertificate,
    CertificateQueryLog,
)


class VerificationResultInline(admin.StackedInline):
    model = VerificationResult
    extra = 0
    readonly_fields = ('verified_at',)


@admin.register(VerificationRequest)
class VerificationRequestAdmin(admin.ModelAdmin):
    list_display = ('reference_number', 'target_subject', 'requester', 'verification_type', 'status', 'created_at')
    list_filter = ('verification_type', 'status', 'created_at')
    search_fields = ('reference_number', 'target_subject__name')
    inlines = [VerificationResultInline]


@admin.register(VerificationResult)
class VerificationResultAdmin(admin.ModelAdmin):
    list_display = ('request', 'outcome', 'verified_by', 'verified_at')
    list_filter = ('outcome', 'verified_at')
    search_fields = ('request__reference_number', 'summary')


class CertificateQueryLogInline(admin.TabularInline):
    model = CertificateQueryLog
    extra = 0
    readonly_fields = ('queried_at', 'queried_by', 'payment', 'purpose', 'organisation_name', 'ip_address', 'result_snapshot')
    can_delete = False

    def has_add_permission(self, request, obj=None):
        # Query logs are append-only — never created from admin
        return False


@admin.register(VerificationCertificate)
class VerificationCertificateAdmin(admin.ModelAdmin):
    list_display = ('certificate_id', 'holder', 'check_level', 'status', 'issued_at', 'expires_at', 'created_at')
    list_filter = ('check_level', 'status', 'created_at')
    search_fields = ('certificate_id', 'holder__username', 'holder__email', 'subject__name')
    readonly_fields = ('certificate_id', 'created_at', 'updated_at')
    inlines = [CertificateQueryLogInline]

    def has_delete_permission(self, request, obj=None):
        # Certificates must be revoked, not deleted
        return False


@admin.register(CertificateQueryLog)
class CertificateQueryLogAdmin(admin.ModelAdmin):
    list_display = ('certificate', 'queried_by', 'purpose', 'organisation_name', 'queried_at')
    list_filter = ('purpose', 'queried_at')
    search_fields = ('certificate__certificate_id', 'queried_by__username', 'organisation_name')
    readonly_fields = ('certificate', 'queried_by', 'payment', 'queried_at', 'ip_address', 'purpose', 'organisation_name', 'result_snapshot')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

