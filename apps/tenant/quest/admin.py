from django.contrib import admin

from apps.shared.config.sites import tenant_admin

from apps.tenant.quest.models import Quest, QuestSubmit,Cooldown, DailyCode

tenant_admin.register(Quest)
tenant_admin.register(QuestSubmit)
tenant_admin.register(Cooldown)
tenant_admin.register(DailyCode)