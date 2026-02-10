from django.contrib import admin

from apps.shared.config.sites import tenant_admin
from apps.shared.config.mixins import BranchRestrictedAdminMixin
from apps.tenant.quest.models import Quest, QuestSubmit, Cooldown, DailyCode


class QuestAdmin(BranchRestrictedAdminMixin, admin.ModelAdmin):
    list_display = ('name', 'branch', 'reward', 'is_active', 'created_at')
    list_filter = ('branch', 'is_active')
    search_fields = ('name', 'description')
    list_editable = ('is_active', 'reward')


class QuestSubmitAdmin(BranchRestrictedAdminMixin, admin.ModelAdmin):
    client_branch_field_name = 'client'
    branch_field_name = None

    list_display = ('client', 'quest', 'is_complete', 'activated_at', 'served_by', 'created_at')
    list_filter = ('is_complete', 'quest__branch')
    search_fields = ('client__client__name', 'client__client__lastname', 'quest__name')
    readonly_fields = ('created_at',)

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
    search_fields = ('client__client__name',)

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


class DailyCodeAdmin(BranchRestrictedAdminMixin, admin.ModelAdmin):
    list_display = ('code', 'date', 'branch', 'created_at')
    list_filter = ('branch', 'date')
    search_fields = ('code',)


tenant_admin.register(Quest, QuestAdmin)
tenant_admin.register(QuestSubmit, QuestSubmitAdmin)
tenant_admin.register(Cooldown, CooldownAdmin)
tenant_admin.register(DailyCode, DailyCodeAdmin)
