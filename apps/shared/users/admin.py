from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django import forms

from apps.shared.config.sites import public_admin # Импорт нашего сайта
from apps.shared.users.models import User
from apps.shared.clients.models import Company, Domain


class GlobalUserChangeForm(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = User


class GlobalUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User


# Настраиваем UserAdmin для публичной части (создание Компаний и Владельцев)
class GlobalUserAdmin(UserAdmin):
    form = GlobalUserChangeForm
    add_form = GlobalUserCreationForm

    fieldsets = UserAdmin.fieldsets + (
        ('SaaS Info', {'fields': ('company', 'companies',)}),
    )
    list_display = ('username', 'company', 'is_staff', 'is_superuser')
    filter_horizontal = ('groups', 'user_permissions', 'companies',)

    def delete_queryset(self, request, queryset):
        # Удаляем по одному, чтобы гарантированно срабатывали сигналы (pre_delete)
        for user in queryset:
            user.delete()

    def has_delete_permission(self, request, obj=None):
        """Запрещаем is_staff (не superuser) удалять superuser-ов."""
        if obj is not None and obj.is_superuser and not request.user.is_superuser:
            return False
        return super().has_delete_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        """Запрещаем is_staff (не superuser) редактировать superuser-ов."""
        if obj is not None and obj.is_superuser and not request.user.is_superuser:
            return False
        return super().has_change_permission(request, obj)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # is_staff (не superuser) не видит superuser-ов в списке
        if not request.user.is_superuser:
            qs = qs.filter(is_superuser=False)
        return qs


public_admin.register(User, GlobalUserAdmin)