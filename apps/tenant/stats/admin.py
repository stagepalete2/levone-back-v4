from django.contrib import admin

from apps.shared.config.sites import tenant_admin

from apps.tenant.stats.models import RFSegment, RFSettings

tenant_admin.register(RFSegment)
tenant_admin.register(RFSettings)