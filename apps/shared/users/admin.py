from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from apps.shared.config.sites import public_admin # Импорт нашего сайта
from apps.shared.users.models import User
from apps.shared.clients.models import Company, Domain

# Настраиваем UserAdmin для публичной части (создание Компаний и Владельцев)
class GlobalUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ('SaaS Info', {'fields': ('company',)}),
    )
    list_display = ('username', 'company', 'is_staff')

    def delete_queryset(self, request, queryset):
        # Удаляем по одному, чтобы гарантированно срабатывали сигналы (pre_delete)
        for user in queryset:
            user.delete()

public_admin.register(User, GlobalUserAdmin)