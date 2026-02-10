from django.contrib import admin

from apps.shared.config.sites import tenant_admin
from apps.shared.config.mixins import BranchRestrictedAdminMixin
from apps.tenant.game.models import DailyCode, Cooldown, ClientAttempt


class ClientAttemptAdmin(BranchRestrictedAdminMixin, admin.ModelAdmin):
    client_branch_field_name = 'client'
    branch_field_name = None

    list_display = ('client', 'served_by', 'created_at')
    list_filter = ('client__branch', 'created_at')
    search_fields = (
        'client__client__name', 'client__client__lastname',
        'served_by__client__name', 'served_by__client__lastname'
    )
    readonly_fields = ('created_at', 'served_by', 'client')

    def get_queryset(self, request):
        qs = super(admin.ModelAdmin, self).get_queryset(request)
        user = request.user
        if user.is_superuser:
            return qs
        if hasattr(user, 'tenant_profile'):
            user_branches = user.tenant_profile.branches.all()
            if user_branches.exists():
                return qs.filter(client__branch__in=user_branches)
        return qs


class DailyCodeAdmin(BranchRestrictedAdminMixin, admin.ModelAdmin):
    list_display = ('code', 'date', 'branch', 'created_at')
    list_filter = ('branch', 'date')
    search_fields = ('code',)


class CooldownAdmin(BranchRestrictedAdminMixin, admin.ModelAdmin):
    client_branch_field_name = 'client'
    branch_field_name = None

    list_display = ('client', 'last_activated_at', 'duration', 'is_active_display')
    search_fields = ('client__client__name', 'client__client__lastname')

    def is_active_display(self, obj):
        return obj.is_active
    is_active_display.boolean = True
    is_active_display.short_description = 'Активен'

    def get_queryset(self, request):
        qs = super(admin.ModelAdmin, self).get_queryset(request)
        user = request.user
        if user.is_superuser:
            return qs
        if hasattr(user, 'tenant_profile'):
            user_branches = user.tenant_profile.branches.all()
            if user_branches.exists():
                return qs.filter(client__branch__in=user_branches)
        return qs


tenant_admin.register(ClientAttempt, ClientAttemptAdmin)
tenant_admin.register(DailyCode, DailyCodeAdmin)
tenant_admin.register(Cooldown, CooldownAdmin)
