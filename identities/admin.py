from django.contrib import admin
from .models import SubjectEntity, Identifier, BusinessProfile

@admin.register(SubjectEntity)
class SubjectEntityAdmin(admin.ModelAdmin):
    list_display = ('name', 'type', 'is_active', 'created_at')
    list_filter = ('type', 'is_active')
    search_fields = ('name',)

@admin.register(Identifier)
class IdentifierAdmin(admin.ModelAdmin):
    list_display = ('subject', 'type', 'created_at')
    list_filter = ('type',)
    search_fields = ('subject__name',)

@admin.register(BusinessProfile)
class BusinessProfileAdmin(admin.ModelAdmin):
    list_display = ('official_name', 'registration_number', 'is_verified_business', 'created_at')
    list_filter = ('is_verified_business',)
    search_fields = ('official_name', 'registration_number')