from django.db import models
from datetime import timedelta
from django.utils.timezone import now

from apps.shared.config.models import TimeStampedModel

class Quest(TimeStampedModel):
    name = models.CharField(max_length=1000, verbose_name='Название')
    description = models.TextField(verbose_name='Описание задания')

    reward = models.PositiveIntegerField(default=150, verbose_name='Вознаграждение')
    
    branch = models.ForeignKey(
        'branch.Branch', 
        on_delete=models.CASCADE, 
        related_name='quests', # Удобно получать все квесты ресторана
        verbose_name='Ресторан'
    )

    is_active = models.BooleanField(default=True, verbose_name='Активно') # Лучше скрывать, чем удалять

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = 'Задание'
        verbose_name_plural = 'Задания'


class QuestSubmit(TimeStampedModel):
    client = models.ForeignKey(
        'branch.ClientBranch',
        on_delete=models.CASCADE,
        related_name='quest_submissions',
        verbose_name='Клиент'
    )

    quest = models.ForeignKey(
        Quest,
        on_delete=models.PROTECT,
        related_name='submissions',
        verbose_name='Задание'
    )

    is_complete = models.BooleanField(
        default=False,
        verbose_name='Завершено'
    )

    activated_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Дата активации задания'
    )

    duration = models.DurationField(
        default=timedelta(minutes=40),
        verbose_name='Время для выполнения'
    )

    served_by = models.ForeignKey(
        'branch.ClientBranch', 
        on_delete=models.SET_NULL,
        blank=True, 
        null=True, 
        verbose_name='Пригласил выполнить (Сотрудник)', 
        related_name='served_quests'
    )

    @property
    def time_left(self):
        if not self.activated_at:
            return timedelta(0)

        end_time = self.activated_at + self.duration
        remaining = end_time - now()

        return max(remaining, timedelta(0))
    
    def __str__(self):
        # self.type работает, так как это property
        return f"{self.client} — {self.quest.name} ({self.type})"
    
    @property
    def type(self):
        return 'Завершено' if self.is_complete else 'В процессе'

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Выполнение квеста'
        verbose_name_plural = 'Выполнения квестов'


class Cooldown(models.Model):
    client = models.OneToOneField( 
        'branch.ClientBranch', 
        on_delete=models.CASCADE, 
        related_name='quest_cooldown_client', 
        verbose_name='Клиент'
    )

    last_activated_at = models.DateTimeField(
        verbose_name='Последняя покупка', 
        null=True, 
        blank=True # <--- Добавь это
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
        related_name='daily_codes_quest',
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