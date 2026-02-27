# models.py

from django.db import models
from colorfield.fields import ColorField

class RFSegment(models.Model):
    code = models.CharField(max_length=10, unique=True, verbose_name='Код')
    name = models.CharField(max_length=50, verbose_name='Название')
    
    # Границы Recency (Дни)
    recency_min = models.IntegerField(
        default=0, 
        verbose_name="Давность: от (дней)",
        help_text="Нижняя граница последнего визита"
    )
    recency_max = models.IntegerField(
        default=999, 
        verbose_name="Давность: до (дней)",
        help_text="Верхняя граница последнего визита"
    )
    
    # Границы Frequency (Визиты)
    frequency_min = models.IntegerField(
        default=0, 
        verbose_name="Частота: от (визитов)",
        help_text="Минимальное кол-во покупок/посещений"
    )
    frequency_max = models.IntegerField(
        default=999, 
        verbose_name="Частота: до (визитов)",
        help_text="Максимальное кол-во покупок/посещений"
    )

    emoji = models.CharField(max_length=10, verbose_name='Эмодзи')
    color = ColorField(default='#FF0000', verbose_name='Цвет')
    strategy = models.TextField(verbose_name='Маркетинговая стратегия')
    
    # New fields for hints and tracking
    hint = models.TextField(blank=True, null=True, verbose_name="Подсказка для персонала", help_text="Текст подсказки в админке")
    last_campaign_date = models.DateTimeField(blank=True, null=True, verbose_name="Дата последней рассылки")


    class Meta:
        verbose_name = 'Настройка сегмента'
        verbose_name_plural = 'Настройки сегментов'
        ordering = ['-code']

    def __str__(self):
        return f"{self.name} ({self.code})"

class GuestRFScore(models.Model):
    client = models.OneToOneField(
        'branch.ClientBranch', 
        on_delete=models.CASCADE, 
        related_name='rf_score'
    )
    recency_days = models.IntegerField()
    frequency = models.IntegerField()
    r_score = models.PositiveSmallIntegerField() 
    f_score = models.PositiveSmallIntegerField()
    segment = models.ForeignKey(RFSegment, on_delete=models.SET_NULL, null=True)
    calculated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return str(self.client)
    
    class Meta:
        indexes = [
            models.Index(fields=['r_score', 'f_score']),
        ]
        verbose_name = 'RF-метрика гостя'
        verbose_name_plural = 'RF-метрики гостей'
    

class RFMigrationLog(models.Model):
    client = models.ForeignKey('branch.ClientBranch', on_delete=models.CASCADE)
    # Добавлен SET_NULL и null=True, чтобы не терять логи при изменении справочника
    from_segment = models.ForeignKey(RFSegment, related_name='migrations_from', on_delete=models.SET_NULL, null=True)
    to_segment = models.ForeignKey(RFSegment, related_name='migrations_to', on_delete=models.SET_NULL, null=True)
    migrated_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return str(self.client)

    class Meta:
        verbose_name = 'RF Логи-миграции'
        verbose_name_plural = 'RF Логи-миграции'

class RFSettings(models.Model):
    """Оставляем только период анализа, пороги ушли в RFSegment"""
    branch = models.OneToOneField('branch.Branch', on_delete=models.CASCADE, verbose_name='Ресторан')
    analysis_period = models.IntegerField(default=365, verbose_name='Период анализа')

    stats_reset_date = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Дата обнуления статистики',
        help_text=(
            'Если задана — RFM-анализ и общая статистика учитывают '
            'ТОЛЬКО данные после этой даты. '
            'Балансы монет, задания и инвентарь НЕ затрагиваются.'
        ),
    )

    def __str__(self):
        return str(self.branch)

    class Meta:
        verbose_name = 'RF - Настройки'
        verbose_name_plural = 'RF - Настройки'
    

class BranchSegmentSnapshot(models.Model):
    branch = models.ForeignKey('branch.Branch', on_delete=models.CASCADE)
    segment = models.ForeignKey('stats.RFSegment', on_delete=models.CASCADE)
    guests_count = models.PositiveIntegerField(default=0)
    # Поле date позволит нам выбирать данные за конкретный день
    date = models.DateField(auto_now_add=True) 
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # Теперь уникальность по дате, филиалу и сегменту
        unique_together = ('branch', 'segment', 'date')
        ordering = ['-date']

    def __str__(self):
        return f"{self.date} | {self.branch.name} | {self.segment.code}: {self.guests_count}"