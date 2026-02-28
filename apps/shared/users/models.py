from django.db import models
from django.contrib.auth.models import AbstractUser

from apps.shared.clients.models import Company

# Create your models here.
class User(AbstractUser):
    company = models.ForeignKey(
        Company, 
        on_delete=models.PROTECT, 
        null=True, 
        blank=True,
        related_name='users',
        verbose_name='Основной тенант'
    )

    companies = models.ManyToManyField(
        Company,
        blank=True,
        related_name='staff_users',
        verbose_name='Доступные тенанты',
        help_text='Пользователь может логиниться и управлять всеми отмеченными тенантами'
    )

    def __str__(self):
        return f"{self.username} ({self.company.name if self.company else 'Глобальный'})"

    class Meta:
        permissions = [
            ('can_view_stats', 'Может просматривать статистику'),
        ]