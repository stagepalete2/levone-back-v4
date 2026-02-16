import uuid
from django.db import models, transaction
from django.db.models import Sum
from django.core.exceptions import ValidationError

from apps.shared.config.models import TimeStampedModel

class Branch(TimeStampedModel):
    name = models.CharField(max_length=255, verbose_name='Название')
    description = models.TextField(null=True, blank=True, verbose_name='Описание', help_text='Для внутреннего пользования')
    
    company = models.ForeignKey(
        'clients.Company', 
        on_delete=models.CASCADE, 
        related_name='branches', 
        verbose_name='Клиент'
    )
    
    # IIKO Integration: Department name from IIKO OLAP reports
    iiko_organization_id = models.CharField(
        max_length=255, 
        blank=True, 
        null=True, 
        verbose_name='IIKO Organization ID (Department)',
        help_text='ID ресторана из IIKO (Если у вас IIKO, оставьте пустым Dooglys)'
    )
    
    dooglys_branch_id = models.PositiveIntegerField(
        blank=True,
        null=True,
        verbose_name='Dooglys branch ID',
        help_text='ID ресторана из Dooglys (Если у вас Dooglys, оставьте пустым IIKO)',
        unique=True
    )

    dooglas_sale_point_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name='Sale Point ID ресторана из Dooglys',
        unique=True
    )
    
    def clean(self):
        '''Валидация: можно заполнить только одно из полей - iiko_organization_id или dooglys_branch_id'''
        super().clean()
        
        # Проверяем, что заполнено не более одного поля
        has_iiko = bool(self.iiko_organization_id and self.iiko_organization_id.strip())
        has_dooglys = self.dooglys_branch_id is not None
        
        if has_iiko and has_dooglys:
            raise ValidationError({
                'iiko_organization_id': 'Нельзя одновременно указать IIKO Organization ID и Dooglys Branch ID. Выберите один источник.',
                'dooglys_branch_id': 'Нельзя одновременно указать IIKO Organization ID и Dooglys Branch ID. Выберите один источник.'
            })
        
        # Проверяем, что хотя бы одно поле заполнено (опционально - закомментируйте если не нужно)
        if not has_iiko and not has_dooglys:
            raise ValidationError(
                'Необходимо указать хотя бы один идентификатор: IIKO Organization ID или Dooglys Branch ID'
            )
    
    def save(self, *args, **kwargs):
        '''Переопределяем save для вызова clean() при сохранении'''
        self.clean()
        super().save(*args, **kwargs)
    
    def __str__(self):
        return self.name
    
    class Meta:
        verbose_name = 'Торговая точка'
        verbose_name_plural = 'Торговые точки'

class BranchConfig(TimeStampedModel):
    branch = models.OneToOneField(
        Branch, 
        on_delete=models.CASCADE,
        related_name='config',
        verbose_name='Ресторан'
    )

    yandex_map = models.URLField(verbose_name='Yandex Карты Ссылка', blank=True, null=True)
    gis_map = models.URLField(verbose_name='2GIS Карты Ссылка', blank=True, null=True)

    def __str__(self):
        # ИСПРАВЛЕНО: self.name -> self.branch.name
        return f"Настройки: {self.branch.name}"
    
    class Meta:
        verbose_name = 'Настройки Ресторана'
        verbose_name_plural = 'Настройки Ресторанов'

class TelegramBot(TimeStampedModel):
    name = models.CharField(max_length=100, verbose_name='Название (для админки)')

    bot_username = models.CharField(max_length=100, verbose_name='Username бота (без @)', help_text='Пример: MyRestaurantBot')
    api = models.CharField(max_length=255, verbose_name='Телеграм бот API Token')

    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, verbose_name='Ресторан')

    def __str__(self):
        return f"@{self.bot_username} ({self.name})"
    
    class Meta:
        verbose_name = 'Телеграм бот'
        verbose_name_plural = 'Телеграм боты'

class BotAdmin(TimeStampedModel):
    bot = models.ForeignKey(TelegramBot, on_delete=models.CASCADE, verbose_name='Бот')

    chat_id = models.CharField(max_length=255, verbose_name='ID Чат', null=True, blank=True)
    name = models.CharField(max_length=155, verbose_name='Имя сотрудника')
    verification_token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    is_active = models.BooleanField(default=True, verbose_name='Активно',  help_text='Доступ к админке бота')

    def get_connect_link(self):
        return f"https://t.me/{self.bot.bot_username}?start={self.verification_token}"

    def __str__(self):
        return f"{self.name} ({self.bot.name})"
    
    class Meta:
        verbose_name = 'Администратор'
        verbose_name_plural = 'Администраторы ботов'


class ClientBranch(TimeStampedModel):
    client = models.ForeignKey(
        'guest.Client', 
        on_delete=models.CASCADE, 
        verbose_name='Гость',
        related_name='branch_profiles'
    )
    branch = models.ForeignKey(
        'branch.Branch',
        on_delete=models.CASCADE, 
        verbose_name='Ресторан',
        related_name='clients'
    )

    birth_date = models.DateField(blank=True, null=True, verbose_name='Дата рождения')

    is_story_uploaded = models.BooleanField(default=False, verbose_name='Сторис опубликован')
    is_joined_community = models.BooleanField(default=False, verbose_name='Вступил в сообщество')
    is_allowed_message = models.BooleanField(default=False, verbose_name='Разрешил отправку сообщений')
    is_super_prize_won = models.BooleanField(default=False, verbose_name='Выиграл суперприз')

    invited_by = models.ForeignKey(
        'guest.Client', 
        on_delete=models.SET_NULL,
        verbose_name='Пригласил', 
        blank=True, 
        null=True, 
        related_name='invited_clients'
    )

    is_employee = models.BooleanField(default=False, verbose_name='Сотрудник')

    @property
    def coins_balance(self):
        """Calculate balance dynamically as sum of all transactions."""
        income = self.transactions.filter(type=CoinTransaction.Type.INCOME).aggregate(total=Sum('amount'))['total'] or 0
        expense = self.transactions.filter(type=CoinTransaction.Type.EXPENSE).aggregate(total=Sum('amount'))['total'] or 0
        return income - expense
    
    coins_balance.fget.short_description = 'Баланс монет'

    def can_spend(self, amount):
        """Check if the client has enough coins to spend."""
        return self.coins_balance >= amount

    def __str__(self):
        return f'{self.client} @ {self.branch}'

    class Meta:
        verbose_name = 'Профиль гостя в ресторане'
        verbose_name_plural = 'Профили гостей'
        unique_together = ('client', 'branch')

# class CoinTransactionQuerySet(models.QuerySet):
#     def delete(self):
#         # raise NotImplementedError("Удаление транзакций запрещено! Это история.")
#         self.delete()

class CoinTransactionManager(models.Manager):
    # def get_queryset(self):
    #     return CoinTransactionQuerySet(self.model, using=self._db)

    @transaction.atomic
    def create_transfer(self, client_branch, amount, transaction_type, source, description=''):
        # 1. Блокируем клиента. 
        # Это нужно, чтобы пока мы считаем баланс и пишем транзакцию,
        # никто другой не мог создать новую транзакцию для этого клиента.
        # (Хотя технически insert не блокируется row-lock-ом клиента, это служит "мьютексом")
        _ = type(client_branch).objects.select_for_update().get(pk=client_branch.pk)

        # 2. Проверяем средства (ТОЛЬКО для списания)
        # Здесь Django сделает SQL-запрос SUM() по всей таблице транзакций
        if transaction_type == CoinTransaction.Type.EXPENSE:
            if client_branch.coins_balance < amount:
                 raise ValidationError("Недостаточно средств")

        # 3. Просто создаем запись. Баланс изменится сам "виртуально" при следующем подсчете.
        transaction_record = self.create(
            client=client_branch,
            type=transaction_type,
            source=source,
            amount=amount,
            description=description
        )
        
        return transaction_record

class CoinTransaction(models.Model):
    class Type(models.TextChoices):
        INCOME = 'INCOME', 'Доход'
        EXPENSE = 'EXPENSE', 'Трата'

    class Source(models.TextChoices):
        GAME = 'GAME', 'Игра'
        QUEST = 'QUEST', 'Задание'
        MANUAL = 'MANUAL', 'Вручную (Админ)'
        SHOP = 'SHOP', 'Магазин'

    client = models.ForeignKey(
        'ClientBranch',
        on_delete=models.PROTECT,
        related_name='transactions',
        verbose_name='Клиент'
    )

    type = models.CharField(max_length=10, choices=Type.choices, verbose_name='Тип')
    source = models.CharField(max_length=20, choices=Source.choices, verbose_name='Источник')
    amount = models.PositiveIntegerField(verbose_name='Сумма')
    description = models.CharField(max_length=255, blank=True, null=True, verbose_name='Описание')

    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name='Создан')

    objects = CoinTransactionManager()

    # def delete(self, *args, **kwargs):
    #     raise NotImplementedError("Нельзя удалять транзакции")

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Транзакция монет'
        verbose_name_plural = 'Транзакции монет'
        indexes = [
            models.Index(fields=['client', 'type']), 
        ]


class StoryImage(TimeStampedModel):
    image = models.ImageField(upload_to='story_image/', verbose_name='Фото')

    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        verbose_name='Ресторан'
    )

    def __str__(self):
        return self.image.name

    class Meta:
        verbose_name = 'Фото для истории'
        verbose_name_plural = 'Фото для истории'


class BranchTestimonials(TimeStampedModel):
    class Source(models.TextChoices):
        APP = 'APP', 'Приложение'
        VK_MESSAGE = 'VK_MESSAGE', 'Сообщение ВК'

    class Sentiment(models.TextChoices):
        POSITIVE = 'POSITIVE', 'Позитивный'
        NEGATIVE = 'NEGATIVE', 'Негативный'
        NEUTRAL = 'NEUTRAL', 'Нейтральный'
        SPAM = 'SPAM', 'Спам/Не по теме'
        WAITING = 'WAITING', 'Ожидает анализа'

    client = models.ForeignKey(
        'branch.ClientBranch', 
        on_delete=models.SET_NULL, 
        verbose_name='Гость', 
        null=True, 
        blank=True
    )
    vk_sender_id = models.CharField("VK ID отправителя", max_length=50, blank=True, null=True)
    vk_message_id = models.CharField("VK ID сообщения", max_length=50, blank=True, null=True, unique=True)
    
    rating = models.PositiveIntegerField(default=5, verbose_name='Оценка (из приложения)')
    phone = models.CharField(max_length=20, null=True, blank=True, verbose_name='Номер Телефона')
    table = models.PositiveIntegerField(verbose_name='Столик', null=True, blank=True)
    
    review = models.TextField(verbose_name='Текст отзыва')
    
    # Новые поля
    source = models.CharField("Источник", max_length=20, choices=Source.choices, default=Source.APP)
    
    sentiment = models.CharField(
        "Анализ ИИ", 
        max_length=20, 
        choices=Sentiment.choices, 
        default=Sentiment.WAITING
    )
    ai_comment = models.TextField("Комментарий ИИ", blank=True, null=True, help_text="Почему ИИ принял такое решение")
    
    is_replied = models.BooleanField(default=False, verbose_name="Ответ отправлен")

    def __str__(self):
        return f'{self.source}: {self.review[:30]}...'
    
    class Meta:
        verbose_name = 'Отзыв / Обращение'
        verbose_name_plural = 'Отзывы и Обращения'


class ClientBranchVisit(TimeStampedModel):
    """
    Запись визита гостя при сканировании QR кода.
    Используется для подсчёта индекса сканирования.
    6-часовой cooldown предотвращает фантомные визиты.
    """
    COOLDOWN_HOURS = 6
    
    client = models.ForeignKey(
        ClientBranch,
        on_delete=models.CASCADE,
        related_name='visits',
        verbose_name='Гость'
    )
    visited_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Время визита'
    )
    
    class Meta:
        verbose_name = 'Визит гостя (QR скан)'
        verbose_name_plural = 'Визиты гостей (QR сканы)'
        indexes = [
            models.Index(fields=['client', '-visited_at']),
            models.Index(fields=['visited_at']),
        ]
        ordering = ['-visited_at']
    
    def __str__(self):
        return f'{self.client} @ {self.visited_at.strftime("%d.%m.%Y %H:%M")}'
    
    @classmethod
    def can_record_visit(cls, client_branch) -> bool:
        """
        Проверяет, можно ли записать визит (прошло ли 6 часов с последнего).
        """
        from django.utils import timezone
        from datetime import timedelta
        
        cooldown_threshold = timezone.now() - timedelta(hours=cls.COOLDOWN_HOURS)
        
        return not cls.objects.filter(
            client=client_branch,
            visited_at__gte=cooldown_threshold
        ).exists()
    
    @classmethod
    def record_visit(cls, client_branch) -> 'ClientBranchVisit | None':
        """
        Записывает визит если прошёл cooldown, иначе возвращает None.
        """
        if cls.can_record_visit(client_branch):
            return cls.objects.create(client=client_branch)
        return None


class Promotions(TimeStampedModel):
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, verbose_name='Ресторан')

    title = models.CharField(max_length=100, verbose_name='Название')
    discount = models.PositiveIntegerField(verbose_name='Скидка (%)')
    dates = models.CharField(max_length=255, verbose_name='Даты')
    images = models.ImageField(upload_to='promotions', verbose_name='Фото')

    def __str__(self):
        return self.title
    
    class Meta:
        verbose_name = 'Скидка'
        verbose_name_plural = 'Скидки и промоакции'
