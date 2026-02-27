import logging
from celery import shared_task
from django.utils import timezone
from django.db import transaction

from django_tenants.utils import tenant_context, get_tenant_model
from apps.shared.config.utils import generate_code

# Настраиваем логгер, чтобы видеть ошибки в Celery логах
logger = logging.getLogger(__name__)

# --- Orchestrators (Главные задачи-менеджеры) ---

@shared_task()
def generate_daily_code_for_all_tenants():
    """Запускает генерацию кодов для каждого тенанта отдельно"""
    # Получаем модель тенанта динамически внутри задачи, чтобы избежать проблем при импорте
    TenantModel = get_tenant_model()
    
    # Исключаем public и берем ID
    tenants = TenantModel.objects.exclude(schema_name='public').values_list('pk', flat=True)
    
    logger.info(f"Starting daily code generation for {len(tenants)} tenants.")
    
    for tenant_id in tenants:
        # Приводим к строке для безопасности сериализации (если используете UUID)
        process_tenant_daily_codes.delay(str(tenant_id))

@shared_task()
def daily_rfm_update():
    """Запускает расчет RFM для каждого тенанта отдельно"""
    TenantModel = get_tenant_model()
    tenants = TenantModel.objects.exclude(schema_name='public').values_list('pk', flat=True)
    
    logger.info(f"Starting RFM update for {len(tenants)} tenants.")
    
    for tenant_id in tenants:
        process_tenant_rfm.delay(str(tenant_id))


# --- Workers (Задачи-исполнители для конкретного тенанта) ---

@shared_task()
def process_tenant_daily_codes(tenant_id):
    TenantModel = get_tenant_model()
    try:
        tenant = TenantModel.objects.get(pk=tenant_id)
    except TenantModel.DoesNotExist:
        logger.error(f"Tenant {tenant_id} not found!")
        return

    today = timezone.localdate()
    
    with tenant_context(tenant):
        # Импорты внутри контекста тенанта — это важно!
        from apps.tenant.branch.models import Branch
        from apps.tenant.game.models import DailyCode as GameDailyCodes
        from apps.tenant.quest.models import DailyCode as QuestDailyCodes
        from apps.tenant.branch.models import DailyCode as BranchDailyCodes
        
        branches = Branch.objects.all()
        logger.info(f"Processing daily codes for tenant {tenant.schema_name}: {len(branches)} branches")

        for branch in branches:
            try:
                with transaction.atomic():
                    # Game Code
                    GameDailyCodes.objects.get_or_create(
                        date=today,
                        branch=branch,
                        defaults={"code": generate_code()},
                    )

                    # Quest Code
                    QuestDailyCodes.objects.get_or_create(
                        date=today,
                        branch=branch,
                        defaults={"code": generate_code()},
                    )

                    # Birthday Prize Code (НОВОЕ)
                    BranchDailyCodes.objects.get_or_create(
                        date=today,
                        branch=branch,
                        defaults={"code": generate_code()},
                    )

            except Exception as e:
                logger.error(f"Error generating codes for branch {branch.id} in tenant {tenant.schema_name}: {e}")

@shared_task()
def process_tenant_rfm(tenant_id):
    TenantModel = get_tenant_model()
    try:
        tenant = TenantModel.objects.get(pk=tenant_id)
    except TenantModel.DoesNotExist:
        logger.error(f"Tenant {tenant_id} not found!")
        return
    
    with tenant_context(tenant):
        # Импорты внутри
        from apps.tenant.branch.models import Branch
        from apps.tenant.stats.models import RFSegment, BranchSegmentSnapshot
        from apps.tenant.stats.core import RFCalculator
        from django.db.models import Count, Q
        
        today = timezone.localdate() # Лучше использовать timezone.localdate()
        branches = Branch.objects.all()
        
        logger.info(f"Processing RFM for tenant {tenant.schema_name}: {len(branches)} branches")
        
        for branch in branches:
            try:
                # 1. Запускаем калькулятор
                calc = RFCalculator(branch)
                calc.run_analysis()

                # 2. Агрегируем данные
                # ВАЖНО: убедитесь, что guestrfscore__client__branch правильно связан
                segment_stats = RFSegment.objects.annotate(
                    real_count=Count(
                        'guestrfscore',
                        filter=Q(guestrfscore__client__branch=branch),
                        distinct=True
                    )
                )

                # 3. Создаем записи истории
                for seg in segment_stats:
                    BranchSegmentSnapshot.objects.update_or_create(
                        branch=branch,
                        segment=seg,
                        date=today,
                        defaults={'guests_count': seg.real_count}
                    )
                
                logger.info(f"RFM snapshot success: branch {branch.id}")

            except Exception as e:
                logger.error(f"Error in RFM process for branch {branch.id} (tenant {tenant.schema_name}): {e}", exc_info=True)