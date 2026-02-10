from django.contrib import admin

from apps.shared.config.sites import tenant_admin
from apps.shared.config.mixins import BranchRestrictedAdminMixin
from apps.tenant.inventory.models import Inventory, SuperPrize, Cooldown


class InventoryAdmin(BranchRestrictedAdminMixin, admin.ModelAdmin):
    client_branch_field_name = 'client'
    branch_field_name = None

    list_display = ('product', 'client', 'acquired_from', 'status_display', 'activated_at', 'created_at')
    list_filter = ('acquired_from', 'client__branch')
    search_fields = ('product__name', 'client__client__name', 'client__client__lastname')
    readonly_fields = ('created_at',)

    def status_display(self, obj):
        return obj.get_status_display()
    status_display.short_description = 'Статус'

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


class SuperPrizeAdmin(BranchRestrictedAdminMixin, admin.ModelAdmin):
    client_branch_field_name = 'client'
    branch_field_name = None

    list_display = ('client', 'product', 'acquired_from', 'is_used_display', 'activated_at', 'created_at')
    list_filter = ('acquired_from', 'client__branch')
    search_fields = ('client__client__name', 'client__client__lastname', 'product__name')

    def is_used_display(self, obj):
        return obj.is_used
    is_used_display.boolean = True
    is_used_display.short_description = 'Использован'

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


tenant_admin.register(Inventory, InventoryAdmin)
tenant_admin.register(SuperPrize, SuperPrizeAdmin)
tenant_admin.register(Cooldown, CooldownAdmin)
