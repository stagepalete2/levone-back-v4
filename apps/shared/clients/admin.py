from django.contrib import admin
from django.utils.html import format_html

from apps.shared.config.sites import public_admin
from apps.shared.clients.models import Company, CompanyConfig, Domain, KnowledgeBase


class DomainInline(admin.TabularInline):
    model = Domain
    extra = 1
    verbose_name = 'Домен'
    verbose_name_plural = 'Домены'
    fields = ('domain', 'is_primary')


@admin.register(Company, site=public_admin)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ('name', 'get_primary_domain',  'display_id', 'is_active', 'paid_until', 'go_to_admin_link', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name',)
    inlines = [DomainInline]

    def get_primary_domain(self, obj):
        domain = obj.get_primary_domain()
        if domain:
            return domain.domain
        return '—'
    get_primary_domain.short_description = 'Домен'

    def go_to_admin_link(self, obj):
        domain = obj.get_primary_domain()
        if domain:
            url = f'https://{domain.domain}/admin'
            return format_html(
                '<a href="{}" target="_blank" class="button" style="'
                'background:#28a745;color:#fff;padding:4px 12px;border-radius:4px;'
                'font-size:11px;text-decoration:none;font-weight:600;">'
                '🔗 Открыть админку</a>',
                url
            )
        return '—'
    go_to_admin_link.short_description = 'Перейти'
    go_to_admin_link.allow_tags = True


    def display_id(self, obj):
        # Если объект существует, вычитаем 1 из его реального ID
        if obj.id is not None:
            return obj.id - 1
        return '-'

    # Возвращаем колонке красивое название (иначе она назовется "Display id")
    display_id.short_description = 'ID'
    
    # Включаем возможность сортировки по этой колонке (по реальному id в базе)
    display_id.admin_order_field = 'id'


@admin.register(CompanyConfig, site=public_admin)
class CompanyConfigAdmin(admin.ModelAdmin):
    list_display = ('company', 'vk_group_name', 'vk_group_id')
    search_fields = ('company__name',)


@admin.register(KnowledgeBase, site=public_admin)
class KnowledgeBaseAdmin(admin.ModelAdmin):
    list_display = ('company', 'updated_at')
    search_fields = ('company__name',)
