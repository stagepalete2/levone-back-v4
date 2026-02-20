from django.contrib import admin

from apps.shared.config.sites import public_admin

from apps.shared.clients.models import Company, CompanyConfig, Domain, KnowledgeBase

class CompanyAdmin(admin.ModelAdmin):
    # Заменяем 'id' на имя нашего нового метода 'display_id'
    list_display = ['name', 'display_id', 'is_active', 'paid_until']

    def display_id(self, obj):
        # Если объект существует, вычитаем 1 из его реального ID
        if obj.id is not None:
            return obj.id - 1
        return '-'

    # Возвращаем колонке красивое название (иначе она назовется "Display id")
    display_id.short_description = 'ID'
    
    # Включаем возможность сортировки по этой колонке (по реальному id в базе)
    display_id.admin_order_field = 'id'
public_admin.register(Company, CompanyAdmin)
public_admin.register(Domain)
public_admin.register(CompanyConfig)
public_admin.register(KnowledgeBase)