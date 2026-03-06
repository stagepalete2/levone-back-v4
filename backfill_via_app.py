"""
Скрипт для заполнения via_app флагов у существующих ClientBranch.
Запуск: python manage.py shell < backfill_via_app.py
"""
from django_tenants.utils import get_tenant_model, tenant_context
from django.utils import timezone

TenantModel = get_tenant_model()
tenants = TenantModel.objects.exclude(schema_name='public')

now = timezone.now()
total_joined = 0
total_allowed = 0
total_story = 0

for tenant in tenants:
    with tenant_context(tenant):
        from apps.tenant.branch.models import ClientBranch

        joined = ClientBranch.objects.filter(
            is_joined_community=True,
            joined_community_via_app=False
        ).update(joined_community_via_app=True)

        allowed = ClientBranch.objects.filter(
            is_allowed_message=True,
            allowed_message_via_app=False
        ).update(allowed_message_via_app=True)

        stories = ClientBranch.objects.filter(
            is_story_uploaded=True,
            story_uploaded_at__isnull=True
        )
        story_count = stories.count()
        for cb in stories:
            cb.story_uploaded_at = cb.created_at or now
            cb.save(update_fields=['story_uploaded_at'])

        total_joined += joined
        total_allowed += allowed
        total_story += story_count

        print(f"[{tenant.schema_name}] joined_via_app={joined}, allowed_via_app={allowed}, story_uploaded_at={story_count}")

print(f"\n✅ Готово! Итого: joined={total_joined}, allowed={total_allowed}, story={total_story}")
