from django.contrib import admin

from apps.shared.config.sites import tenant_admin
from apps.shared.config.mixins import BranchRestrictedAdminMixin
from apps.tenant.delivery.models import Delivery


class DeliveryAdmin(BranchRestrictedAdminMixin, admin.ModelAdmin):
    list_display = ('code', 'branch', 'order_source', 'activated_by', 'duration', 'created_at')
    list_filter = ('branch', 'order_source')
    search_fields = ('code',)
    readonly_fields = ('created_at', 'order_source')


tenant_admin.register(Delivery, DeliveryAdmin)