# apps/tenant/branch/tasks.py
from celery import shared_task
from apps.tenant.branch.models import BranchTestimonials, Branch
from apps.tenant.branch.core import VKFeedbackService
# Импорт AI сервиса
from django_tenants.utils import schema_context
from apps.tenant.branch.ai import AIService 

@shared_task
def process_ai_review(testimonial_id):
    """Задача классификации отзыва"""
    try:
        review = BranchTestimonials.objects.get(id=testimonial_id)
        AIService.classify_review(review)
    except BranchTestimonials.DoesNotExist:
        pass

@shared_task
def sync_vk_messages_task():
    # Предполагаем, что Branch в public, но данные настроек в tenant-схеме
    for branch in Branch.objects.all():
        with schema_context(branch.company.schema_name):
            VKFeedbackService.fetch_unread_messages(branch)