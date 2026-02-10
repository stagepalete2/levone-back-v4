class BranchRestrictedAdminMixin:
    """
    Фильтрует QuerySet и Dropdown-ы в зависимости от EmployeeProfile.
    """
    branch_field_name = 'branch'

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        user = request.user

        # 1. Суперюзер видит все
        if user.is_superuser:
            return qs

        # 2. Проверяем профиль внутри тенанта
        if not hasattr(user, 'tenant_profile'):
            # Нет профиля = видит всё (или ничего, зависит от политики. Сейчас - всё).
            return qs

        user_branches = user.tenant_profile.branches.all()

        # 3. Если бранчи не выбраны = видит всё
        if not user_branches.exists():
            return qs

        # 4. Фильтруем
        return qs.filter(**{f"{self.branch_field_name}__in": user_branches})

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == self.branch_field_name:
            user = request.user
            if not user.is_superuser and hasattr(user, 'tenant_profile'):
                user_branches = user.tenant_profile.branches.all()
                if user_branches.exists():
                    kwargs["queryset"] = user_branches
        
        return super().formfield_for_foreignkey(db_field, request, **kwargs)