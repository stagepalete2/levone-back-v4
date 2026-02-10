# mailing/models.py
from django.db import models
from django.utils import timezone

from apps.tenant.branch.models import ClientBranch
from apps.tenant.stats.models import RFSegment 
from apps.shared.config.models import TimeStampedModel

class VKConnection(TimeStampedModel):
    """Настройки подключения группы ВК для конкретного тенанта"""
    group_id = models.CharField(max_length=50, verbose_name="ID Группы ВК")
    access_token = models.TextField(verbose_name="Access Token (Long/Group)")
    
    class Meta:
        verbose_name = "Настройки ВК"
        verbose_name_plural = "Настройки ВК"

    @property
    def raw_token(self):
        """Возвращает расшифрованный токен"""
        return self._decrypt_token(self.access_token)

    def save(self, *args, **kwargs):
        # Если токен изменился или новый — шифруем
        # Простая проверка: если токен не похож на Fernet (не начинается на gAAAA), шифруем
        if self.access_token and not self.access_token.startswith('gAAAA'):
            self.access_token = self._encrypt_token(self.access_token)
        super().save(*args, **kwargs)

    def _get_fernet(self):
        import base64
        from cryptography.fernet import Fernet
        from django.conf import settings
        
        # Деривация ключа из SECRET_KEY (нужен 32-байтовый url-safe base64)
        # Берем первые 32 байта хеша или просто паддим
        key = str(settings.SECRET_KEY).encode()[:32].ljust(32, b'0')
        fernet_key = base64.urlsafe_b64encode(key)
        return Fernet(fernet_key)

    def _encrypt_token(self, text):
        if not text: return ""
        f = self._get_fernet()
        return f.encrypt(text.encode()).decode()

    def _decrypt_token(self, encrypted):
        if not encrypted: return ""
        try:
            f = self._get_fernet()
            return f.decrypt(encrypted.encode()).decode()
        except Exception:
            # Если не удалось расшифровать (например, старый простой токен), возвращаем как есть
            return encrypted

class MailingCampaign(TimeStampedModel):
    """Сущность рассылки (массовая или ручная)"""
    STATUS_CHOICES = [
        ('draft', 'Черновик'),
        ('scheduled', 'Запланировано'),
        ('completed', 'Завершено'),
    ]
    
    title = models.CharField(max_length=100, verbose_name="Название рассылки")
    text = models.TextField(verbose_name="Текст сообщения")
    image = models.ImageField(upload_to='campaign_images/', blank=True, null=True, verbose_name="Изображение")
    
    # Таргетинг
    segment = models.ForeignKey(RFSegment, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Сегмент (RFM)")
    send_to_all = models.BooleanField(default=False, verbose_name="Отправить всем оцифрованным")
    specific_clients = models.ManyToManyField(ClientBranch, blank=True, verbose_name="Точечная отправка")
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    scheduled_at = models.DateTimeField(blank=True, null=True, verbose_name="Время отправки")

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
    
    class Meta:
        verbose_name = "Рассылка"
        verbose_name_plural = "Рассылки"

class MessageLog(TimeStampedModel):
    """Лог каждого отдельного сообщения"""
    STATUS_CHOICES = [
        ('sent', 'Доставлено'),
        ('failed', 'Ошибка API'),
        ('blocked', 'Пользователь запретил сообщения'),
    ]
    
    campaign = models.ForeignKey(MailingCampaign, on_delete=models.CASCADE, null=True, blank=True, related_name='logs', verbose_name='Рассылка')
    client = models.ForeignKey(ClientBranch, on_delete=models.CASCADE, verbose_name='Гость')
    sent_at = models.DateTimeField(auto_now_add=True, verbose_name='Время отправки')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, verbose_name='Статус')
    error_message = models.TextField(blank=True, null=True, verbose_name='Сообщение об ошибке')
    
    # Поля для отслеживания прочтения (VK API)
    vk_message_id = models.BigIntegerField(blank=True, null=True, db_index=True, verbose_name="ID сообщения VK")
    is_read = models.BooleanField(default=False, verbose_name="Прочитано")
    read_at = models.DateTimeField(blank=True, null=True, verbose_name="Дата прочтения")

    class Meta:
        verbose_name = "Лог отправки"
        verbose_name_plural = "Логи отправки"
        ordering = ['-sent_at']

    def __str__(self):
        return f'{self.client} - {self.campaign}'


class MessageTemplate(TimeStampedModel):
    """
    Шаблоны автоматических рассылок.
    Позволяет настраивать тексты из админки вместо хардкода.
    """
    TEMPLATE_TYPES = [
        ('post_game', 'После игры (3 часа)'),
        ('birthday_today', 'ДР сегодня'),
        ('birthday_7days', 'ДР через 7 дней'),
        ('birthday_1day', 'ДР через 1 день'),
        ('welcome', 'Приветственное сообщение'),
        ('referral_reward', 'Награда за реферала'),
        ('prize_reminder', 'Напоминание о призах'),
    ]
    
    template_type = models.CharField(
        max_length=30,
        choices=TEMPLATE_TYPES,
        unique=True,
        verbose_name='Тип шаблона'
    )
    text = models.TextField(
        verbose_name='Текст сообщения',
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name='Активно',
        help_text='Если выключено, сообщение не будет отправлено'
    )
    
    class Meta:
        verbose_name = 'Шаблон рассылки'
        verbose_name_plural = 'Шаблоны рассылок'
    
    def __str__(self):
        return self.get_template_type_display()
    
    @classmethod
    def get_text(cls, template_type: str, default: str = '') -> str:
        """
        Получает текст шаблона по типу.
        Возвращает default если шаблон не найден или неактивен.
        """
        try:
            template = cls.objects.get(template_type=template_type, is_active=True)
            return template.text
        except cls.DoesNotExist:
            return default
    
    @classmethod
    def get_defaults(cls) -> dict:
        """Возвращает дефолтные тексты для каждого типа."""
        return {
            'post_game': 'Спасибо за игру! Ждем вас снова 🎮',
            'birthday_today': 'С Днем Рождения! 🎉 Ваш подарок уже ждет вас в ресторане!',
            'birthday_7days': 'Через неделю ваш День Рождения! 🎂 Загляните в раздел "Подарки" — там вас ждёт сюрприз.',
            'birthday_1day': 'Завтра праздник! 🎈 Столик забронирован?',
            'welcome': 'Добро пожаловать! Рады видеть вас в нашей программе лояльности.',
            'referral_reward': 'Спасибо за приглашённого друга! Ваш бонус начислен.',
            'prize_reminder': 'Не забудьте забрать свои призы! Они ждут вас.',
        }