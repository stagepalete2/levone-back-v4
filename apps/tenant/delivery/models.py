from django.db import models
from datetime import timedelta

from apps.shared.config.models import TimeStampedModel

class Delivery(TimeStampedModel):
	code = models.CharField(max_length=222, verbose_name='Уникальный код', unique=True)
	branch = models.ForeignKey('branch.Branch', on_delete=models.CASCADE, verbose_name='Ресторан')
	activated_by = models.ForeignKey('branch.ClientBranch', on_delete=models.CASCADE, verbose_name='Активировано пользователем', null=True, blank=True)

	duration = models.DurationField(default=timedelta(hours=5), verbose_name='Длительность')

	def __str__(self):
		return f'{self.code} - {self.created_at}'

	class Meta:
		verbose_name = 'Доставка'
		verbose_name_plural = 'Коды доставки'