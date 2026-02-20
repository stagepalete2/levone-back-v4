import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from apps.shared.clients.models import Company, Domain

company = Company.objects.get(schema_name='asap_bryansk')

domains_data = []
for domain in company.domains.all():
    domains_data.append({
        'domain': domain.domain,
        'is_primary': domain.is_primary
    })
    domain.delete()

Company.objects.filter(schema_name='asap_bryansk').update(id=8)

updated_company = Company.objects.get(schema_name='asap_bryansk')

for data in domains_data:
    Domain.objects.create(tenant=updated_company, **data)

print("ID успешно изменен, домены перепривязаны!")