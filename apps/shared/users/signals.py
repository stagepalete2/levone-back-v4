from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.contrib.admin.models import LogEntry
from django_tenants.utils import schema_context, get_tenant_model
from django.contrib.auth import get_user_model

User = get_user_model()

@receiver(pre_delete, sender=User)
def clean_up_user_admin_logs(sender, instance, **kwargs):
    """
    Удаляет все записи логов админки (LogEntry) для пользователя 
    во всех схемах БД перед его удалением, чтобы избежать IntegrityError.
    """
    TenantModel = get_tenant_model()
    
    # 1. Сначала удаляем логи в публичной схеме
    with schema_context('public'):
        LogEntry.objects.filter(user=instance).delete()

    # 2. Проходимся по всем остальным схемам клиентов и удаляем логи там
    for tenant in TenantModel.objects.exclude(schema_name='public'):
        with schema_context(tenant.schema_name):
            LogEntry.objects.filter(user=instance).delete()