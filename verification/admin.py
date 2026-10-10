from django.contrib import admin
from .models import VerificationRequest, VerificationResult


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
