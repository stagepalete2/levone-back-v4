from django.contrib import admin

from apps.shared.config.sites import tenant_admin
from apps.shared.config.mixins import BranchRestrictedAdminMixin
from apps.tenant.catalog.models import Product, Cooldown


class ProductAdmin(BranchRestrictedAdminMixin, admin.ModelAdmin):
    list_display = ('name', 'branch', 'price', 'is_active', 'is_super_prize', 'is_birthday_prize', 'created_at')
    list_filter = ('branch', 'is_active', 'is_super_prize', 'is_birthday_prize')
    search_fields = ('name', 'description')
    list_editable = ('is_active', 'is_super_prize', 'is_birthday_prize', 'price')


class CooldownAdmin(BranchRestrictedAdminMixin, admin.ModelAdmin):
    client_branch_field_name = 'client'
    branch_field_name = None

    list_display = ('client', 'last_activated_at', 'duration', 'is_active')
    search_fields = ('client__client__name', 'client__client__lastname')

    def is_active(self, obj):
        return obj.is_active
    is_active.boolean = True
    is_active.short_description = 'Активен'

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


tenant_admin.register(Product, ProductAdmin)
tenant_admin.register(Cooldown, CooldownAdmin)
