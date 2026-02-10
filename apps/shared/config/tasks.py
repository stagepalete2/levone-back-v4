from celery import shared_task
from django.utils import timezone

from django_tenants.utils import tenant_context, get_tenant_model
from apps.shared.config.utils import generate_code

from apps.tenant.branch.models import Branch
from apps.tenant.stats.core import RFCalculator

# Рекомендуется использовать get_tenant_model для гибкости django-tenants
TenantModel = get_tenant_model()

# --- Orchestrators (Главные задачи-менеджеры) ---

@shared_task(name="administration.tasks.generate_daily_code_for_all_tenants")
def generate_daily_code_for_all_tenants():
    """Запускает генерацию кодов для каждого тенанта отдельно"""
    tenants = TenantModel.objects.exclude(schema_name='public').values_list('pk', flat=True)
    for tenant_id in tenants:
        process_tenant_daily_codes.delay(tenant_id)

@shared_task(name='administration.tasks.daily_rfm_update')
def daily_rfm_update():
    """Запускает расчет RFM для каждого тенанта отдельно"""
    tenants = TenantModel.objects.exclude(schema_name='public').values_list('pk', flat=True)
    for tenant_id in tenants:
        process_tenant_rfm.delay(tenant_id)


# --- Workers (Задачи-исполнители для конкретного тенанта) ---

@shared_task(name="administration.tasks.process_tenant_daily_codes")
def process_tenant_daily_codes(tenant_id):
    from apps.tenant.game.models import DailyCode as GameDailyCodes
    from apps.tenant.quest.models import DailyCode as QuestDailyCodes
    
    tenant = TenantModel.objects.get(pk=tenant_id)
    today = timezone.localdate()
    
    with tenant_context(tenant):
        branches = Branch.objects.all()
        for branch in branches:
            # Используем один и тот же код, если это логика бизнеса, 
            # либо генерируем разные внутри defaults
            GameDailyCodes.objects.get_or_create(
                date=today,
                branch=branch,
                defaults={"code": generate_code()},
            )
            QuestDailyCodes.objects.get_or_create(
                date=today,
                branch=branch,
                defaults={"code": generate_code()},
            )

@shared_task(name="administration.tasks.process_tenant_rfm")
def process_tenant_rfm(tenant_id):
    tenant = TenantModel.objects.get(pk=tenant_id)
    
    with tenant_context(tenant):
        from apps.tenant.stats.models import RFSegment, BranchSegmentSnapshot, GuestRFScore
        from django.db.models import Count, Q
        from django.utils.timezone import now
        
        today = now().date()
        branches = Branch.objects.all()
        
        for branch in branches:
            try:
                # 1. Запускаем калькулятор (обновляет GuestRFScore)
                calc = RFCalculator(branch)
                calc.run_analysis()

                # 2. Агрегируем данные
                segment_stats = RFSegment.objects.annotate(
                    real_count=Count(
                        'guestrfscore',
                        filter=Q(guestrfscore__client__branch=branch),
                        distinct=True
                    )
                )

                # 3. Создаем записи истории. 
                # Используем update_or_create только для защиты от повторного запуска в тот же день
                for seg in segment_stats:
                    BranchSegmentSnapshot.objects.update_or_create(
                        branch=branch,
                        segment=seg,
                        date=today, # Важно: привязка к дате
                        defaults={'guests_count': seg.real_count}
                    )
                
                print(f"History snapshot created for branch {branch.id} on {today}")

            except Exception as e:
                print(f"Error in RFM process for branch {branch.id}: {e}")


