from django.db import models
from datetime import timedelta
from django.utils.timezone import now
from django.utils import timezone

from apps.shared.config.models import TimeStampedModel


class Cooldown(models.Model):
    client = models.OneToOneField( 
        'branch.ClientBranch', 
        on_delete=models.CASCADE, 
        related_name='game_cooldown_client', 
        verbose_name='Клиент'
    )

    last_activated_at = models.DateTimeField(
        verbose_name='Последняя игра', 
        null=True, 
        blank=True # <--- Обязательно добавь
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


class DailyCode(TimeStampedModel):
    date = models.DateField(verbose_name='Дата', default=now)
    code = models.CharField(max_length=20, verbose_name='Код дня')

    branch = models.ForeignKey(
        'branch.Branch', 
        on_delete=models.CASCADE, 
        related_name='daily_codes_game',
        verbose_name='Ресторан'
    )

    def save(self, *args, **kwargs):
        self.code = self.code.upper().strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.date}: {self.code} ({self.branch})"

    class Meta:
        verbose_name='Код дня'
        verbose_name_plural = 'Коды дня'
        ordering = ['-date']
        # Отличная защита от дублей
        unique_together = ('branch', 'date')


class ClientAttempt(TimeStampedModel):
    client = models.ForeignKey(
        'branch.ClientBranch', 
        on_delete=models.CASCADE, 
        related_name='game_attempts',
        db_index=True,
        verbose_name='Гость'
    )

    served_by = models.ForeignKey(
        'branch.ClientBranch', 
        on_delete=models.SET_NULL,
        blank=True, 
        null=True, 
        verbose_name='Кем приглашен (Сотрудник)',
        related_name='served_games'
    )

    def __str__(self):
        local_time = timezone.localtime(self.created_at)
        return f'{local_time.strftime("%d.%m %H:%M")} - {self.client}'
    
    class Meta:
        verbose_name = 'История игры'
        verbose_name_plural = 'История игр'
        ordering = ['-created_at']