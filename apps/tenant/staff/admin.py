from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django import forms

from apps.shared.config.sites import tenant_admin
from apps.tenant.branch.models import Branch
from apps.tenant.staff.models import EmployeeProfile

User = get_user_model()


class TenantUser(User):
    class Meta:
        proxy = True
        verbose_name = "Сотрудник"
        verbose_name_plural = "Сотрудники"


class EmployeeProfileInline(admin.StackedInline):
    model = EmployeeProfile
    can_delete = False
    verbose_name = 'Права доступа'
    verbose_name_plural = 'Права доступа к филиалам'
    filter_horizontal = ('branches',)

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        """Ограничиваем выбор филиалов только теми, к которым имеет доступ текущий пользователь."""
        if db_field.name == 'branches':
            user = request.user
            if not user.is_superuser and hasattr(user, 'tenant_profile'):
                user_branches = user.tenant_profile.branches.all()
                if user_branches.exists():
                    kwargs['queryset'] = user_branches
        return super().formfield_for_manytomany(db_field, request, **kwargs)


class TenantUserAdmin(BaseUserAdmin):
    inlines = [EmployeeProfileInline]

    list_display = ('username', 'email', 'first_name', 'last_name', 'is_staff', 'is_active', 'get_branches_display')
    list_filter = ('is_active', 'is_staff')
    search_fields = ('username', 'email', 'first_name', 'last_name')

    def get_fieldsets(self, request, obj=None):
        """
        Иерархия прав:
        - Суперюзер видит всё
        - Владелец компании (без привязки к branch) может управлять is_staff, groups, permissions
        - Branch-пользователь может создавать подчинённых, но НЕ может давать больше прав чем у него
        """
        user = request.user

        # 1. Если суперюзер - отдаем стандартное поведение (и add, и change)
        if user.is_superuser:
            return super().get_fieldsets(request, obj)

        # 2. РЕЖИМ СОЗДАНИЯ (obj is None)
        if not obj:
            # Возвращаем поля для создания. 
            # Можно использовать self.add_fieldsets (стандартные) или свои кастомные.
            return [
                (None, {
                    'classes': ('wide',),
                    'fields': ('username', 'email', 'password1', 'password2'), # Добавил username, он обычно обязателен
                })
            ]

        # 3. РЕЖИМ РЕДАКТИРОВАНИЯ (obj существует)
        
        # Базовые поля для всех при редактировании
        fieldsets = [
            (None, {'fields': ('username', 'password')}),
            ('Персональные данные', {'fields': ('first_name', 'last_name', 'email')}),
        ]

        # Логика разделения прав
        if not self._user_has_branch_restriction(user):
            # Владелец компании
            fieldsets.append(
                ('Статус', {'fields': ('is_active', 'is_staff')}),
            )
            fieldsets.append(
                ('Права', {
                    'fields': ('groups', 'user_permissions'),
                    'classes': ('collapse',),
                }),
            )
        else:
            # Branch-пользователь
            fieldsets.append(
                ('Статус', {'fields': ('is_active', 'is_staff')}),
            )
            # Если нужно показывать права, но ограничить выбор - это делается в get_form, 
            # но здесь мы просто отображаем поля
            fieldsets.append(
                ('Права', {
                    'fields': ('groups', 'user_permissions'),
                    'classes': ('collapse',),
                }),
            )

        return fieldsets

    def get_queryset(self, request):
        """
        Фильтрация списка пользователей:
        - Суперюзер: все пользователи
        - Владелец компании: только пользователи этой компании
        - Branch-пользователь: только пользователи его бранчей + он сам
        """
        qs = super().get_queryset(request)
        user = request.user

        if user.is_superuser:
            return qs.filter(company=request.tenant)

        # Фильтруем по компании текущего тенанта
        qs = qs.filter(company=request.tenant)

        # Branch-пользователь видит только пользователей своих бранчей
        if self._user_has_branch_restriction(user):
            user_branches = user.tenant_profile.branches.all()
            # Показываем пользователей, чьи бранчи пересекаются с нашими
            qs = qs.filter(
                tenant_profile__branches__in=user_branches
            ).distinct()

        return qs

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        user = request.user

        # Убираем поле company — оно ставится автоматически
        if 'company' in form.base_fields:
            del form.base_fields['company']

        # Ограничиваем permissions и groups только теми, что есть у текущего пользователя
        if not user.is_superuser:
            if 'user_permissions' in form.base_fields:
                form.base_fields['user_permissions'].queryset = user.user_permissions.all()
            if 'groups' in form.base_fields:
                form.base_fields['groups'].queryset = user.groups.all()

        return form

    def save_model(self, request, obj, form, change):
        """Автоматически присваиваем компанию текущего тенанта."""
        obj.company = request.tenant
        if not change:
            obj.is_staff = True
        super().save_model(request, obj, form, change)

    def has_change_permission(self, request, obj=None):
        """Нельзя редактировать суперюзеров и тех, кто выше по иерархии."""
        if obj is not None:
            user = request.user
            # Никто кроме суперюзера не может редактировать суперюзера
            if obj.is_superuser and not user.is_superuser:
                return False
            # Branch-пользователь не может редактировать владельца компании
            if self._user_has_branch_restriction(user) and not self._user_has_branch_restriction(obj):
                return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        """Нельзя удалять суперюзеров и тех, кто выше."""
        if obj is not None:
            user = request.user
            if obj.is_superuser and not user.is_superuser:
                return False
            if self._user_has_branch_restriction(user) and not self._user_has_branch_restriction(obj):
                return False
            # Нельзя удалить самого себя
            if obj.pk == user.pk:
                return False
        return super().has_delete_permission(request, obj)

    def get_branches_display(self, obj):
        if hasattr(obj, 'tenant_profile'):
            branches = obj.tenant_profile.branches.all()
            if branches.exists():
                return ", ".join([b.name for b in branches])
        return "Все (Владелец)"
    get_branches_display.short_description = "Филиалы"

    @staticmethod
    def _user_has_branch_restriction(user):
        """Проверяет, привязан ли пользователь к конкретным бранчам."""
        if user.is_superuser:
            return False
        if hasattr(user, 'tenant_profile'):
            return user.tenant_profile.branches.exists()
        return False


tenant_admin.register(TenantUser, TenantUserAdmin)
