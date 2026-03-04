from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.contrib.admin.models import LogEntry
from django_tenants.utils import schema_context, get_tenant_model
from django.contrib.auth import get_user_model

User = get_user_model()

@receiver(pre_delete, sender=User)
def clean_up_user_tenant_refs(sender, instance, **kwargs):
    """
    Перед удалением пользователя вручную чистим все FK-ссылки
    в tenant-схемах, чтобы избежать ProgrammingError (таблица не найдена
    в публичной схеме, когда Django пытается выполнить SET_NULL).
    """
    from apps.tenant.branch.models import TestimonialReply

    TenantModel = get_tenant_model()

    for tenant in TenantModel.objects.exclude(schema_name='public'):
        with schema_context(tenant.schema_name):
            LogEntry.objects.filter(user=instance).delete()
            TestimonialReply.objects.filter(sent_by=instance).update(sent_by=None)

    # Логи в публичной схеме
    with schema_context('public'):
        LogEntry.objects.filter(user=instance).delete()