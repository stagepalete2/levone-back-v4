from django.db import models
from django.core.exceptions import ValidationError
from django_tenants.models import TenantMixin, DomainMixin

from apps.shared.config.models import TimeStampedModel


class UsedClientId(models.Model):
	"""Хранит все когда-либо использованные client_id, чтобы нельзя было повторно назначить удалённый ID."""
	client_id = models.PositiveIntegerField(unique=True, verbose_name='Использованный ID')
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		verbose_name = 'Использованный ID клиента'
		verbose_name_plural = 'Использованные ID клиентов'

	def __str__(self):
		return str(self.client_id)


class Company(TenantMixin, TimeStampedModel):
	name = models.CharField(max_length=100, verbose_name='Название')
	description = models.TextField(verbose_name='Описание', blank=True, null=True, help_text='Для удобства')

	client_id = models.PositiveIntegerField(
		unique=True,
		verbose_name='ID клиента',
		help_text='Ручной ID клиента. После удаления этот номер нельзя будет использовать повторно.'
	)

	is_active = models.BooleanField(default=False, verbose_name='Статус', help_text='Активно/Неактивно')

	paid_until = models.DateField(verbose_name='Оплачено до', help_text='', null=True, blank=True)

	auto_create_schema = True

	auto_drop_schema = True

	def clean(self):
		super().clean()
		# Проверяем, не был ли этот client_id уже использован ранее (и удалён)
		if self.client_id is not None:
			used = UsedClientId.objects.filter(client_id=self.client_id)
			# Если это существующий объект — разрешаем свой текущий ID
			if self.pk:
				existing = Company.objects.filter(pk=self.pk).values_list('client_id', flat=True).first()
				if existing == self.client_id:
					return
			if used.exists():
				raise ValidationError({
					'client_id': f'ID {self.client_id} уже был использован ранее и заблокирован.'
				})

	def save(self, *args, **kwargs):
		super().save(*args, **kwargs)
		# Сохраняем client_id в таблицу использованных
		UsedClientId.objects.get_or_create(client_id=self.client_id)

	def __str__(self):
		return self.name

	class Meta:
		verbose_name = 'Клиент'
		verbose_name_plural = 'Клиенты'


class Domain(DomainMixin):

	class Meta:
		verbose_name = 'Домен'
		verbose_name_plural = 'Домены'


class CompanyConfig(TimeStampedModel):
	company = models.OneToOneField(
		Company, 
		on_delete=models.CASCADE,
		related_name='config',
		verbose_name='Компания'
	)

	logotype_image = models.ImageField(upload_to='logo_image/', verbose_name='Иконка логотипа', null=True, blank=True)
	coin_image = models.ImageField(upload_to='coin_image/', verbose_name='Иконка монеты', null=True, blank=True)

	vk_group_name = models.CharField(max_length=255, verbose_name='Названия группы ВК', default='Кафе LevOne')
	vk_group_id = models.CharField(max_length=255, unique=False, null=False, blank=False, default='211202938', verbose_name='ID группы ВК')

	# VK Mini-App ID — used to build deep-links into the mini-app with company/branch/table params
	vk_mini_app_id = models.CharField(
		default='53418653',
		max_length=50,
		verbose_name='ID VK Мини-Апп',
		help_text=(
			'Числовой ID мини-приложения ВКонтакте. '
			'Найти можно в разделе «Управление» → «Мини-приложения» на странице группы. '
			'Используется для генерации QR-кодов и ссылок на столики.'
		)
	)

	# IIKO API Integration
	iiko_api_url = models.URLField(
		blank=True, 
		null=True, 
		verbose_name='IIKO API URL',
		help_text='Базовый URL API, например: https://your-iiko-server.com'
	)
	iiko_api_login = models.CharField(
		max_length=255, 
		blank=True, 
		null=True, 
		verbose_name='IIKO Login'
	)
	iiko_api_password = models.CharField(
		max_length=255, 
		blank=True, 
		null=True, 
		verbose_name='IIKO Password',
		help_text='Пароль будет зашифрован SHA1 при отправке'
	)

	dooglys_api_url = models.URLField(
		blank=True, 
		null=True, 
		verbose_name='DOOGLYS API URL',
		help_text='Базовый URL API, например: https://tenant.dooglys.com'
	)

	dooglys_api_token = models.CharField(max_length=255, null=True, blank=True, verbose_name='DOOGLYS API TOKEN')

	def __str__(self):
		return f'Настройки для {self.company}'
	
	class Meta:
		verbose_name = 'Настройки компании'
		verbose_name_plural = 'Настройки компаний'


class KnowledgeBase(TimeStampedModel):
	"""
	Таблица для хранения ОДНОГО файла с базой знаний.
	"""
	company = models.OneToOneField(Company, verbose_name='База знаний', on_delete=models.PROTECT)
	
	newsletter_file = models.FileField("Файл базы знаний генерация сообщений (.docx)", upload_to='knowledge_base/newsletter', help_text='Для генерации ИИ рассылок')

	testimonial_file = models.FileField('Файл базы знании классификация отзывов (.docx)', upload_to='knowledge_base/testimonial', help_text='Для классификации отзывов')

	def save(self, *args, **kwargs):
		if not self.pk and KnowledgeBase.objects.filter(company=self.company).exists():
			KnowledgeBase.objects.filter(company=self.company).delete()
		super().save(*args, **kwargs)

	def __str__(self):
		return f"База знаний {self.company} (от {self.updated_at.strftime('%d.%m.%Y')})"

	class Meta:
		verbose_name = "База знаний (Word)"
		verbose_name_plural = "База знаний"
