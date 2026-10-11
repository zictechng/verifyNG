
# payments/admin.py
from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from .models import Plan, PlanFeature, Subscription, Transaction, FreeUsageQuota, SiteSettings


class PlanFeatureInline(admin.TabularInline):
    model = PlanFeature
    extra = 1
    fields = ('feature_text', 'is_included', 'display_order')
    ordering = ['display_order']


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    fields = ('free_check_limit', 'free_check_window_days', 'maintenance_mode')
    readonly_fields = ('updated_at',)

    def has_add_permission(self, request):
        return not SiteSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'price_display', 'interval', 'check_limit_display',
        'is_active', 'is_featured', 'display_order', 'subscriber_count'
    )
    list_editable = ('is_active', 'is_featured', 'display_order')
    list_filter = ('is_active', 'is_featured', 'interval')
    search_fields = ('name', 'slug', 'description')
    prepopulated_fields = {'slug': ('name',)}
    inlines = [PlanFeatureInline]
    fieldsets = (
        ('Plan Details', {
            'fields': ('name', 'slug', 'description', 'is_active', 'is_featured', 'display_order')
        }),
        ('Pricing', {
            'fields': ('price_kobo', 'currency', 'interval')
        }),
        ('Limits', {
            'fields': ('check_limit',),
            'description': 'Set -1 for unlimited checks.'
        }),
        ('Paystack Integration', {
            'fields': ('paystack_plan_code',),
            'classes': ('collapse',),
        }),
    )

    def price_display(self, obj):
        if obj.is_free:
            return format_html('<span style="color:#16a34a;font-weight:600;">Free</span>')
        return format_html('₦{:,.0f}', obj.price_naira)
    price_display.short_description = 'Price'

    def check_limit_display(self, obj):
        if obj.has_unlimited_checks:
            return format_html('<span style="color:#2563eb;">Unlimited</span>')
        return f"{obj.check_limit} checks"
    check_limit_display.short_description = 'Check Limit'

    def subscriber_count(self, obj):
        count = obj.subscriptions.filter(status='active').count()
        return format_html('<strong>{}</strong>', count)
    subscriber_count.short_description = 'Active Subscribers'


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        'user', 'plan', 'status_badge', 'current_period_end',
        'days_remaining_display', 'cancel_at_period_end', 'created_at'
    )
    list_filter = ('status', 'plan', 'cancel_at_period_end')
    search_fields = ('user__username', 'user__email', 'paystack_subscription_code')
    readonly_fields = (
        'id', 'paystack_subscription_code', 'paystack_customer_code',
        'created_at', 'updated_at'
    )
    actions = ['cancel_subscriptions', 'extend_subscriptions_30_days']
    fieldsets = (
        ('Subscription', {
            'fields': ('id', 'user', 'plan', 'status', 'cancel_at_period_end')
        }),
        ('Period', {
            'fields': ('current_period_start', 'current_period_end', 'cancelled_at')
        }),
        ('Paystack', {
            'fields': ('paystack_subscription_code', 'paystack_customer_code'),
            'classes': ('collapse',),
        }),
        ('Meta', {
            'fields': ('created_at', 'updated_at', 'is_active'),
            'classes': ('collapse',),
        }),
    )

    def status_badge(self, obj):
        colours = {
            'active': '#16a34a', 'expired': '#6b7280',
            'cancelled': '#dc2626', 'past_due': '#d97706', 'pending': '#2563eb',
        }
        colour = colours.get(obj.status, '#6b7280')
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;">{}</span>',
            colour, obj.get_status_display().upper()
        )
    status_badge.short_description = 'Status'

    def days_remaining_display(self, obj):
        d = obj.days_remaining
        if d is None:
            return '—'
        if d == 0:
            return format_html('<span style="color:#dc2626;">Expires today</span>')
        return f"{d} days"
    days_remaining_display.short_description = 'Days Left'

    @admin.action(description='Cancel selected subscriptions')
    def cancel_subscriptions(self, request, queryset):
        now = timezone.now()
        updated = queryset.filter(status='active').update(
            status='cancelled', cancelled_at=now, updated_at=now
        )
        self.message_user(request, f"{updated} subscription(s) cancelled.")

    @admin.action(description='Extend selected subscriptions by 30 days')
    def extend_subscriptions_30_days(self, request, queryset):
        from datetime import timedelta
        now = timezone.now()
        count = 0
        for sub in queryset:
            base = max(sub.current_period_end or now, now)
            sub.current_period_end = base + timedelta(days=30)
            sub.status = 'active'
            sub.save(update_fields=['current_period_end', 'status', 'updated_at'])
            count += 1
        self.message_user(request, f"{count} subscription(s) extended by 30 days.")


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = (
        'reference', 'user', 'plan', 'amount_display',
        'status_badge', 'created_at'
    )
    list_filter = ('status', 'currency', 'plan')
    search_fields = ('reference', 'paystack_reference', 'user__username', 'user__email')
    readonly_fields = (
        'id', 'reference', 'paystack_reference', 'amount_kobo',
        'paystack_response', 'created_at', 'updated_at'
    )
    date_hierarchy = 'created_at'
    fieldsets = (
        ('Transaction', {
            'fields': ('id', 'reference', 'paystack_reference', 'status', 'failure_reason')
        }),
        ('Amount', {
            'fields': ('amount_kobo', 'currency')
        }),
        ('Relations', {
            'fields': ('user', 'plan', 'subscription')
        }),
        ('Paystack Response', {
            'fields': ('paystack_response',),
            'classes': ('collapse',),
        }),
        ('Meta', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    def amount_display(self, obj):
        return f"₦{obj.amount_naira:,.0f}"
    amount_display.short_description = 'Amount'

    def status_badge(self, obj):
        colours = {
            'success': '#16a34a', 'pending': '#2563eb',
            'failed': '#dc2626', 'refunded': '#d97706', 'abandoned': '#6b7280',
        }
        colour = colours.get(obj.status, '#6b7280')
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;">{}</span>',
            colour, obj.get_status_display().upper()
        )
    status_badge.short_description = 'Status'

    def has_add_permission(self, request):
        return False  # Transactions are system-generated only


@admin.register(FreeUsageQuota)
class FreeUsageQuotaAdmin(admin.ModelAdmin):
    list_display = ('user', 'checks_used', 'quota_period_start', 'updated_at')
    search_fields = ('user__username', 'user__email')
    readonly_fields = ('updated_at',)
