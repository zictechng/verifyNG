from django.contrib import admin
from .models import FraudReport, ReportEvidence, Dispute, AuditLog, EvidenceDossier, DossierAccessLog


class ReportEvidenceInline(admin.TabularInline):
    model = ReportEvidence
    extra = 0
    readonly_fields = ('uploaded_at',)


@admin.register(FraudReport)
class FraudReportAdmin(admin.ModelAdmin):
    list_display = ('reference_number', 'title', 'target_subject', 'reporter', 'formatted_amount_lost', 'state', 'created_at')
    list_filter = ('state', 'created_at')
    search_fields = ('reference_number', 'title', 'allegation', 'target_subject__name')
    readonly_fields = ('formatted_amount_lost', 'created_at', 'updated_at')
    inlines = [ReportEvidenceInline]

    def formatted_amount_lost(self, obj):
        return obj.amount_lost_formatted()
    formatted_amount_lost.short_description = "Amount Lost"


@admin.register(EvidenceDossier)
class EvidenceDossierAdmin(admin.ModelAdmin):
    list_display = ('tracking_id', 'report', 'user', 'payment_status', 'amount_paid', 'scan_count', 'created_at')
    list_filter = ('payment_status', 'created_at')
    search_fields = ('tracking_id', 'report__reference_number', 'user__username', 'section84_hash')
    readonly_fields = ('tracking_id', 'section84_hash', 'scan_count', 'created_at')


@admin.register(DossierAccessLog)
class DossierAccessLogAdmin(admin.ModelAdmin):
    list_display = ('dossier', 'access_type', 'device_type', 'operating_system', 'browser', 'ip_address', 'created_at')
    list_filter = ('access_type', 'device_type', 'created_at')
    search_fields = ('dossier__tracking_id', 'ip_address', 'user_agent')
    readonly_fields = ('created_at',)


@admin.register(ReportEvidence)
class ReportEvidenceAdmin(admin.ModelAdmin):
    list_display = ('report', 'file_type', 'is_confidential', 'uploaded_at')
    list_filter = ('file_type', 'is_confidential')


@admin.register(Dispute)
class DisputeAdmin(admin.ModelAdmin):
    list_display = ('report', 'disputant', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('report__reference_number', 'reason')


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('action', 'performed_by', 'report', 'timestamp')
    list_filter = ('timestamp',)
    search_fields = ('action', 'performed_by__username')
    readonly_fields = ('timestamp',)
