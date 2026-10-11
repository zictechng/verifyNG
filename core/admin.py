from django.contrib import admin
from core.models import SiteConfiguration


@admin.register(SiteConfiguration)
class SiteConfigurationAdmin(admin.ModelAdmin):
    list_display = ('site_name', 'base_url', 'support_email', 'updated_at')

    fieldsets = (
        ('Branding & Identity', {
            'description': (
                'These values appear in the navigation bar, browser tab, '
                'email headers, and all generated documents.'
            ),
            'fields': ('site_name', 'site_tagline', 'logo', 'favicon'),
        }),
        ('URLs & Contact', {
            'description': (
                'base_url is used to build links in emails. '
                'Update this to your live domain before going to production.'
            ),
            'fields': ('base_url', 'support_email', 'company_reg_number', 'company_address'),
        }),
        ('Social Media Links', {
            'description': 'Leave a field blank to hide that link from the email and website footer.',
            'fields': (
                'twitter_url', 'facebook_url',
                'instagram_url', 'linkedin_url', 'youtube_url', 'whatsapp_number',
            ),
            'classes': ('collapse',),
        }),
        ('Footer', {
            'fields': ('footer_text',),
        }),
    )

    def has_add_permission(self, request):
        return not SiteConfiguration.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
