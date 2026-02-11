from django.db import models
from django.conf import settings

from apps.tenant.branch.models import Branch

class EmployeeProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='tenant_profile',
        verbose_name='Пользователь'
    )
    branches = models.ManyToManyField(
        Branch,
        blank=True,
        related_name='employees',
        verbose_name='Доступные ресторан'
    )

    def __str__(self):
        return f"Profile: {self.user.username}"