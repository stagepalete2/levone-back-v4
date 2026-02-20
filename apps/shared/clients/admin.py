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
    list_display = ('name', 'get_primary_domain', 'display_id', 'is_active', 'paid_until', 'go_to_admin_link', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name',)
    inlines = [DomainInline]

    def get_primary_domain(self, obj):
        domain = obj.get_primary_domain()
        return domain.domain if domain else '—'
    get_primary_domain.short_description = 'Домен'

    def display_id(self, obj):
        return obj.id - 1 if obj.id is not None else '-'
    display_id.short_description = 'ID'
    display_id.admin_order_field = 'id'

    def go_to_admin_link(self, obj):
        domain = obj.get_primary_domain()
        if domain:
            url = f'https://{domain.domain}/admin'
            return format_html(
                '<a href="{}" target="_blank" class="button" '
                'style="background:#28a745;color:#fff;padding:4px 12px;border-radius:4px;'
                'font-size:11px;text-decoration:none;font-weight:600;">'
                '🔗 Открыть админку</a>',
                url
            )
        return '—'
    go_to_admin_link.short_description = 'Перейти'


@admin.register(CompanyConfig, site=public_admin)
class CompanyConfigAdmin(admin.ModelAdmin):
    list_display = ('company', 'vk_group_name', 'vk_group_id', 'vk_mini_app_id')
    search_fields = ('company__name',)
    fieldsets = [
        (None, {
            'fields': ('company',),
        }),
        ('Внешний вид', {
            'fields': ('logotype_image', 'coin_image'),
        }),
        ('ВКонтакте', {
            'fields': ('vk_group_name', 'vk_group_id', 'vk_mini_app_id'),
            'description': (
                'vk_mini_app_id — числовой ID мини-приложения. '
                'Используется для генерации ссылок и QR-кодов на столики в клиентской админке.'
            ),
        }),
        ('IIKO', {
            'fields': ('iiko_api_url', 'iiko_api_login', 'iiko_api_password'),
        }),
        ('Dooglys', {
            'fields': ('dooglys_api_url', 'dooglys_api_token'),
        }),
    ]


@admin.register(KnowledgeBase, site=public_admin)
class KnowledgeBaseAdmin(admin.ModelAdmin):
    list_display = ('company', 'updated_at')
    search_fields = ('company__name',)
