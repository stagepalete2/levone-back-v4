from django.contrib import admin

from apps.shared.config.sites import tenant_admin

from apps.tenant.game.models import DailyCode, Cooldown, ClientAttempt

class ClientAttemptAdmin(admin.ModelAdmin):
    list_display = ('client', 'served_by', 'created_at')
    list_filter = ('served_by', 'created_at')
    search_fields = ('client__client__name', 'client__client__lastname', 'served_by__client__name', 'served_by__client__lastname')
    readonly_fields = ('created_at', 'served_by', 'client')

class DailyCodeAdmin(admin.ModelAdmin):
    list_display = ('code', 'date', 'created_at')
    list_filter = ('date', 'created_at')
    search_fields = ('code',)

class CooldownAdmin(admin.ModelAdmin):
    list_display = ('client', 'last_activated_at')
    list_filter = ('last_activated_at',)
    search_fields = ('client__client__name', 'client__client__lastname')

tenant_admin.register(ClientAttempt, ClientAttemptAdmin)
tenant_admin.register(DailyCode, DailyCodeAdmin)
tenant_admin.register(Cooldown, CooldownAdmin)