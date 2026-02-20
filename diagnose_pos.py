import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from datetime import date, timedelta
from django.db import connection
from django_tenants.utils import get_tenant_model

TenantModel = get_tenant_model()
all_tenants = TenantModel.objects.exclude(schema_name='public')
print("=" * 60)
for t in all_tenants:
    print(f"  {t.schema_name} | {getattr(t, 'name', t)}")
print("=" * 60)

if all_tenants.count() == 1:
    tenant = all_tenants.first()
else:
    s = input("schema_name: ").strip()
    tenant = TenantModel.objects.get(schema_name=s)

connection.set_tenant(tenant)
print(f"✅ Схема: {connection.schema_name}\n")

from apps.tenant.branch.models import Branch
from apps.tenant.stats.iiko import IIKOService
from apps.tenant.stats.dooglys import DooglysService

# Тестируем за последние 7 дней (сегодня может не быть данных)
date_from = date.today() - timedelta(days=7)
date_to   = date.today()
print(f"Период теста: {date_from} → {date_to}\n")

# ── IIKO ────────────────────────────────────────────────────
print("📋 Тест IIKO")
print("-" * 40)
try:
    svc = IIKOService()
    print(f"is_configured = {svc.is_configured}")
    if svc.is_configured:
        token = svc._auth()
        print(f"Токен: {'✅' if token else '❌ не получен'}")
        if token:
            result = svc.get_olap_guests_count(date_from=date_from, date_to=date_to)
            print(f"\nOLAP ответ (UUID → гости): {result}")

            if result:
                print("\nСовпадение с филиалами:")
                for b in Branch.objects.all():
                    oid = getattr(b, 'iiko_organization_id', None)
                    if oid:
                        guests = result.get(oid, 0)
                        ok = oid in result
                        print(f"  [{b.name}]")
                        print(f"    iiko_organization_id = {oid}")
                        print(f"    Гостей за 7 дней     = {guests} {'✅' if ok else '❌ UUID не найден в OLAP'}")
            else:
                print("⚠️  OLAP вернул {} — нет данных за период или ошибка авторизации")
                print("   Сырой ответ API (для отладки):")
                # Повторяем запрос и смотрим raw ответ
                import requests, hashlib
                token2 = svc._auth()
                url = f"{svc.base_url}/resto/api/v2/reports/olap"
                payload = {
                    "reportType": "SALES",
                    "buildSummary": "false",
                    "groupByRowFields": ["Department", "Department.Id"],
                    "groupByColFields": [],
                    "aggregateFields": ["GuestNum"],
                    "filters": {
                        "OpenDate.Typed": {
                            "filterType": "DateRange",
                            "periodType": "CUSTOM",
                            "from": date_from.strftime("%Y-%m-%d"),
                            "to": date_to.strftime("%Y-%m-%d"),
                            "includeLow": True, "includeHigh": True
                        }
                    }
                }
                r = requests.post(url, params={'key': token2}, json=payload,
                                  headers={'Content-Type':'application/json'}, verify=False, timeout=30)
                print(f"   HTTP {r.status_code}")
                print(f"   Body: {r.text[:600]}")
except Exception as e:
    import traceback; traceback.print_exc()

# ── Dooglys ─────────────────────────────────────────────────
print("\n\n📋 Тест Dooglys")
print("-" * 40)
try:
    svc = DooglysService()
    print(f"is_configured = {svc.is_configured}")
    if svc.is_configured:
        count = svc.get_orders_count(date_from=date_from, date_to=date_to)
        print(f"Заказов за 7 дней: {count}")
except Exception as e:
    import traceback; traceback.print_exc()

print("\n" + "=" * 60)