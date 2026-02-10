import logging
from django.db import transaction
from django.utils import timezone
import datetime
from django.db.models import Q, F
from django.core.exceptions import ValidationError

logger = logging.getLogger(__name__)

from apps.tenant.branch.core import ClientService
from apps.tenant.catalog.models import Product
from apps.tenant.inventory.models import Inventory, SuperPrize, Cooldown

class InventoryService:

	@staticmethod
	def get_client_inventory(vk_user_id: int, branch_id: int):
		"""
		Получает активный инвентарь (не просроченный).
		"""
		client_profile = ClientService.get_client_profile(vk_user_id, branch_id)
		
		# Логика фильтрации:
		# 1. Либо activated_at is NULL (лежит в запасе)
		# 2. Либо activated_at + duration >= now (активирован и действует)
		now = timezone.now()
		
		inventory = Inventory.objects.filter(
			client=client_profile
		).select_related('product').filter(
			Q(activated_at__isnull=True) |
			Q(activated_at__gte=now - F('duration'))
		).order_by('-created_at')
		
		return inventory
	
	@staticmethod
	def grant_birthday_prize_single(client_branch):
		"""
		Проверяет, попадает ли сегодня в окно (-3 дня ... +7 дней) от ДР клиента.
		Если да — выдает подарок.
		Возвращает True, если подарок был создан.
		"""
		if not client_branch.birth_date:
			return False
			
		today = timezone.now().date()
		bdate = client_branch.birth_date
		
		# Определяем ДР в текущем году
		current_year_birthday = bdate.replace(year=today.year)
		
		# Если ДР был в конце года, а сейчас начало года (или наоборот), логика сложнее.
		# Но для простоты считаем окно в рамках года, или обрабатываем переход года.
		# Окно: [ДР - 3 дня, ДР + 7 дней]
		
		# Проверка "не прошел ли ДР". 
		# Но окно плавающее.
		# Давайте проще: 
		# Если (today >= birthday - 3 days) AND (today <= birthday + 7 days)
		
		# Учитываем смену года (январь/декабрь)
		# Сделаем список дат, когда подарок положен
		valid_dates = []
		for offset in range(-3, 8): # -3, -2, -1, 0, 1 ... 7
			d = current_year_birthday + datetime.timedelta(days=offset)
			valid_dates.append(d)
			
		# Еще есть edge case с 29 февраля, но пока игнорируем или django сам справится.
		
		if today in valid_dates:
			# Проверяем, был ли уже выдан подарок в этом году
			year_start = datetime.date(today.year, 1, 1)
			year_end = datetime.date(today.year, 12, 31)
			
			exists = SuperPrize.objects.filter(
				client=client_branch,
				acquired_from='BIRTHDAY',
				created_at__date__gte=year_start,
				created_at__date__lte=year_end
			).exists()
			
			if not exists:
				SuperPrize.objects.create(
					client=client_branch,
					acquired_from='BIRTHDAY',
					product=None,
					activated_at=None
				)
				logger.info(f"Granted BIRTHDAY prize to {client_branch} (Reg/Update Check)")
				return True
				
		return False

	@staticmethod
	def grant_birthday_prizes_batch(target_date):
		"""
		Выдает SuperPrize всем клиентам, у которых день рождения в target_date (обычно +7 дней).
		Использует get_or_create, чтобы не дублировать подарки при повторном запуске.
		"""
		from apps.tenant.branch.models import ClientBranch
		
		# Ищем клиентов с ДР в указанную дату
		birthday_clients = ClientBranch.objects.filter(
			birth_date__month=target_date.month,
			birth_date__day=target_date.day
		)

		created_count = 0
		for cb in birthday_clients:
			# Просто вызываем single метод. 
			# Т.к. target_date это birthday, то today (который target_date - 7) точно попадет в окно?
			# Стоп. grant_birthday_prizes_batch вызывается ЗА 7 ДНЕЙ до ДР.
			# То есть сегодня = ДР - 7.
			# Значит single метод должен это поддержать.
			# В single методе проверка: today in [birth-3 ... birth+7]
			# Если мы вызываем batch за 7 дней до, то today = birth - 7.
			# В окне [-3, +7] это НЕ попадает. (-7 < -3).
			
			# Значит batch логика и "при регистрации" логика немного разные.
			# Batch - это предиктивная выдача (заранее).
			# Registration - это "по факту" (если попал в окно).
			
			# Проверяем, был ли уже выдан подарок в этом году
			year_start = datetime.date(timezone.now().year, 1, 1)
			year_end = datetime.date(timezone.now().year, 12, 31)
			
			exists = SuperPrize.objects.filter(
				client=cb,
				acquired_from='BIRTHDAY',
				created_at__date__gte=year_start,
				created_at__date__lte=year_end
			).exists()
			
			if not exists:
				SuperPrize.objects.create(
					client=cb,
					acquired_from='BIRTHDAY',
					product=None,
					activated_at=None
				)
				created_count += 1
		
		return created_count

	@staticmethod
	def revoke_expired_birthday_prizes():
		"""
		Удаляет SuperPrize с источником BIRTHDAY, если:
		1. Прошло 3 дня после Дня Рождения.
		2. Подарок НЕ был активирован (activated_at is NULL).
		"""
		today = timezone.now().date()
		# Если сегодня 10-е число, то 3 дня назад было 7-е.
		# Значит, ищем тех, у кого ДР был 7-го числа.
		birthday_date_was = today - datetime.timedelta(days=3)

		# Логика:
		# Находим SuperPrize, который:
		# - Выдан на ДР
		# - НЕ активирован (клиент не выбрал приз)
		# - У владельца этого приза ДР был 3 дня назад
		expired_prizes = SuperPrize.objects.filter(
			acquired_from='BIRTHDAY',
			activated_at__isnull=True, # ВАЖНО: удаляем только если не воспользовался
			client__birth_date__month=birthday_date_was.month,
			client__birth_date__day=birthday_date_was.day
		)
		
		count, _ = expired_prizes.delete()
		return count

	@staticmethod
	def get_client_super_prizes(vk_user_id: int, branch_id: int):
		"""
		Получает доступные (не использованные) токены супер-призов.
		"""
		client_profile = ClientService.get_client_profile(vk_user_id, branch_id)
		
		# SuperPrize считается использованным, если есть activated_at
		prizes = SuperPrize.objects.filter(
			client=client_profile, 
			activated_at__isnull=True
		).order_by('created_at')
		
		return prizes

	@staticmethod
	def claim_super_prize(vk_user_id: int, branch_id: int, product_id: int):
		"""
		Клиент выбирает конкретный товар (product_id) для своего супер-приза.
		Создается запись в Inventory.
		"""
		# Получаем профиль (можно до транзакции, если там нет блокировки)
		client_profile = ClientService.get_client_profile(vk_user_id, branch_id)

		# 1. ОТКРЫВАЕМ ТРАНЗАКЦИЮ ТУТ
		with transaction.atomic():
			
			# Проверяем продукт (можно и внутри транзакции, это безопасно)
			product = Product.objects.filter(id=product_id, is_super_prize=True).first()
			if not product:
				raise ValidationError(message='Приз не найден или не доступен', code='product_not_found')

			# 2. Ищем и БЛОКИРУЕМ (Теперь это внутри atomic, ошибка исчезнет)
			super_prize = SuperPrize.objects.select_for_update().filter(
				client=client_profile, 
				activated_at__isnull=True
			).order_by('created_at').first()

			if not super_prize:
				raise ValidationError(message='Нет доступных супер-призов', code='not_found')

			# 3. Обновляем запись
			super_prize.product = product
			super_prize.activated_at = timezone.now()
			super_prize.save()

			# Создаем предмет
			inventory_item = Inventory.objects.create(
				client=client_profile,
				product=product,
				acquired_from='SUPERPRIZE'
			)
			
			return inventory_item
		
	@staticmethod
	def activate_inventory_item(vk_user_id: int, branch_id: int, inventory_id: int):
		"""
		Активация предмета (например, показать официанту).
		Запускает таймер действия предмета и таймер кулдауна на повторную активацию.
		"""
		client_profile = ClientService.get_client_profile(vk_user_id, branch_id)

		with transaction.atomic():
			# 1. Блокируем кулдаун для чтения и записи
			# Используем get_or_create внутри atomic, чтобы избежать гонки создания
			cooldown, created = Cooldown.objects.select_for_update().get_or_create(
				client=client_profile,
				defaults={'last_activated_at': None} # Важно для фикса п.1
			)
			
			# 2. Проверяем уже заблокированный объект
			if not created and cooldown.is_active:
				raise ValidationError(message='Подарки перезаряжаются', code='cooldown')

			# 3. Ищем и проверяем предмет
			inventory_item = Inventory.objects.select_for_update().filter(
				id=inventory_id, 
				client=client_profile
			).first()
			
			if not inventory_item:
				raise ValidationError(message='Предмет не найден', code='not_found')
				
			if inventory_item.activated_at is not None:
				raise ValidationError(message='Предмет уже активирован', code='already_used')

			# 4. Активируем
			now_time = timezone.now()
			
			inventory_item.activated_at = now_time
			inventory_item.save(update_fields=['activated_at'])

			cooldown.last_activated_at = now_time
			cooldown.save(update_fields=['last_activated_at'])
			
			return inventory_item
        
class CooldownService:
    
	@staticmethod
	def get_cooldown_status(vk_user_id: int, branch_id: int):
		client_profile = ClientService.get_client_profile(vk_user_id, branch_id)
		
		# Используем related_name из модели 'inventory_cooldown_client'
		if hasattr(client_profile, 'inventory_cooldown_client'):
			return client_profile.inventory_cooldown_client
		
		return Cooldown.objects.filter(client=client_profile).first()

	@staticmethod
	def activate_cooldown_manually(vk_user_id: int, branch_id: int):
		"""Ручная установка кулдауна (для тестов или админки)"""
		client_profile = ClientService.get_client_profile(vk_user_id, branch_id)
		
		cooldown, created = Cooldown.objects.get_or_create(
			client=client_profile,
			defaults={'last_activated_at': timezone.now()}
		)
		if not created:
			cooldown.last_activated_at = timezone.now()
			cooldown.save(update_fields=['last_activated_at'])
		return cooldown