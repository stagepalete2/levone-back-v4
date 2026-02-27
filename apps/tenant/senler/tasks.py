# senler/tasks.py
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

        # Тихие часы (21:00 - 09:00)
        if target_time.hour >= 21:
            target_time = target_time + datetime.timedelta(days=1)
            target_time = target_time.replace(hour=9, minute=0, second=0)
        elif target_time.hour < 9:
            target_time = target_time.replace(hour=9, minute=0, second=0)

        defaults = MessageTemplate.get_defaults()
        msg_text = MessageTemplate.get_text('post_game', defaults.get('post_game', ''))

        # И передается в Celery как готовая строка
        send_single_message.apply_async(
            args=[client_branch_id, msg_text],
            eta=target_time,
            kwargs={'schema_name': schema_name},
        )


@shared_task
def check_birthdays_daily():
    """Диспетчер: запускает проверку ДР для каждого тенанта."""
    from django_tenants.utils import get_tenant_model
    TenantModel = get_tenant_model()

    for tenant in TenantModel.objects.exclude(schema_name='public'):
        check_tenant_birthdays.delay(tenant.schema_name)


@shared_task
def check_tenant_birthdays(schema_name):
    """
    Ежедневная проверка ДР для конкретного тенанта.

    Логика:
      1. За 7 дней до ДР — выдача подарка + сообщение «через неделю твой ДР»
      2. В день ДР     — сообщение «с ДР!» (подарок уже был выдан на шаге 1 или 0 дней)
      3. Аннулирование — удаляем не активированные призы через 5+1 дней после ДР
    """
    with schema_context(schema_name):
        try:
            vk_service = VKService()
            today = timezone.now().date()

            campaign_title = f"День Рождения (auto) {today.strftime('%d.%m.%Y')}"
            campaign, _ = MailingCampaign.objects.get_or_create(
                title=campaign_title,
                defaults={
                    'text': 'Автоматическая рассылка ДР',
                    'status': 'completed',
                    'scheduled_at': timezone.now(),
                },
            )

            # ----------------------------------------------------------
            # ЗА 7 ДНЕЙ: выдача подарка + первое сообщение
            # ----------------------------------------------------------
            target_date_7 = today + datetime.timedelta(days=7)
            created_prizes = InventoryService.grant_birthday_prizes_batch(target_date_7)
            if created_prizes > 0:
                logger.info(f"[{schema_name}] Granted {created_prizes} birthday prizes (7d ahead).")

            if vk_service.is_configured:
                clients_7 = ClientBranch.objects.filter(
                    birth_date__month=target_date_7.month,
                    birth_date__day=target_date_7.day,
                )
                if clients_7.exists():
                    defaults = MessageTemplate.get_defaults()
                    msg_text = MessageTemplate.get_text('birthday_7days', defaults.get('birthday_7days', ''))
                    if msg_text:
                        vk_service.send_batch_messages(list(clients_7), msg_text, campaign=campaign)

            # ----------------------------------------------------------
            # В ДЕНЬ ДР: сообщение + экстренная выдача если не было
            # ----------------------------------------------------------
            try:
                created_now = InventoryService.grant_birthday_prizes_batch(today)
                if created_now:
                    logger.info(f"[{schema_name}] Emergency grant: {created_now} prizes for TODAY.")
            except Exception as e:
                logger.error(f"Error granting immediate prizes: {e}")

            if vk_service.is_configured:
                clients_today = ClientBranch.objects.filter(
                    birth_date__month=today.month,
                    birth_date__day=today.day,
                )
                if clients_today.exists():
                    logger.info(f"[{schema_name}] Found {clients_today.count()} birthdays today!")
                    defaults = MessageTemplate.get_defaults()
                    msg_text = MessageTemplate.get_text('birthday_today', defaults.get('birthday_today', ''))
                    if msg_text:
                        vk_service.send_batch_messages(list(clients_today), msg_text, campaign=campaign)
                else:
                    logger.debug(f"[{schema_name}] No birthdays today.")

            # ----------------------------------------------------------
            # АННУЛИРОВАНИЕ просроченных призов (окно ±5 дней закрылось)
            # ----------------------------------------------------------
            revoked_count = InventoryService.revoke_expired_birthday_prizes()
            if revoked_count > 0:
                logger.info(f"[{schema_name}] Revoked {revoked_count} expired birthday prizes.")

        except Exception as e:
            logger.error(f"Error checking birthdays for tenant {schema_name}: {e}")


@shared_task
def send_single_message(client_branch_id, text, attachment=None, campaign_id=None, schema_name=None, template_type=None):
    """Задача для отправки ОДНОГО сообщения."""
    if schema_name:
        with schema_context(schema_name):
            _perform_send_single(client_branch_id, text, attachment, campaign_id, template_type)
    else:
        _perform_send_single(client_branch_id, text, attachment, campaign_id, template_type)

def _perform_send_single(client_branch_id, text, attachment, campaign_id, template_type=None):
    from apps.tenant.senler.models import MessageTemplate # Импортируем локально во избежание циклических импортов
    
    try:
        cb = ClientBranch.objects.get(id=client_branch_id)
        
        # Если передан template_type, достаем актуальный текст из БД прямо сейчас
        if template_type and not text:
            defaults = MessageTemplate.get_defaults()
            text = MessageTemplate.get_text(template_type, defaults.get(template_type, ''))
            
        if not text:
            return # Если текста совсем нет, ничего не отправляем
            
        campaign = MailingCampaign.objects.get(id=campaign_id) if campaign_id else None
        service = VKService()
        if service.is_configured:
            service.send_message(cb, text, attachment, campaign)
    except ClientBranch.DoesNotExist:
        pass
# --- Основная логика массовой рассылки ---

@shared_task
def process_mass_campaign(campaign_id, schema_name):
    """Диспетчер: определяет аудиторию, фильтрует по полу и создаёт задачи-чанки."""
    logger.debug(f"Task started. Schema: {schema_name}, Campaign ID: {campaign_id}")
    with schema_context(schema_name):
        try:
            campaign = MailingCampaign.objects.get(id=campaign_id)
        except MailingCampaign.DoesNotExist:
            logger.error(f"Campaign {campaign_id} not found in schema {schema_name}!")
            return

        qs = ClientBranch.objects.none()

        if campaign.specific_clients.exists():
            qs = campaign.specific_clients.filter(client__vk_user_id__isnull=False)
        elif campaign.send_to_all:
            qs = ClientBranch.objects.filter(client__vk_user_id__isnull=False)
        elif campaign.segment:
            qs = ClientBranch.objects.filter(
                rf_score__segment=campaign.segment,
                client__vk_user_id__isnull=False,
            )

        if campaign.send_by_sex != 0:
            qs = qs.filter(client__sex=campaign.send_by_sex)

        client_ids = list(qs.values_list('id', flat=True))

        if not client_ids:
            logger.info(f"No clients found for campaign {campaign_id} after filtering.")
            campaign.status = 'completed'
            campaign.save()
            return

        attachment_str = None
        if campaign.image and client_ids:
            pass  # логика загрузки картинки в ВК (без изменений)

        batch_size = 100
        for i in range(0, len(client_ids), batch_size):
            chunk_ids = client_ids[i:i + batch_size]
            send_campaign_chunk.delay(
                campaign_id=campaign.id,
                client_ids=chunk_ids,
                schema_name=schema_name,
                attachment=attachment_str,
            )

        if campaign.segment:
            campaign.segment.last_campaign_date = timezone.now()
            campaign.segment.save(update_fields=['last_campaign_date'])

        campaign.status = 'completed'
        campaign.save()


@shared_task(bind=True, rate_limit='2/s', max_retries=3)
def send_campaign_chunk(self, campaign_id, client_ids, schema_name, attachment=None):
    """Воркер: отправляет чанк клиентов через VK Service."""
    try:
        with schema_context(schema_name):
            campaign = MailingCampaign.objects.get(id=campaign_id)
            clients = ClientBranch.objects.filter(id__in=client_ids).select_related('client')
            service = VKService()
            service.send_batch_messages(
                client_branches=clients,
                text=campaign.text,
                attachment=attachment,
                campaign=campaign,
            )
    except Exception as exc:
        raise self.retry(exc=exc, countdown=5)
