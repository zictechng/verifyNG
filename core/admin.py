
from django.contrib import admin
from core.models import SiteConfiguration


@admin.register(SiteConfiguration)
class SiteConfigurationAdmin(admin.ModelAdmin):
    list_display = ('site_name', 'site_tagline', 'updated_at')
    fieldsets = (
        ('Branding & Identity', {
            'fields': ('site_name', 'site_tagline', 'logo', 'favicon')
        }),
        ('Footer & Disclaimers', {
            'fields': ('footer_text',)
        }),
    )

    def has_add_permission(self, request):
        return not SiteConfiguration.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

