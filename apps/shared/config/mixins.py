from django.contrib import admin


class BranchRestrictedAdminMixin:
    """
    Фильтрует QuerySet и Dropdown-ы в зависимости от EmployeeProfile.

    Поддерживает три сценария:
    1. Модель имеет FK на Branch напрямую (branch_field_name = 'branch')
    2. Модель имеет FK на ClientBranch, у которого есть FK на Branch
       (branch_field_name = 'client__branch' или указать client_branch_field_name)
    3. Модель имеет FK на Company (company_field_name = 'company')

    Настройки:
    - branch_field_name: имя поля FK на Branch (или путь через __)
    - client_branch_field_name: имя поля FK на ClientBranch (если фильтр через ClientBranch)
    - company_field_name: имя поля FK на Company (для фильтрации по Company)
    """
    branch_field_name = 'branch'          # FK на Branch
    client_branch_field_name = None       # FK на ClientBranch (если есть)
    company_field_name = None             # FK на Company (если есть)

    def _get_user_branches(self, user):
        """Возвращает queryset бранчей пользователя или None если полный доступ."""
        if user.is_superuser:
            return None
        if not hasattr(user, 'tenant_profile'):
            return None
        user_branches = user.tenant_profile.branches.all()
        if not user_branches.exists():
            return None  # Нет привязки = владелец компании, видит всё
        return user_branches

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        user = request.user

        user_branches = self._get_user_branches(user)
        if user_branches is None:
            return qs

        # Фильтрация через ClientBranch
        if self.client_branch_field_name:
            return qs.filter(
                **{f"{self.client_branch_field_name}__branch__in": user_branches}
            )

        # Фильтрация через прямое поле Branch
        if self.branch_field_name:
            return qs.filter(**{f"{self.branch_field_name}__in": user_branches})

        return qs

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        user = request.user
        user_branches = self._get_user_branches(user)

        if user_branches is not None:
            # Ограничиваем выбор Branch
            if db_field.name == self.branch_field_name:
                kwargs["queryset"] = user_branches

            # Ограничиваем выбор ClientBranch
            if self.client_branch_field_name and db_field.name == self.client_branch_field_name:
                from apps.tenant.branch.models import ClientBranch
                kwargs["queryset"] = ClientBranch.objects.filter(branch__in=user_branches)

        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        user = request.user
        user_branches = self._get_user_branches(user)

        if user_branches is not None:
            if db_field.name == 'specific_clients':
                from apps.tenant.branch.models import ClientBranch
                kwargs["queryset"] = ClientBranch.objects.filter(branch__in=user_branches)

        return super().formfield_for_manytomany(db_field, request, **kwargs)
