from django.shortcuts import get_object_or_404
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.db import connection # Added
import vk_api
import requests

from apps.tenant.branch.models import Branch, ClientBranch, BranchTestimonials, TestimonialReply, TelegramBot, BotAdmin, CoinTransaction, Promotions
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
		
		# Проверяем VK API: был ли пользователь УЖЕ подписан на группу и рассылку
		# ДО нашего приложения. Выполняем проверку:
		# - При ПЕРВОМ создании профиля (cb_created=True)
		# - ИЛИ если предыдущая проверка не удалась (vk_status_checked=False)
		#
		# ВАЖНО: это ЕДИНСТВЕННЫЙ момент, когда мы можем отличить
		# "был подписан заранее" от "подпишется через приложение".
		# К моменту PATCH пользователь уже подписан — различить невозможно.
		#
		# check_is_group_member / check_is_messages_allowed возвращают:
		#   True  = подписан
		#   False = НЕ подписан  
		#   None  = ошибка VK API (таймаут, невалидный токен, etc.)
		# vk_status_checked=True ставим ТОЛЬКО при True/False, не при None.
		if not client_branch.vk_status_checked:
			import time
			import logging
			_logger = logging.getLogger(__name__)
			
			try:
				from apps.tenant.senler.services import VKService
				vk_service = VKService()
				
				was_member = None
				was_allowed = None

				# 3 попытки с паузой 0.5с.
				# check_is_group_member возвращает None при ошибке —
				# ретраим только те проверки, которые вернули None.
				for attempt in range(3):
					if was_member is None:
						was_member = vk_service.check_is_group_member(vk_user_id)
					if was_allowed is None:
						was_allowed = vk_service.check_is_messages_allowed(vk_user_id)
					
					# Обе проверки дали чёткий результат (True или False, не None)
					if was_member is not None and was_allowed is not None:
						break
					
					if attempt < 2:
						time.sleep(0.5)
				
				_logger.info(
					f"VK check for {vk_user_id}: member={was_member}, allowed={was_allowed} "
					f"(after {attempt + 1} attempt(s))"
				)
				
				# Ставим vk_status_checked=True ТОЛЬКО если обе проверки
				# вернули чёткий результат (True или False).
				# Если хоть одна вернула None — не ставим, попробуем при следующем входе.
				if was_member is not None and was_allowed is not None:
					update_fields = ['vk_status_checked']
					client_branch.vk_status_checked = True
					
					if was_member and not client_branch.is_joined_community:
						client_branch.is_joined_community = True
						update_fields.append('is_joined_community')
					if was_allowed and not client_branch.is_allowed_message:
						client_branch.is_allowed_message = True
						update_fields.append('is_allowed_message')
					
					client_branch.save(update_fields=update_fields)
				else:
					_logger.warning(
						f"VK check INCOMPLETE for {vk_user_id}: member={was_member}, allowed={was_allowed}. "
						f"vk_status_checked remains False — will retry on next visit."
					)
			except Exception as e:
				import logging
				logging.getLogger(__name__).warning(
					f"VK check failed for {vk_user_id}: {e}. "
					f"vk_status_checked remains False."
				)
		
		# Если передали ДР, сохраняем
		if data.get('birth_date'):
			client_branch.birth_date = data['birth_date']
			client_branch.save(update_fields=['birth_date'])
		
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
		#
		# Защита от ложных срабатываний — в register_or_update_client:
		# при каждом входе (пока vk_status_checked=False) проверяем VK API с ретраями.
		# Если пользователь УЖЕ был подписан — is_joined_community будет True ДО PATCH,
		# и перехода False→True не произойдёт.
		new_joined = client_branch.is_joined_community
		new_allowed = client_branch.is_allowed_message
		new_story = client_branch.is_story_uploaded

		if not old_joined and new_joined:
			client_branch.joined_community_via_app = True
			# Если вступил в сообщество — значит и рассылку разрешил
			client_branch.is_allowed_message = True
			client_branch.allowed_message_via_app = True
			if not client_branch.vk_status_checked:
				import logging
				logging.getLogger(__name__).warning(
					f"PATCH: via_app=True для {vk_user_id}, но vk_status_checked=False. "
					f"Возможно ложное срабатывание — VK проверка не прошла при регистрации."
				)
		
		if not old_allowed and new_allowed:
			client_branch.allowed_message_via_app = True
			if not client_branch.vk_status_checked:
				import logging
				logging.getLogger(__name__).warning(
					f"PATCH: allowed_message_via_app=True для {vk_user_id}, "
					f"но vk_status_checked=False. Возможно ложное срабатывание."
				)

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
        config = VKConnection.objects.first()
        if not config or not config.access_token:
            print(f"[VK Fetch] No VKConnection or no access_token for branch {branch}")
            return

        vk_session = vk_api.VkApi(token=config.raw_token, api_version='5.131')
        vk = vk_session.get_api()

        try:
            conversations = vk.messages.getConversations(filter='unread', count=20)
        except Exception as e:
            print(f"[VK Fetch] Error getConversations: {e}")
            return

        items = conversations.get('items', [])
        print(f"[VK Fetch] Got {len(items)} unread conversations")

        for item in items:
            try:
                last_msg = item['last_message']
                sender_id = last_msg['from_id']
                text = last_msg['text']
                message_id = str(last_msg['id'])

                # Игнорируем пустые сообщения или от ботов
                if sender_id < 0 or not text:
                    continue

                # 1. Проверяем, не обрабатывали ли мы уже это сообщение
                if BranchTestimonials.objects.filter(vk_message_id=message_id).exists():
                    # Помечаем как прочитанное чтобы не получать повторно
                    try:
                        vk.messages.markAsRead(peer_id=sender_id)
                    except Exception:
                        pass
                    continue
                if TestimonialReply.objects.filter(vk_message_id=message_id).exists():
                    try:
                        vk.messages.markAsRead(peer_id=sender_id)
                    except Exception:
                        pass
                    continue

                # Пробуем найти клиента в базе по VK ID
                client_branch = ClientBranch.objects.filter(
                    client__vk_user_id=sender_id,
                    branch=branch
                ).first()

                # Проверяем, есть ли уже диалог с этим пользователем
                existing = BranchTestimonials.objects.filter(
                    vk_sender_id=str(sender_id)
                ).first()

                if existing:
                    # Добавляем как входящее сообщение в существующий диалог
                    TestimonialReply.objects.create(
                        testimonial=existing,
                        text=text,
                        direction=TestimonialReply.Direction.INCOMING,
                        message_type=TestimonialReply.MessageType.VK_MESSAGE,
                        vk_message_id=message_id,
                    )
                    existing.has_unread = True
                    existing.save(update_fields=['has_unread'])
                    print(f"[VK Fetch] Added reply to existing dialog #{existing.id} from VK user {sender_id}")
                else:
                    # Создаём новый диалог
                    ReviewService.create_review_from_vk(
                        branch=branch,
                        text=text,
                        vk_user_id=sender_id,
                        client_branch=client_branch,
                        vk_message_id=message_id
                    )
                    print(f"[VK Fetch] Created new dialog for VK user {sender_id}")

                # Помечаем как прочитанное после успешной обработки
                try:
                    vk.messages.markAsRead(peer_id=sender_id)
                except Exception:
                    pass

            except Exception as e:
                print(f"VK Fetch Error (message {item}): {e}")

class ReviewService:
	@staticmethod
	def create_review(data: dict):
		vk_user_id = data['vk_user_id']
		branch_id = data['branch_id']
		client_branch = ClientService.get_client_profile(vk_user_id, branch_id)

		# Проверяем, есть ли уже диалог с этим клиентом
		existing = BranchTestimonials.objects.filter(client=client_branch).first()

		if existing:
			# Добавляем как входящее сообщение в существующий диалог
			TestimonialReply.objects.create(
				testimonial=existing,
				text=data['review'],
				direction=TestimonialReply.Direction.INCOMING,
				message_type=TestimonialReply.MessageType.APP_REVIEW,
			)
			existing.has_unread = True
			existing.save(update_fields=['has_unread'])
			from apps.tenant.branch.tasks import process_ai_review
			process_ai_review.delay(existing.id, connection.schema_name)
			ReviewService._send_telegram_notification(existing, client_branch.branch)
			return existing

		testimonial = BranchTestimonials.objects.create(
			client=client_branch,
			rating=data['rating'],
			phone=data['phone'],
			table=data['table'],
			review=data['review']
		)

		from apps.tenant.branch.tasks import process_ai_review
		process_ai_review.delay(testimonial.id, connection.schema_name)

		ReviewService._send_telegram_notification(testimonial, client_branch.branch)
		return testimonial
	
	@staticmethod
	def create_review_from_vk(branch, text, vk_user_id, client_branch=None, vk_message_id=None):
		"""Создание отзыва/обращения из ЛС ВК группы. Оценка (rating) не ставится — она только из приложения."""
		testimonial = BranchTestimonials.objects.create(
			client=client_branch,
			vk_sender_id=str(vk_user_id),
			vk_message_id=vk_message_id,
			review=text,
			rating=None,
			source=BranchTestimonials.Source.VK_MESSAGE,
			table=None
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
		
		# Формируем сообщение с учётом источника
		is_vk = testimonial.source == BranchTestimonials.Source.VK_MESSAGE
		rating = testimonial.rating
		
		if is_vk:
			# Обращение из ВК — без оценки
			message = (
				f'💬 Новое обращение из ВК!\n\n'
				f'👤 Имя: {full_name}\n'
				f'🏠 Кафе: {branch.name}\n'
				f'🕒 Время: {timestamp}\n\n'
				f'📝 Сообщение:\n{testimonial.review}'
			)
		elif rating is not None and rating < 5:
			message = (
				f'❗️❗️❗️ ВНИМАНИЕ ❗️❗️❗️ Отзыв с оценкой {rating}/5 {"⭐️" * rating} !!!\n\n'
				f'👤 Имя: {full_name}\n'
				f'📱 Телефон: {testimonial.phone}\n'
				f'🏠 Кафе: {branch.name}\n'
				f'🪑 Стол: {testimonial.table}\n'
				f'🕒 Время: {timestamp}\n\n'
				f'📝 Отзыв:\n{testimonial.review}\n\n'
				f'⚠️ Требуется обратная связь с клиентом!'
			)
		else:
			stars = "⭐️" * (rating if rating else 0)
			message = (
				f'📢 Новый отзыв! {stars}\n\n'
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