# admin.py
from apps.shared.config.sites import tenant_admin
from django.contrib import admin
from django.utils.timezone import now
from django.db import connection
from django.db.models import Count, Q
from apps.tenant.senler.models import MailingCampaign, VKConnection, MessageLog
from apps.tenant.senler.tasks import process_mass_campaign

class VKConnectionAdmin(admin.ModelAdmin):
    list_display = ('group_id', 'updated_at')

class MailingCampaignAdmin(admin.ModelAdmin):
    list_display = ('title', 'status', 'created_at', 'get_stats')
    list_filter = ('status', 'segment')
    filter_horizontal = ('specific_clients',)
    actions = ['send_campaign']

    class Media:
        js = (
            'https://code.jquery.com/jquery-3.6.0.min.js',
            'senler/js/mailing_ai.js',
        )

    def get_queryset(self, request):
        # Оптимизация: Сразу считаем агрегацию, чтобы не делать запросы в get_stats
        qs = super().get_queryset(request)
        return qs.annotate(
            total_logs=Count('logs'),
            sent_logs=Count('logs', filter=Q(logs__status='sent')),
            blocked_logs=Count('logs', filter=Q(logs__status='blocked'))
        )

    def send_campaign(self, request, queryset):
        """
        Action для массового запуска рассылок.
        Запускает Celery задачу напрямую, минуя save_model.
        """
        # Фильтруем только черновики
        drafts = queryset.filter(status='draft')
        count = 0
        
        for campaign in drafts:
            # Обновляем статус и время
            campaign.status = 'scheduled' 
            campaign.scheduled_at = now()
            # Сохраняем БЕЗ триггера Celery (используя update_fields)
            campaign.save(update_fields=['status', 'scheduled_at'])
            
            # Запускаем Celery задачу напрямую
            process_mass_campaign.apply_async(
                args=[campaign.id, connection.schema_name],
                eta=campaign.scheduled_at
            )
            count += 1
            
        self.message_user(request, f"Запланировано рассылок: {count}")

    send_campaign.short_description = "Запустить выбранные рассылки"

    def get_stats(self, obj):
        total = getattr(obj, 'total_logs', obj.logs.count())
        sent = getattr(obj, 'sent_logs', obj.logs.filter(status='sent').count())
        blocked = getattr(obj, 'blocked_logs', obj.logs.filter(status='blocked').count())
        return f"Всего: {total} | OK: {sent} | Блок: {blocked}"
    get_stats.short_description = "Статистика"

    def save_model(self, request, obj, form, change):
        """
        Перехватываем сохранение модели.
        Запускаем Celery ТОЛЬКО если статус ИЗМЕНИЛСЯ на 'scheduled'.
        """
        # Проверяем, изменился ли статус на 'scheduled'
        should_trigger_celery = False
        
        if change:  # Это редактирование существующего объекта
            try:
                old_obj = MailingCampaign.objects.get(pk=obj.pk)
                # Триггерим Celery только если статус ИЗМЕНИЛСЯ с чего-то на 'scheduled'
                if old_obj.status != 'scheduled' and obj.status == 'scheduled':
                    should_trigger_celery = True
            except MailingCampaign.DoesNotExist:
                pass
        else:  # Новый объект
            if obj.status == 'scheduled':
                should_trigger_celery = True
        
        # Сохраняем изменения в БД
        super().save_model(request, obj, form, change)

        # Запускаем Celery только если нужно
        if should_trigger_celery:
            eta = obj.scheduled_at
            process_mass_campaign.apply_async(
                args=[obj.id, connection.schema_name],
                eta=eta
            )
            self.message_user(request, f"Кампания '{obj.title}' поставлена в очередь (Celery).")

class MessageLogAdmin(admin.ModelAdmin):
    list_display = ('client', 'status', 'sent_at', 'campaign', 'is_read')
    list_filter = ('status', 'campaign')
    # Добавляем select_related, чтобы при отображении client не было лишних запросов
    list_select_related = ('client', 'campaign')
    readonly_fields = ('client', 'status', 'error_message', 'campaign')


class MessageTemplateAdmin(admin.ModelAdmin):
    """Админка для управления шаблонами автоматических рассылок"""
    list_display = ('template_type', 'is_active', 'text_preview', 'updated_at')
    list_filter = ('is_active', 'template_type')
    list_editable = ('is_active',)
    search_fields = ('text',)
    
    fieldsets = (
        (None, {
            'fields': ('template_type', 'is_active')
        }),
        ('Содержимое', {
            'fields': ('text',),
        }),
    )
    
    def text_preview(self, obj):
        return obj.text[:80] + '...' if len(obj.text) > 80 else obj.text
    text_preview.short_description = 'Превью текста'


tenant_admin.register(VKConnection, VKConnectionAdmin)
tenant_admin.register(MailingCampaign, MailingCampaignAdmin)
tenant_admin.register(MessageLog, MessageLogAdmin)

# Import MessageTemplate at the top if not already imported
from apps.tenant.senler.models import MessageTemplate
tenant_admin.register(MessageTemplate, MessageTemplateAdmin)