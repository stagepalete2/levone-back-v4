from django.contrib import admin

from apps.shared.config.sites import tenant_admin

from apps.tenant.catalog.models import Product, Cooldown

tenant_admin.register(Product)
tenant_admin.register(Cooldown)