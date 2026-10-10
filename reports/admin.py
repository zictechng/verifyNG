from django.contrib import admin
from .models import FraudReport, ReportEvidence, Dispute, AuditLog


class ReportEvidenceInline(admin.TabularInline):
    model = ReportEvidence
    extra = 0
    readonly_fields = ('uploaded_at',)


@admin.register(FraudReport)
class FraudReportAdmin(admin.ModelAdmin):
    list_display = ('reference_number', 'title', 'target_subject', 'reporter', 'state', 'created_at')
    list_filter = ('state', 'created_at')
    search_fields = ('reference_number', 'title', 'allegation', 'target_subject__name')
    inlines = [ReportEvidenceInline]


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
