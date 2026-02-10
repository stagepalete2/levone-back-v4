from django.db import models

from apps.shared.config.models import TimeStampedModel

class Client(TimeStampedModel):
    vk_user_id = models.PositiveBigIntegerField(
        unique=True, 
        verbose_name='VK ID',
        help_text='Уникальный цифровой ID пользователя ВКонтакте'
    )

    name = models.CharField(max_length=100, verbose_name='Имя', blank=True)
    lastname = models.CharField(max_length=100, verbose_name='Фамилия', blank=True)

    SEX_CHOICES = [
        (0, 'Не указан'),
        (1, 'Женский'),
        (2, 'Мужской'),
    ]
    sex = models.PositiveSmallIntegerField(
        choices=SEX_CHOICES, 
        default=0, 
        verbose_name="Пол"
    )

    @property
    def full_name(self):
        return f'{self.name} {self.lastname}'.strip()

    def __str__(self):
        return self.full_name if self.full_name else str(self.vk_user_id)

    class Meta:
        verbose_name = 'Клиент (ВК)'
        verbose_name_plural = 'Клиенты (ВК)'