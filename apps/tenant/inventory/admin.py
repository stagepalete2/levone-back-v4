from django.contrib import admin

from apps.shared.config.sites import tenant_admin

from apps.tenant.inventory.models import Inventory, SuperPrize, Cooldown

tenant_admin.register(Inventory)
tenant_admin.register(SuperPrize)
tenant_admin.register(Cooldown)