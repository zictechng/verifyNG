
# employer/admin.py
from django.contrib import admin
from .models import BulkCheckRow, BulkCheckUpload, EmployerProfile, TeamMember


@admin.register(EmployerProfile)
class EmployerProfileAdmin(admin.ModelAdmin):
    list_display = ('company_name', 'user', 'industry', 'is_verified', 'created_at')
    list_filter = ('is_verified', 'is_active')
    search_fields = ('company_name', 'user__username', 'company_rc_number')
    readonly_fields = ('created_at', 'updated_at', 'verified_at')


@admin.register(TeamMember)
class TeamMemberAdmin(admin.ModelAdmin):
    list_display = ('user', 'employer', 'team_role', 'is_active', 'created_at')
    list_filter = ('team_role', 'is_active')
    search_fields = ('user__username', 'employer__company_name')
    readonly_fields = ('created_at', 'updated_at')


class BulkCheckRowInline(admin.TabularInline):
    model = BulkCheckRow
    extra = 0
    readonly_fields = ('row_number', 'full_name', 'phone_number', 'status', 'checked_at')
    can_delete = False
    max_num = 0  # view-only inline


@admin.register(BulkCheckUpload)
class BulkCheckUploadAdmin(admin.ModelAdmin):
    list_display = ('original_filename', 'employer', 'status', 'row_count', 'processed_count', 'created_at')
    list_filter = ('status',)
    search_fields = ('original_filename', 'employer__company_name')
    readonly_fields = ('id', 'created_at', 'updated_at', 'progress_pct')
    inlines = [BulkCheckRowInline]


@admin.register(BulkCheckRow)
class BulkCheckRowAdmin(admin.ModelAdmin):
    list_display = ('upload', 'row_number', 'full_name', 'status', 'checked_at')
    list_filter = ('status',)
    search_fields = ('full_name', 'phone_number')
    readonly_fields = ('created_at', 'updated_at', 'result_data')

