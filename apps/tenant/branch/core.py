from django.shortcuts import get_object_or_404
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.db import connection # Added
import vk_api
import requests

from apps.tenant.branch.models import Branch, ClientBranch, BranchTestimonials, TelegramBot, BotAdmin, CoinTransaction, Promotions
from apps.shared.guest.models import Client as BaseClient
from apps.tenant.senler.models import VKConnection

class BranchService:
	@staticmethod
	def get_branch_full_info(branch_id: int) -> Branch:
		"""
		Получает ресторан со всеми связанными настройками.
		Использует select_related для оптимизации (join config).
		"""
		# Проверяем, существует ли branch
		# select_related('config') делает JOIN таблицы конфига сразу, 
		# чтобы в сериализаторе не было лишних запросов
		branch = Branch.objects.select_related('config').filter(id=branch_id).first()
		
		if not branch:
			raise ValidationError(
				message='Ресторан не найден', 
				code='not_found'
			)
			
		return branch
	
	@staticmethod
	def get_promotions(branch: int):
		branch = get_object_or_404(Branch, id=branch)
		promotions = Promotions.objects.filter(branch=branch)
		return promotions


class ClientService:
	@staticmethod
	def get_client_profile(vk_user_id: int, branch_id: int) -> ClientBranch:
		"""Получает профиль клиента в конкретном ресторане"""
		try:
			profile = ClientBranch.objects.select_related('client', 'branch').get(
				client__vk_user_id=vk_user_id,
				branch_id=branch_id
			)
			return profile
		except ClientBranch.DoesNotExist:
			raise ValidationError(
				message='Клиент в данном ресторане не найден', 
				code='not_found'
			)
	
	@staticmethod
	def get_client_profile_queryset(vk_user_id, branch_id):
		return ClientBranch.objects.filter(
			client__vk_user_id=vk_user_id, 
			branch_id=branch_id
		)

	@staticmethod
	@transaction.atomic
	def register_or_update_client(vk_user_id: int, branch_id: int, data: dict) -> ClientBranch:
		branch = Branch.objects.filter(id=branch_id).first()
		if not branch:
				raise ValidationError('Ресторан не найден', code='branch_not_found')

		base_client, created = BaseClient.objects.get_or_create(
			vk_user_id=vk_user_id,
			defaults={
				'name': data.get('name', ''),
				'lastname': data.get('lastname', ''),
				'sex': data.get('sex', 0)
			}
		)

		if not created:
			need_save = False
			if data.get('name') and base_client.name != data['name']:
				base_client.name = data['name']
				need_save = True
			if data.get('lastname') and base_client.lastname != data['lastname']:
				base_client.lastname = data['lastname']
				need_save = True
			if data.get('sex') is not None and base_client.sex != data['sex']:
				base_client.sex = data['sex']
				need_save = True
			
			if need_save:
				base_client.save()

		# Связь с тенантом
		client_branch, cb_created = ClientBranch.objects.get_or_create(
			client=base_client,
			branch=branch
		)
		
		# При ПЕРВОМ создании профиля — проверяем VK API:
		# был ли пользователь УЖЕ подписан на группу и рассылку ДО нашего приложения.
		# Если да — ставим is_joined_community/is_allowed_message = True сразу,
		# чтобы при PATCH'е мы знали, что это НЕ новая подписка через приложение.
		if cb_created:
			try:
				from apps.tenant.senler.services import VKService
				vk_service = VKService()
				if vk_service.is_configured:
					was_member = vk_service.check_is_group_member(vk_user_id)
					was_allowed = vk_service.check_is_messages_allowed(vk_user_id)
					
					if was_member:
						client_branch.is_joined_community = True
					if was_allowed:
						client_branch.is_allowed_message = True
					
					if was_member or was_allowed:
						client_branch.save(update_fields=['is_joined_community', 'is_allowed_message'])
			except Exception as e:
				import logging
				logging.getLogger(__name__).warning(f"VK check at registration failed for {vk_user_id}: {e}")
		
		# Если передали ДР, сохраняем
		if data.get('birth_date'):
			client_branch.birth_date = data['birth_date']
			client_branch.save(update_fields=['birth_date'])
		
		# Отправляем приветственное сообщение при ПЕРВОМ создании профиля
		if cb_created:
			try:
				from apps.tenant.senler.tasks import send_single_message
				send_single_message.delay(
					client_branch_id=client_branch.id,
					text=None,
					schema_name=connection.schema_name,
					template_type='welcome'
				)
			except Exception as e:
				import logging
				logging.getLogger(__name__).warning(f"Welcome message scheduling failed for {vk_user_id}: {e}")
		
		return client_branch

	@staticmethod
	def update_profile_details(vk_user_id: int, branch_id: int, validated_data: dict) -> ClientBranch:
		"""
		Логика PATCH запроса.
		Отслеживает переход is_joined_community и is_allowed_message
		из False → True как реальную подписку через приложение.
		"""
		# Получаем объект (метод переиспользуем)
		client_branch = ClientService.get_client_profile(vk_user_id, branch_id)

		# Сохраняем старые значения ДО обновления
		old_joined = client_branch.is_joined_community
		old_allowed = client_branch.is_allowed_message
		old_story = client_branch.is_story_uploaded
		old_invited_by = client_branch.invited_by_id

		# Обновляем поля ClientBranch
		for attr, value in validated_data.items():
			# Пропускаем служебные поля, если они вдруг попали (хотя сериализатор их отсек)
			if attr in ['vk_user_id', 'branch_id']:
				continue
			setattr(client_branch, attr, value)
		
		# ── Синхронизация связанных флагов ──
		# Когда is_joined_community переходит False → True (подписался через приложение):
		# автоматически ставим все связанные флаги, чтобы метрики считались правильно.
		new_joined = client_branch.is_joined_community
		new_allowed = client_branch.is_allowed_message
		new_story = client_branch.is_story_uploaded

		if not old_joined and new_joined:
			client_branch.joined_community_via_app = True
			# Если вступил в сообщество — значит и рассылку разрешил
			client_branch.is_allowed_message = True
			client_branch.allowed_message_via_app = True
		
		if not old_allowed and new_allowed:
			client_branch.allowed_message_via_app = True

		# Когда is_story_uploaded переходит False → True — фиксируем время
		if not old_story and new_story:
			client_branch.story_uploaded_at = timezone.now()

		client_branch.save()

		# Отправляем награду за реферала пригласившему, если invited_by установлен впервые
		new_invited_by = client_branch.invited_by_id
		if not old_invited_by and new_invited_by:
			try:
				inviter_branch = ClientBranch.objects.filter(
					client_id=new_invited_by,
					branch_id=branch_id
				).first()
				if inviter_branch:
					from apps.tenant.senler.tasks import send_single_message
					send_single_message.delay(
						client_branch_id=inviter_branch.id,
						text=None,
						schema_name=connection.schema_name,
						template_type='referral_reward'
					)
			except Exception as e:
				import logging
				logging.getLogger(__name__).warning(f"Referral reward message failed: {e}")
		
		return client_branch

	@staticmethod
	def get_client_transactions(vk_user_id: int, branch_id: int):
		"""
		Возвращает QuerySet транзакций конкретного гостя в конкретном ресторане.
		"""
		# 1. Сначала находим профиль (с проверкой, что он существует)
		# Этот метод мы написали в прошлом шаге, он уже проверяет branch_id!
		client_profile = ClientService.get_client_profile(vk_user_id, branch_id)

		# 2. Получаем транзакции через reverse relation
		# order_by('-created_at') гарантирует, что новые будут сверху
		transactions = CoinTransaction.objects.filter(
			client=client_profile
		).order_by('-created_at')

		return transactions
	
	@staticmethod
	def get_employees(branch: int):
		branch = get_object_or_404(Branch, id=branch)
		employees = ClientBranch.objects.filter(branch=branch, is_employee=True)
		return employees

class VKFeedbackService:
    @staticmethod
    def fetch_unread_messages(branch):
        """Получает непрочитанные сообщения из ЛС сообщества"""
        config = VKConnection.objects.first() # Предполагаем связь с branch
        if not config or not config.access_token:
            return

        vk_session = vk_api.VkApi(token=config.raw_token, api_version='5.131')
        vk = vk_session.get_api()

        try:
            # Получаем непрочитанные диалоги
            conversations = vk.messages.getConversations(filter='unread', count=20)
            
            for item in conversations['items']:
                last_msg = item['last_message']
                sender_id = last_msg['from_id']
                text = last_msg['text']
                message_id = str(last_msg['id'])
                
                # Игнорируем пустые сообщения или от ботов
                if sender_id < 0 or not text:
                    continue

                # 1. Проверяем, не обрабатывали ли мы уже это сообщение
                if BranchTestimonials.objects.filter(vk_message_id=message_id).exists():
                    continue

                # Пробуем найти клиента в базе по VK ID
                client_branch = ClientBranch.objects.filter(
                    client__vk_user_id=sender_id, 
                    branch=branch
                ).first()

                # Сохраняем как отзыв
                ReviewService.create_review_from_vk(
                    branch=branch,
                    text=text,
                    vk_user_id=sender_id,
                    client_branch=client_branch,
                    vk_message_id=message_id
                )
                
                # Помечаем как прочитанное (опционально, чтобы не скачивать вечно)
                # vk.messages.markAsRead(peer_id=sender_id)

        except Exception as e:
            print(f"VK Fetch Error: {e}")

class ReviewService:
	@staticmethod
	def create_review(data: dict):
		# ... (код создания testimonial остается) ...
		vk_user_id = data['vk_user_id']
		branch_id = data['branch_id']
		client_branch = ClientService.get_client_profile(vk_user_id, branch_id)

		testimonial = BranchTestimonials.objects.create(
			client=client_branch,
			rating=data['rating'],
			phone=data['phone'],
			table=data['table'],
			review=data['review']
		)

		from apps.tenant.branch.tasks import process_ai_review
		# Passing schema_name explicitly
		process_ai_review.delay(testimonial.id, connection.schema_name)

		ReviewService._send_telegram_notification(testimonial, client_branch.branch)
		return testimonial
	
	@staticmethod
	def create_review_from_vk(branch, text, vk_user_id, client_branch=None, vk_message_id=None):
		# ... (код создания testimonial остается) ...
		testimonial = BranchTestimonials.objects.create(
			client=client_branch,
			vk_sender_id=str(vk_user_id),
			vk_message_id=vk_message_id,
			review=text,
			rating=0,
			source=BranchTestimonials.Source.VK_MESSAGE,
			table=0
		)
		
		from apps.tenant.branch.tasks import process_ai_review
		# Passing schema_name explicitly
		process_ai_review.delay(testimonial.id, connection.schema_name)
		
		return testimonial

	@staticmethod
	def _send_telegram_notification(testimonial: BranchTestimonials, branch):
		"""
		Внутренняя логика отправки сообщения в Telegram.
		Не должна прерывать основной поток, если телеграм недоступен.
		"""
		bot = TelegramBot.objects.filter(branch=branch).first()
		if not bot:
			return

		admins = BotAdmin.objects.filter(bot=bot, is_active=True).exclude(chat_id__isnull=True)
		if not admins.exists():
			return

		timestamp = timezone.localtime(timezone.now()).strftime('%d.%m.%Y %H:%M')
		
		# Handle potential checking if client is None
		if testimonial.client and testimonial.client.client:
			full_name = f"{testimonial.client.client.name} {testimonial.client.client.lastname}"
		else:
			full_name = f"VK ID: {testimonial.vk_sender_id}" # Fallback
		
		if testimonial.rating < 5:
			message = (
				f'❗️❗️❗️ ВНИМАНИЕ ❗️❗️❗️ Отзыв с оценкой {testimonial.rating}/5 {"⭐️" * testimonial.rating} !!!\n\n'
				f'👤 Имя: {full_name}\n'
				f'📱 Телефон: {testimonial.phone}\n'
				f'🏠 Кафе: {branch.name}\n'
				f'🪑 Стол: {testimonial.table}\n'
				f'🕒 Время: {timestamp}\n\n'
				f'📝 Отзыв:\n{testimonial.review}\n\n'
				f'⚠️ Требуется обратная связь с клиентом!'
			)
		else:
			message = (
				f'📢 Новый отзыв! {"⭐️" * testimonial.rating}\n\n'
				f'👤 Имя: {full_name}\n'
				f'📱 Телефон: {testimonial.phone}\n'
				f'🏠 Кафе: {branch.name}\n'
				f'🪑 Стол: {testimonial.table}\n'
				f'🕒 Время: {timestamp}\n\n'
				f'📝 Отзыв:\n{testimonial.review}'
			)

		url = f'https://api.telegram.org/bot{bot.api}/sendMessage'
		
		for admin in admins:
			try:
				requests.post(url, json={"chat_id": admin.chat_id, "text": message}, timeout=5)
			except Exception as e:
				print(f"Error sending telegram to {admin.chat_id}: {e}")
