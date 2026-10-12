from django.contrib import admin
from verification.models import (
    VerificationRequest,
    VerificationResult,
    VerificationCertificate,
    CertificateQueryLog,
)


@admin.register(VerificationRequest)
class VerificationRequestAdmin(admin.ModelAdmin):
    list_display = ('reference_number', 'verification_type', 'status', 'requester', 'created_at')
    list_filter = ('status', 'verification_type')
    search_fields = ('reference_number', 'requester__username', 'requester__email')
    readonly_fields = ('reference_number', 'created_at', 'updated_at')
    ordering = ('-created_at',)


@admin.register(VerificationResult)
class VerificationResultAdmin(admin.ModelAdmin):
    list_display = ('request', 'outcome', 'verified_by', 'verified_at')
    list_filter = ('outcome',)
    search_fields = ('request__reference_number',)
    readonly_fields = ('verified_at',)


@admin.register(VerificationCertificate)
class VerificationCertificateAdmin(admin.ModelAdmin):
    list_display = ('certificate_id', 'issued_to_name', 'check_level', 'status', 'is_active', 'created_at')
    list_filter = ('check_level', 'status', 'is_active')
    search_fields = ('certificate_id', 'holder__username', 'holder__email', 'subject__name')
    readonly_fields = ('certificate_id', 'created_at', 'updated_at')
    ordering = ('-created_at',)

    @admin.display(description='Issued To')
    def issued_to_name(self, obj):
        if obj.subject and obj.subject.name:
            return obj.subject.name
        return obj.holder.get_full_name() or obj.holder.username


@admin.register(CertificateQueryLog)
class CertificateQueryLogAdmin(admin.ModelAdmin):
    """
    Append-only audit log: no add, change, or delete permissions in admin.
    Read-only view for auditing purposes only.
    """
    list_display = ('certificate', 'queried_by', 'queried_at', 'ip_address', 'purpose', 'transaction_reference')
    list_filter = ('purpose', 'queried_at')
    search_fields = ('certificate__certificate_id', 'queried_by__username', 'payment__reference')
    readonly_fields = (
        'certificate',
        'queried_by',
        'payment',
        'queried_at',
        'ip_address',
        'purpose',
        'transaction_reference',
        'organisation_name',
        'result_snapshot',
    )
    ordering = ('-queried_at',)

    @admin.display(description='Transaction Reference')
    def transaction_reference(self, obj):
        return obj.payment.reference if obj.payment else '-'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

