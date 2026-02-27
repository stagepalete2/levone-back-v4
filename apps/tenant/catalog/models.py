from django.db import models
from datetime import timedelta
from django.utils.timezone import now
from PIL import Image
from django.core.exceptions import ValidationError
from django.core.files.images import get_image_dimensions

from apps.shared.config.models import TimeStampedModel
from apps.tenant.catalog.utils import product_image_path

def validate_square_image(image):
    """
    Проверяет соотношение сторон без полной загрузки тяжелых библиотек,
    используя встроенный в Django get_image_dimensions.
    """
    if not image:
        return

    width, height = get_image_dimensions(image)
    
    if width and height and width != height:
        raise ValidationError(
            f'Изображение должно быть квадратным (1:1). Загружено: {width}x{height}px.'
        )

class Product(TimeStampedModel):
    name = models.CharField(max_length=200, verbose_name='Название')
    description = models.TextField(verbose_name='Описание')

    image = models.ImageField(
        upload_to=product_image_path,
        verbose_name='Изображение',
        help_text='Формат строго 1:1',
        validators=[validate_square_image] # Валидатор тут надежнее
    )

    price = models.PositiveIntegerField(default=3000, verbose_name='Цена')

    is_active = models.BooleanField(default=True, verbose_name='Опубликовано') 
    is_super_prize = models.BooleanField(default=False, verbose_name='Супер-приз')
    is_birthday_prize = models.BooleanField(
        default=False,
        verbose_name='Приз дня рождения',
        help_text='Если включено — этот товар будет доступен как приз дня рождения (аналог супер-приза, но только для именинников)'
    )

    branch = models.ForeignKey(
        'branch.Branch', 
        on_delete=models.CASCADE, 
        verbose_name='Ресторан',
        related_name='products' # Удобно для получения всех товаров ресторана
    )

    def __str__(self):
        return f"{self.name} ({self.price})"

    class Meta:
        verbose_name = 'Приз'
        verbose_name_plural = 'Призы'

class Cooldown(models.Model):
	client = models.OneToOneField( 
		'branch.ClientBranch', 
		on_delete=models.CASCADE, 
		related_name='catalog_cooldown_client', 
		verbose_name='Клиент'
	)

	last_activated_at = models.DateTimeField(
        verbose_name='Последняя покупка', 
        null=True, 
        blank=True
    )

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
