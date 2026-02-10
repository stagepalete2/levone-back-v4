from django.contrib import admin

from apps.shared.config.sites import tenant_admin

from apps.tenant.delivery.models import Delivery

class DeliveryAdmin(admin.ModelAdmin):
	list_display = ('code', 'activated_by', 'duration', 'created_at')

tenant_admin.register(Delivery, DeliveryAdmin)
