from django.contrib import admin

from apps.shared.config.sites import tenant_admin
from apps.shared.config.mixins import BranchRestrictedAdminMixin
from apps.tenant.delivery.models import Delivery


class DeliveryAdmin(BranchRestrictedAdminMixin, admin.ModelAdmin):
    list_display = ('code', 'branch', 'activated_by', 'duration', 'created_at')
    list_filter = ('branch',)
    search_fields = ('code',)
    readonly_fields = ('created_at',)


tenant_admin.register(Delivery, DeliveryAdmin)
