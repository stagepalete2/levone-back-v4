from django.db import models
from datetime import timedelta
from django.utils.timezone import now

from apps.shared.config.models import TimeStampedModel

class Inventory(TimeStampedModel):
    SOURCE_CHOICES = [
        ('BUY', 'Покупка'),
        ('SUPERPRIZE', 'Супер приз'),
        ('BIRTHDAY_PRIZE', 'Приз дня рождения'),
    ]

    client = models.ForeignKey(
        'branch.ClientBranch',
        on_delete=models.CASCADE,
        related_name='inventory_items', # Исправил transactions -> items (логичнее)
        verbose_name='Клиент'
    )

    product = models.ForeignKey(
        'catalog.Product',
        on_delete=models.PROTECT, # ЗАЩИТА ОТ УДАЛЕНИЯ ИСТОРИИ
        verbose_name='Продукт'
    )

    acquired_from = models.CharField(max_length=20, choices=SOURCE_CHOICES, verbose_name='Источник')

    duration = models.DurationField(
        default=timedelta(minutes=40),
        help_text="Сколько действует эффект после активации",
        verbose_name='Длительность действия'
    )

    description = models.CharField(max_length=255, blank=True, null=True, verbose_name='Описание')
    
    # Если null - предмет лежит в инвентаре. Если есть дата - он активирован и таймер тикает.
    activated_at = models.DateTimeField(null=True, blank=True, verbose_name='Дата активации')

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Предмет инвентаря'
        verbose_name_plural = 'Инвентарь'

    def __str__(self):
        # Убрал сложную цепочку имен для оптимизации, либо надо делать prefetch
        return f"{self.product.name} ({self.get_status_display()})"
    
    @property
    def status(self):
        if not self.activated_at:
            return 'IN_STOCK' # В наличии
        elif now() < self.activated_at + self.duration:
            return 'ACTIVE' # Действует
        else:
            return 'EXPIRED' # Использовано/Истекло

    def get_status_display(self):
        statuses = {
            'IN_STOCK': 'В инвентаре',
            'ACTIVE': 'Активен',
            'EXPIRED': 'Использован'
        }
        return statuses.get(self.status, 'Unknown')

    @property
    def is_active(self):
        return self.status == 'ACTIVE'


class SuperPrize(TimeStampedModel):
    SOURCE_CHOICES = [
        ('GAME', 'Игра'),
        ('MANUAL', 'В ручную'),
        ('BIRTHDAY', 'День Рождения'),
    ]

    client = models.ForeignKey(
        'branch.ClientBranch',
        on_delete=models.CASCADE,
        related_name='superprizes',
        verbose_name='Клиент'
    )

    acquired_from = models.CharField(
        max_length=20,
        choices=SOURCE_CHOICES,
        verbose_name='Источник'
    )

    product = models.ForeignKey(
        'catalog.Product',
        on_delete=models.SET_NULL, # Если приз удалят из каталога, история останется
        verbose_name='Выбранный предмет',
        blank=True,
        null=True
    )

    activated_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Дата получения/использования'
    )
    
    # УДАЛЕНО поле is_activated как избыточное

    def __str__(self):
        product_name = self.product.name if self.product else "Удаленный приз"
        return f"Суперприз: {product_name}"
    
    @property
    def is_used(self):
        return bool(self.activated_at)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Супер Приз Гостя'
        verbose_name_plural = 'Супер Призы Гостей'


class Cooldown(models.Model):
	client = models.OneToOneField( 
		'branch.ClientBranch', 
		on_delete=models.CASCADE, 
		related_name='inventory_cooldown_client', 
		verbose_name='Клиент'
	)

	last_activated_at = models.DateTimeField(verbose_name='Последняя активация', null=True, blank=True)

	duration = models.DurationField(default=timedelta(hours=18), verbose_name='Длительность')

	@property
	def time_left(self):
		if not self.last_activated_at:
			return timedelta(0)
		
		end_time = self.last_activated_at + self.duration
		remaining = end_time - now()
		
		return max(remaining, timedelta(0))

	@property
	def is_active(self):
		return self.time_left > timedelta(0)

	def __str__(self):
		return f'Кулдаун {self.client}'

	class Meta:
		verbose_name= 'Перезарядка'
		verbose_name_plural = 'Перезарядки'