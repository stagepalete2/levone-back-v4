from celery import shared_task
from django_tenants.utils import get_tenant_model, schema_context

from apps.tenant.stats.core import RFManagementService

@shared_task
def recalculate_rf_matrix_task():
    """Ежедневный (или еженедельный) пересчет RF-матрицы для всех клиентов"""
    TenantModel = get_tenant_model()
    
    # Итерируемся по всем тенантам
    for tenant in TenantModel.objects.exclude(schema_name='public'):
        with schema_context(tenant.schema_name):
            try:
                # Запускаем пересчет внутри контекста схемы
                # run_recalculation сам найдет branch(и) внутри схемы
                result = RFManagementService.run_recalculation()
                if not result['success']:
                    print(f"Error recalculating RF for {tenant.schema_name}: {result.get('error')}")
                else:
                    print(f"RF Recalculated for {tenant.schema_name}: {result['processed']} branches processed.")
            except Exception as e:
                print(f"Critical error recalculating RF for {tenant.schema_name}: {e}")
