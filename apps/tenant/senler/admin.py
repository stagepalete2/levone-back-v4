from apps.shared.config.sites import tenant_admin
from apps.shared.config.mixins import BranchRestrictedAdminMixin
from django.contrib import admin
from django.utils.timezone import now
from django.db import connection
from django.db.models import Count, Q
from apps.tenant.senler.models import MailingCampaign, VKConnection, MessageLog, MessageTemplate
from apps.tenant.senler.tasks import process_mass_campaign
from django import forms

class VKConnectionForm(forms.ModelForm):
    class Meta:
        model = VKConnection
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Если объект уже существует и токен есть, 
        # подменяем в форме зашифрованную строку на расшифрованную
        if self.instance and self.instance.pk and self.instance.access_token:
            self.initial['access_token'] = self.instance.raw_token

class VKConnectionAdmin(admin.ModelAdmin):
    form = VKConnectionForm
    list_display = ('group_id', 'updated_at')


class MailingCampaignAdmin(admin.ModelAdmin):
    list_display = ('title', 'status', 'segment', 'send_to_all', 'scheduled_at', 'get_stats', 'created_at')
    list_filter = ('status', 'segment', 'send_to_all')
    filter_horizontal = ('specific_clients',)
    search_fields = ('title', 'text')
    actions = ['send_campaign']

    class Media:
        js = (
            'https://code.jquery.com/jquery-3.6.0.min.js',
            'senler/js/mailing_ai.js',
        )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(
            total_logs=Count('logs'),
            sent_logs=Count('logs', filter=Q(logs__status='sent')),
            blocked_logs=Count('logs', filter=Q(logs__status='blocked'))
        )

    def send_campaign(self, request, queryset):
        drafts = queryset.filter(status='draft')
        count = 0
        for campaign in drafts:
            campaign.status = 'scheduled'
            campaign.scheduled_at = now()
            campaign.save(update_fields=['status', 'scheduled_at'])
            process_mass_campaign.apply_async(
                args=[campaign.id, connection.schema_name],
                eta=campaign.scheduled_at
            )
            count += 1
        self.message_user(request, f"Запланировано рассылок: {count}")
    send_campaign.short_description = "Запустить выбранные рассылки"

    def get_stats(self, obj):
        total = getattr(obj, 'total_logs', 0)
        sent = getattr(obj, 'sent_logs', 0)
        blocked = getattr(obj, 'blocked_logs', 0)
        return f"Всего: {total} | OK: {sent} | Блок: {blocked}"
    get_stats.short_description = "Статистика"

    def save_model(self, request, obj, form, change):
        should_trigger_celery = False
        if change:
            try:
                old_obj = MailingCampaign.objects.get(pk=obj.pk)
                if old_obj.status != 'scheduled' and obj.status == 'scheduled':
                    should_trigger_celery = True
            except MailingCampaign.DoesNotExist:
                pass
        else:
            if obj.status == 'scheduled':
                should_trigger_celery = True

        super().save_model(request, obj, form, change)

        if should_trigger_celery:
            eta = obj.scheduled_at
            process_mass_campaign.apply_async(
                args=[obj.id, connection.schema_name],
                eta=eta
            )
            self.message_user(request, f"Кампания '{obj.title}' поставлена в очередь.")


class MessageLogAdmin(admin.ModelAdmin):
    list_display = ('client', 'campaign', 'status', 'is_read', 'sent_at')
    list_filter = ('status', 'is_read', 'campaign')
    list_select_related = ('client', 'campaign')
    search_fields = ('client__client__name', 'client__client__lastname')
    readonly_fields = ('client', 'status', 'error_message', 'campaign', 'vk_message_id', 'is_read', 'read_at')


class MessageTemplateAdmin(admin.ModelAdmin):
    list_display = ('template_type', 'is_active', 'text_preview', 'updated_at')
    list_filter = ('is_active', 'template_type')
    list_editable = ('is_active',)
    search_fields = ('text',)

    fieldsets = (
        (None, {'fields': ('template_type', 'is_active')}),
        ('Содержимое', {'fields': ('text',)}),
    )

    def text_preview(self, obj):
        return (obj.text[:80] + '...') if len(obj.text) > 80 else obj.text
    text_preview.short_description = 'Превью текста'


tenant_admin.register(VKConnection, VKConnectionAdmin)
tenant_admin.register(MailingCampaign, MailingCampaignAdmin)
tenant_admin.register(MessageLog, MessageLogAdmin)
tenant_admin.register(MessageTemplate, MessageTemplateAdmin)
