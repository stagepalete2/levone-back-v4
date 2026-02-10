from django.contrib import admin

from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from apps.shared.config.sites import tenant_admin
from apps.tenant.branch.models import Branch
from apps.tenant.staff.models import EmployeeProfile

User = get_user_model()

class TenantUser(User):
    class Meta:
        proxy = True
        verbose_name = "Сотрудник"
        verbose_name_plural = "Сотрудники"

# 2. Инлайн профиля (выбор филиалов)
class EmployeeProfileInline(admin.StackedInline):
    model = EmployeeProfile
    can_delete = False
    verbose_name_plural = 'Права доступа к филиалам'
    filter_horizontal = ('branches',)

# 3. Админка пользователя (Изолированная)
class TenantUserAdmin(BaseUserAdmin):
    inlines = [EmployeeProfileInline]
    
    # Скрываем поле company из списков и форм
    list_display = ('username', 'email', 'is_staff', 'get_branches_display')
    
    def get_queryset(self, request):
        # Видим только пользователей ЭТОЙ компании
        qs = super().get_queryset(request)
        return qs.filter(company=request.tenant)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        # Убираем возможность выбрать компанию вручную
        if 'company' in form.base_fields:
            del form.base_fields['company']
        return form

    def save_model(self, request, obj, form, change):
        # Автоматически присваиваем текущую компанию при создании
        if not obj.pk:
            obj.company = request.tenant
            # Обычно сотрудники должны иметь доступ в админку
            obj.is_staff = True 
        
        # Если редактируем, на всякий случай форсируем компанию
        obj.company = request.tenant
        super().save_model(request, obj, form, change)

    def get_branches_display(self, obj):
        if hasattr(obj, 'tenant_profile'):
            branches = obj.tenant_profile.branches.all()
            if branches.exists():
                return ", ".join([b.name for b in branches])
        return "Все (Полный доступ)"
    get_branches_display.short_description = "Филиалы"

# Регистрируем в tenant_admin
tenant_admin.register(TenantUser, TenantUserAdmin)