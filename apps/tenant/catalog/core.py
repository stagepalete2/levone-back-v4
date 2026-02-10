from django.core.exceptions import ValidationError
from django.utils import timezone
from django.db import transaction

from apps.tenant.branch.core import ClientService
from apps.tenant.catalog.models import Product, Cooldown
from apps.tenant.branch.models import Branch, CoinTransaction
from apps.tenant.inventory.models import Inventory

class CatalogService:
    
	@staticmethod
	def get_active_products(branch_id: int):
		"""
		Получает список активных товаров для указанного ресторана.
		"""
		# 1. Проверяем существование ресторана
		# Можно использовать exists() для скорости, если объект нам не нужен целиком
		if not Branch.objects.filter(id=branch_id).exists():
			raise ValidationError(
				message='Ресторан не найден', 
				code='branch_not_found'
			)

		# 2. Получаем товары
		# Фильтруем по branch И по is_active (в старом коде было publish)
		products = Product.objects.filter(
			branch_id=branch_id,
			is_active=True
		).order_by('price') # Опционально: сортировка по цене (от дешевых к дорогим)
		
		return products

	@staticmethod
	def buy_product(vk_user_id: int, branch_id: int, product_id: int):
		"""
		Процесс покупки товара с блокировкой баланса.
		"""
		# Начинаем транзакцию ДО получения данных, чтобы залочить строку
		with transaction.atomic():
			# 1. Получаем клиента с БЛОКИРОВКОЙ (select_for_update)
			# Это предотвратит параллельные покупки
			client_branch = ClientService.get_client_profile_queryset(vk_user_id, branch_id)\
				.select_for_update()\
				.first()

			if not client_branch:
				raise ValidationError('Клиент не найден', code='not_found')

			# 2. Получаем товар
			product = Product.objects.filter(
				id=product_id, 
				branch_id=branch_id,
				is_active=True
			).first()

			if not product:
				raise ValidationError('Подарок не найден', code='product_not_found')

			# 3. Проверка кулдауна (если нужна бизнес-логика "1 покупка в день")
			cooldown, _ = Cooldown.objects.get_or_create(client=client_branch)
			if cooldown.is_active:
				raise ValidationError(
					f'Магазин перезаряжается. Ждать: {int(cooldown.time_left.total_seconds())} сек.', 
					code='cooldown_active'
				)

			# 5. Списание и Логирование
			# Вариант А: Если CoinTransaction.save() обновляет баланс сама -> ОК.
			# Вариант Б (Явный и надежный):			
			try:
				CoinTransaction.objects.create_transfer(
					client_branch=client_branch,
					amount=product.price,
					transaction_type=CoinTransaction.Type.EXPENSE,
					source=CoinTransaction.Source.SHOP,
					description=f'Покупка: {product.name}'
				)
			except ValidationError:
				raise ValidationError('Недостаточно монет', code='not_enough_coins')

			# 6. Выдача предмета
			inventory_item = Inventory.objects.create(
				client=client_branch,
				product=product,
				acquired_from='BUY'
			)

			# 7. Активация кулдауна
			cooldown.last_activated_at = timezone.now()
			cooldown.save(update_fields=['last_activated_at'])
			
			return inventory_item

class CooldownService:
    
    @staticmethod
    def get_cooldown_status(vk_user_id: int, branch_id: int):
        """
        Получает статус перезарядки.
        Возвращает None, если записи нет.
        """
        # 1. Находим профиль клиента через существующий сервис
        # Он сам проверит existence клиента и ресторана и выкинет ошибку если что не так
        client_branch = ClientService.get_client_profile(vk_user_id, branch_id)

        # 2. Ищем запись кулдауна
        cooldown = Cooldown.objects.filter(client=client_branch).first()
        return cooldown

    @staticmethod
    def activate_cooldown(vk_user_id: int, branch_id: int):
        """
        Активирует перезарядку (обновляет время).
        """
        # 1. Находим профиль
        client_branch = ClientService.get_client_profile(vk_user_id, branch_id)

        # 2. Создаем или обновляем запись (get_or_create)
        # Обрати внимание: defaults не нужен, так как last_activated_at мы все равно перезапишем
        cooldown, created = Cooldown.objects.get_or_create(
            client=client_branch,
            defaults={'last_activated_at': timezone.now()}
        )

        # 3. Обновляем время на "сейчас"
        if not created:
            cooldown.last_activated_at = timezone.now()
            cooldown.save(update_fields=['last_activated_at'])
            
        return cooldown