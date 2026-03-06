"""
КОРРЕКТИРУЮЩИЙ скрипт: сбрасывает ЛОЖНЫЕ via_app флаги.

Проблема: предыдущий backfill ставил via_app=True ВСЕМ подписчикам,
включая тех, кто был подписан ДО нашего приложения.

Логика исправления:
- Если via_app=True, но via_app_at IS NULL — значит флаг поставлен
  старым backfill-ом (а не реальным PATCH запросом из приложения).
  PATCH всегда ставит _at вместе с via_app → NULL = ложное срабатывание.
- Сбрасываем via_app → False для таких записей.
- story_uploaded_at оставляем как есть (там fallback на created_at корректен).

Запуск: python manage.py shell < backfill_via_app.py
"""
from django_tenants.utils import get_tenant_model, tenant_context
from django.utils import timezone

TenantModel = get_tenant_model()
tenants = TenantModel.objects.exclude(schema_name='public')

total_fixed_joined = 0
total_fixed_allowed = 0

for tenant in tenants:
    with tenant_context(tenant):
        from apps.tenant.branch.models import ClientBranch

        # Сбрасываем joined_community_via_app, если _at = NULL
        # (значит поставлен старым backfill-ом, а не реальным PATCH)
        fixed_joined = ClientBranch.objects.filter(
            joined_community_via_app=True,
            joined_community_via_app_at__isnull=True
        ).update(joined_community_via_app=False)

        # Сбрасываем allowed_message_via_app, если _at = NULL
        fixed_allowed = ClientBranch.objects.filter(
            allowed_message_via_app=True,
            allowed_message_via_app_at__isnull=True
        ).update(allowed_message_via_app=False)

        total_fixed_joined += fixed_joined
        total_fixed_allowed += fixed_allowed

        print(f"[{tenant.schema_name}] RESET: joined_via_app={fixed_joined}, allowed_via_app={fixed_allowed}")

print(f"\n✅ Готово! Сброшено ложных флагов: joined={total_fixed_joined}, allowed={total_fixed_allowed}")
print("Теперь via_app=True останется ТОЛЬКО у тех, кто реально подписался через приложение (есть _at дата).")
