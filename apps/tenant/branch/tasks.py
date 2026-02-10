# apps/tenant/branch/tasks.py
from celery import shared_task
from apps.tenant.branch.models import BranchTestimonials, Branch
from apps.tenant.branch.core import VKFeedbackService
# Импорт AI сервиса
from django_tenants.utils import schema_context
from apps.tenant.branch.ai import AIService 

@shared_task
def process_ai_review(testimonial_id, schema_name):
    """Задача классификации отзыва"""
    with schema_context(schema_name):
        try:
            review = BranchTestimonials.objects.get(id=testimonial_id)
            AIService.classify_review(review)
        except BranchTestimonials.DoesNotExist:
            pass

@shared_task
def sync_vk_messages_task():
    """Регулярная синхронизация сообщений ВК для всех тенантов"""
    from django_tenants.utils import get_tenant_model
    TenantModel = get_tenant_model()
    
    # Итерируемся по всем тенантам (кроме public)
    for tenant in TenantModel.objects.exclude(schema_name='public'):
        try:
            with schema_context(tenant.schema_name):
                # Внутренняя логика работает уже в контексте схемы
                for branch in Branch.objects.all():
                    VKFeedbackService.fetch_unread_messages(branch)
                
                # Синхронизация статуса прочтения сообщений (open rate)
                from apps.tenant.senler.services import VKService
                vk_service = VKService()
                if vk_service.is_configured:
                    updated = vk_service.sync_messages_read_status()
                    if updated:
                        print(f"[{tenant.schema_name}] Updated {updated} message read statuses")
        except Exception as e:
            print(f"Error syncing VK messages for schema {tenant.schema_name}: {e}")

@shared_task
def reclassify_waiting_reviews():
    """Задача для запуска классификации по всем старым/необработанным отзывам"""
    from django_tenants.utils import get_tenant_model
    TenantModel = get_tenant_model()
    
    count = 0
    
    for tenant in TenantModel.objects.exclude(schema_name='public'):
        with schema_context(tenant.schema_name):
            pending_reviews = BranchTestimonials.objects.filter(
                sentiment=BranchTestimonials.Sentiment.WAITING
            )
            for review in pending_reviews:
                process_ai_review.delay(review.id, tenant.schema_name)
                count += 1
                
    return f"Triggered {count} waiting reviews for classification."