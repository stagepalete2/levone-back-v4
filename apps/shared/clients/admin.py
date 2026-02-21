from django.contrib import admin
from django.utils.html import format_html
from django import forms
from django.utils.safestring import mark_safe

from apps.shared.config.sites import public_admin
from apps.shared.clients.models import Company, CompanyConfig, Domain, KnowledgeBase


class SubdomainWidget(forms.TextInput):
    BASE_DOMAIN = '.levelupapp.ru'

    def format_value(self, value):
        """Отрезаем базовый домен при выводе значения из БД в форму"""
        if value and isinstance(value, str) and value.endswith(self.BASE_DOMAIN):
            return value[:-len(self.BASE_DOMAIN)]
        return value

    def render(self, name, value, attrs=None, renderer=None):
        """Отрисовываем HTML: поле ввода + статический текст"""
        # Получаем значение без .levelupapp.ru
        formatted_value = self.format_value(value)
        # Отрисовываем стандартный input
        html = super().render(name, formatted_value, attrs, renderer)
        # Оборачиваем input и добавляем суффикс
        return mark_safe(
            f'<div style="display:inline-flex; align-items:center; gap:4px;">'
            f'{html} <strong style="color:#555; font-size:13px;">{self.BASE_DOMAIN}</strong>'
            f'</div>'
        )

    def value_from_datadict(self, data, files, name):
        """Склеиваем введенное значение с базовым доменом перед сохранением в БД"""
        value = data.get(name)
        if value:
            # Убираем пробелы и на всякий случай удаляем суффикс, если юзер ввел его вручную
            clean_val = value.strip().replace(self.BASE_DOMAIN, '')
            if clean_val:
                return f"{clean_val}{self.BASE_DOMAIN}"
        return value

class DomainForm(forms.ModelForm):
    class Meta:
        model = Domain
        fields = '__all__'
        # Подключаем наш новый виджет к полю domain
        widgets = {
            'domain': SubdomainWidget(attrs={'placeholder': 'название', 'style': 'width: 120px;'}),
        }
        labels = {
            'domain': 'Поддомен',
            'is_primary': 'Основной домен?',
        }

# 2. Подключаем форму к инлайну
class DomainInline(admin.TabularInline):
    model = Domain
    form = DomainForm
    extra = 1          # Показывать 1 пустую форму при создании
    max_num = 1        # <-- ГЛАВНОЕ: Максимально разрешенное количество доменов (убирает кнопку "Добавить еще")
    # min_num = 1      # <-- Раскомментируйте, если домен строго обязателен для каждого клиента
    verbose_name = 'Домен'
    verbose_name_plural = 'Домен' # Поменял на ед. число, раз он один
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
