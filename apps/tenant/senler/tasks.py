# mailing/tasks.py
import logging
from celery import shared_task
from django.utils import timezone
from django_tenants.utils import schema_context
import datetime

from apps.tenant.senler.models import MailingCampaign
from apps.tenant.senler.services import VKService
from apps.tenant.branch.models import ClientBranch
from apps.tenant.inventory.core import InventoryService
from apps.tenant.senler.models import MessageTemplate

logger = logging.getLogger(__name__)

@shared_task
def schedule_post_game_message(client_branch_id, schema_name):
    """Вызывается сразу после игры. Сама вычисляет, когда отправить сообщение."""
    with schema_context(schema_name):
        now = timezone.localtime()
        target_time = now + datetime.timedelta(hours=3)
        
        # Логика "Тихих часов" (21:00 - 09:00)
        if target_time.hour >= 21:
            target_time = target_time + datetime.timedelta(days=1)
            target_time = target_time.replace(hour=9, minute=0, second=0)
        elif target_time.hour < 9:
            target_time = target_time.replace(hour=9, minute=0, second=0)
        
        # Get text from template or use default
        defaults = MessageTemplate.get_defaults()
        msg_text = MessageTemplate.get_text('post_game', defaults.get('post_game', ''))
        
        if msg_text:  # Only send if template is active
            send_single_message.apply_async(
                args=[client_branch_id, msg_text],
                eta=target_time,
                kwargs={'schema_name': schema_name}
            )

@shared_task
def check_birthdays_daily():
    """
    Диспетчер: запускает проверку ДР для каждого тенанта в отдельной задаче.
    """
    from django_tenants.utils import get_tenant_model
    TenantModel = get_tenant_model()
    
    for tenant in TenantModel.objects.exclude(schema_name='public'):
        check_tenant_birthdays.delay(tenant.schema_name)

@shared_task
def check_tenant_birthdays(schema_name):
    """
    Проверка ДР для конкретного тенанта с созданием Кампании для логов.
    """
    with schema_context(schema_name):
        try:
            vk_service = VKService()
            today = timezone.now().date()
            
            # --- Создаем/получаем системную кампанию для логов ---
            campaign_title = f"День Рождения (auto) {today.strftime('%d.%m.%Y')}"
            campaign, _ = MailingCampaign.objects.get_or_create(
                title=campaign_title,
                defaults={
                    'text': 'Автоматическая рассылка ДР',
                    'status': 'completed',
                    'scheduled_at': timezone.now()
                }
            )

            try:
                created_now = InventoryService.grant_birthday_prizes_batch(today)
                if created_now:
                    logger.info(f"[{schema_name}] Emergency grant: {created_now} prizes for TODAY.")
            except Exception as e:
                logger.error(f"Error granting immediate prizes: {e}")

            if vk_service.is_configured:
                clients_today = ClientBranch.objects.filter(
                    birth_date__month=today.month,
                    birth_date__day=today.day
                )
                
                if clients_today.exists():
                    logger.info(f"[{schema_name}] Found {clients_today.count()} birthdays today!")
                    defaults = MessageTemplate.get_defaults()
                    msg_text = MessageTemplate.get_text('birthday_today', defaults.get('birthday_today', ''))
                    if msg_text:
                        vk_service.send_batch_messages(list(clients_today), msg_text, campaign=campaign)
                else:
                    logger.debug(f"[{schema_name}] No birthdays today.")

            # -----------------------------------------------------------
            # 1. ЗА 7 ДНЕЙ: Выдача подарка + Сообщение
            # -----------------------------------------------------------
            target_date_7 = today + datetime.timedelta(days=7)
            created_prizes = InventoryService.grant_birthday_prizes_batch(target_date_7)
            if created_prizes > 0:
                logger.info(f"[{schema_name}] Granted {created_prizes} birthday prizes.")
            # А) Начисляем подарок (не зависит от ВК)

            # Б) Отправляем сообщение
            if vk_service.is_configured:
                clients_7 = ClientBranch.objects.filter(
                    birth_date__month=target_date_7.month,
                    birth_date__day=target_date_7.day
                )
                if clients_7.exists():
                    defaults = MessageTemplate.get_defaults()
                    msg_text = MessageTemplate.get_text('birthday_7days', defaults.get('birthday_7days', ''))
                    if msg_text:
                        vk_service.send_batch_messages(list(clients_7), msg_text, campaign=campaign)

            # -----------------------------------------------------------
            # 2. ЗА 1 ДЕНЬ: Напоминание
            # -----------------------------------------------------------
            if vk_service.is_configured:
                target_date_1 = today + datetime.timedelta(days=1)
                clients_1 = ClientBranch.objects.filter(
                    birth_date__month=target_date_1.month,
                    birth_date__day=target_date_1.day
                )
                if clients_1.exists():
                    defaults = MessageTemplate.get_defaults()
                    msg_text = MessageTemplate.get_text('birthday_1day', defaults.get('birthday_1day', ''))
                    if msg_text:
                        vk_service.send_batch_messages(list(clients_1), msg_text, campaign=campaign)

            # -----------------------------------------------------------
            # 3. СПУСТЯ 3 ДНЯ: Аннулирование (если не активирован)
            # -----------------------------------------------------------
            revoked_count = InventoryService.revoke_expired_birthday_prizes()
            if revoked_count > 0:
                    logger.info(f"[{schema_name}] Revoked {revoked_count} expired birthday prizes.")

        except Exception as e:
            logger.error(f"Error checking birthdays for tenant {schema_name}: {e}")

@shared_task
def send_single_message(client_branch_id, text, attachment=None, campaign_id=None, schema_name=None):
    """Задача для отправки ОДНОГО сообщения (используется в post-game)"""
    if schema_name:
        with schema_context(schema_name):
            _perform_send_single(client_branch_id, text, attachment, campaign_id)
    else:
        _perform_send_single(client_branch_id, text, attachment, campaign_id)

def _perform_send_single(client_branch_id, text, attachment, campaign_id):
    try:
        cb = ClientBranch.objects.get(id=client_branch_id)
        campaign = MailingCampaign.objects.get(id=campaign_id) if campaign_id else None
        
        service = VKService()
        if service.is_configured:
            service.send_message(cb, text, attachment, campaign)
    except ClientBranch.DoesNotExist:
        pass

# --- Основная логика массовой рассылки ---

@shared_task
def process_mass_campaign(campaign_id, schema_name):
    """
    Диспетчер: определяет аудиторию и создает задачи-чанки.
    Не отправляет сообщения сам, только нарезает задачи.
    """
    logger.debug(f"Task started. Schema: {schema_name}, Campaign ID: {campaign_id}")
    with schema_context(schema_name):
        try:
            campaign = MailingCampaign.objects.get(id=campaign_id)
            logger.debug(f"Campaign found: {campaign}")
        except MailingCampaign.DoesNotExist:
            logger.error(f"Campaign {campaign_id} not found in schema {schema_name}!")
            return



        qs = ClientBranch.objects.none()
        
        if campaign.specific_clients.exists():
            qs = campaign.specific_clients.filter(client__vk_user_id__isnull=False)
        elif campaign.send_to_all:
            qs = ClientBranch.objects.filter(client__vk_user_id__isnull=False)
        elif campaign.segment:
            qs = ClientBranch.objects.filter(rf_score__segment=campaign.segment, client__vk_user_id__isnull=False)
            
        # Оптимизация: берем только ID, чтобы не тянуть объекты в память
        client_ids = list(qs.values_list('id', flat=True))
        
        if not client_ids:
            campaign.status = 'completed'
            campaign.save()
            return

        # --- ЛОГИКА ЗАГРУЗКИ КАРТИНКИ В ВК ---
        attachment_str = None
        if campaign.image and client_ids:
            try:
                service = VKService()
                if service.is_configured:
                    # Для сообщества нужен валидный peer_id. Берем первого клиента.
                    first_client_id = client_ids[0]
                    first_client = ClientBranch.objects.get(id=first_client_id)
                    peer_id = first_client.client.vk_user_id
                    
                    if peer_id:
                        logger.debug(f"Uploading image {campaign.image.path} for peer_id={peer_id}...")
                        attachment_str = service.upload_image_to_vk(campaign.image.path, peer_id=peer_id)
                        if attachment_str:
                            logger.debug(f"Image uploaded. Attachment: {attachment_str}")
                        else:
                            logger.error("Failed to upload image to VK")
            except Exception as e:
                logger.error(f"Error processing image for campaign {campaign_id}: {e}")
        # -------------------------------------

        # Разбиваем список ID на чанки по 100
        batch_size = 100 
        for i in range(0, len(client_ids), batch_size):
            chunk_ids = client_ids[i:i + batch_size]
            
            send_campaign_chunk.delay(
                campaign_id=campaign.id,
                client_ids=chunk_ids,
                schema_name=schema_name,
                attachment=attachment_str  # Передаём attachment через аргумент
            )
        
        # Update segment's last_campaign_date if campaign was sent to a segment
        if campaign.segment:
            from django.utils import timezone
            campaign.segment.last_campaign_date = timezone.now()
            campaign.segment.save(update_fields=['last_campaign_date'])
            logger.info(f"Updated last_campaign_date for segment '{campaign.segment.name}'")
        
        campaign.status = 'completed'
        campaign.save()

@shared_task(bind=True, rate_limit='2/s', max_retries=3)
def send_campaign_chunk(self, campaign_id, client_ids, schema_name, attachment=None):
    """
    Воркер: Получает список ID и отправляет их через VK Service.
    """
    try:
        with schema_context(schema_name):
            campaign = MailingCampaign.objects.get(id=campaign_id)
            
            # Получаем объекты ClientBranch по переданным ID
            clients = ClientBranch.objects.filter(id__in=client_ids).select_related('client')
            
            service = VKService()
            service.send_batch_messages(
                client_branches=clients,
                text=campaign.text,
                attachment=attachment,  # Используем переданный attachment
                campaign=campaign
            )
    except Exception as exc:
        raise self.retry(exc=exc, countdown=5)