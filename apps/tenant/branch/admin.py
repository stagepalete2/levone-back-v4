from django.contrib import admin
from django.shortcuts import render, redirect
from django.contrib import messages
from django import forms
from django.utils.html import format_html
from django.conf import settings

from apps.shared.config.sites import tenant_admin
from apps.shared.config.mixins import BranchRestrictedAdminMixin
from apps.tenant.branch.models import (
    Branch, BranchConfig, TelegramBot, BotAdmin,
    ClientBranch, CoinTransaction, StoryImage,
    BranchTestimonials, Promotions, ClientBranchVisit
)
from apps.tenant.senler.services import VKService


# ─── Branch ────────────────────────────────────────────────────
class BranchConfigInline(admin.StackedInline):
    model = BranchConfig
    can_delete = False
    verbose_name = 'Настройки'
    verbose_name_plural = 'Настройки'


VK_MINI_APP_ID = getattr(settings, 'VK_MINI_APP_ID', '0')


class BranchAdmin(BranchRestrictedAdminMixin, admin.ModelAdmin):
    company_field_name = 'company'
    branch_field_name = None

    list_display = ('name', 'id', 'company', 'iiko_organization_id', 'get_vk_app_link', 'get_qr_code_btn', 'created_at')

    list_filter = ('company',)
    search_fields = ('name',)
    inlines = [BranchConfigInline]
    readonly_fields = ('get_vk_app_link_detail', 'get_qr_code_btn_detail')

    def _get_vk_url(self, obj):
        from django.db import connection
        company_slug = getattr(connection, 'schema_name', 'company')
        table = obj.vk_mini_app_table or 1
        return 'https://vk.com/app{}#company={}&branch={}&table={}'.format(
            VK_MINI_APP_ID, company_slug, obj.id, table
        )

    def get_vk_app_link(self, obj):
        url = self._get_vk_url(obj)
        return format_html('<a href="{}" target="_blank" style="font-size:11px;color:#4a76a8;">VK Ссылка</a>', url)
    get_vk_app_link.short_description = 'VK Мини-Апп'

    def get_qr_code_btn(self, obj):
        url = self._get_vk_url(obj)
        return format_html(
            '<button type="button" data-url="{}" data-name="{}"'
            ' onclick="levQR(this)"'
            ' style="background:#28a745;color:#fff;border:none;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:11px;">'
            '📱 QR-код</button>', url, obj.name
        )
    get_qr_code_btn.short_description = 'QR-код'

    def get_vk_app_link_detail(self, obj):
        if not obj.pk:
            return 'Сохраните объект для генерации ссылки'
        url = self._get_vk_url(obj)
        return format_html(
            '<code style="display:block;padding:10px;background:#f8f9fa;border-radius:8px;font-size:12px;word-break:break-all;">{}</code>'
            '<a href="{}" target="_blank" class="button" style="margin-top:8px;display:inline-block;">Открыть ссылку</a>',
            url, url
        )
    get_vk_app_link_detail.short_description = 'Ссылка на VK Мини-Апп'

    def get_qr_code_btn_detail(self, obj):
        if not obj.pk:
            return 'Сохраните объект для генерации QR-кода'
        url = self._get_vk_url(obj)
        return format_html(
            '<button type="button" data-url="{}" data-name="{}"'
            ' onclick="levQR(this)"'
            ' class="button" style="background:#28a745;color:#fff;padding:8px 16px;cursor:pointer;">'
            '📱 Скачать QR-код (PNG)</button>', url, obj.name
        )
    get_qr_code_btn_detail.short_description = 'QR-код VK Мини-Апп'

    def get_fieldsets(self, request, obj=None):
        base = [
            (None, {'fields': ('name', 'description', 'iiko_organization_id', 'dooglys_branch_id', 'dooglas_sale_point_id', 'vk_mini_app_table')}),
            ('VK Мини-Апп', {'fields': ('get_vk_app_link_detail', 'get_qr_code_btn_detail'), 'description': 'Ссылка и QR-код с параметрами company, branch, table'}),
        ]
        return base

    class Media:
        js = ('https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js',)

    def get_queryset(self, request):
        # Вызываем миксин (который теперь фильтрует по company),
        # а потом дополнительно фильтруем по branch pk если нужно
        qs = super().get_queryset(request)
        user = request.user
        if user.is_superuser:
            return qs
        if hasattr(user, 'tenant_profile'):
            user_branches = user.tenant_profile.branches.all()
            if user_branches.exists():
                return qs.filter(pk__in=user_branches)
        return qs

# ─── BranchConfig ──────────────────────────────────────────────
class BranchConfigAdmin(BranchRestrictedAdminMixin, admin.ModelAdmin):
    list_display = ('branch', 'yandex_map', 'gis_map', 'updated_at')
    search_fields = ('branch__name',)


# ─── TelegramBot ──────────────────────────────────────────────
class TelegramBotAdmin(BranchRestrictedAdminMixin, admin.ModelAdmin):
    list_display = ('name', 'bot_username', 'branch', 'created_at')
    list_filter = ('branch',)
    search_fields = ('name', 'bot_username')


# ─── BotAdmin ─────────────────────────────────────────────────
class BotAdminAdmin(BranchRestrictedAdminMixin, admin.ModelAdmin):
    branch_field_name = 'bot__branch'
    list_display = ('name', 'bot', 'is_active', 'chat_id', 'get_connect_link_display')
    list_filter = ('is_active', 'bot__branch')
    search_fields = ('name',)

    def get_connect_link_display(self, obj):
        link = obj.get_connect_link()
        return format_html('<a href="{}" target="_blank">Подключить</a>', link)
    get_connect_link_display.short_description = 'Ссылка подключения'

    def get_queryset(self, request):
        qs = super(admin.ModelAdmin, self).get_queryset(request)
        user = request.user
        if user.is_superuser:
            return qs
        if hasattr(user, 'tenant_profile'):
            user_branches = user.tenant_profile.branches.all()
            if user_branches.exists():
                return qs.filter(bot__branch__in=user_branches)
        return qs


# ─── ClientBranch ─────────────────────────────────────────────
class ClientBranchAdmin(BranchRestrictedAdminMixin, admin.ModelAdmin):
    list_display = (
        'client', 'branch', 'birth_date', 'coins_balance',
        'is_story_uploaded', 'is_joined_community',
        'is_allowed_message', 'is_employee', 'created_at'
    )
    list_filter = ('branch', 'is_employee', 'is_story_uploaded', 'is_joined_community')
    search_fields = ('client__name', 'client__lastname', 'client__vk_user_id')
    readonly_fields = ('coins_balance',)


# ─── CoinTransaction ─────────────────────────────────────────
class CoinTransactionAdmin(BranchRestrictedAdminMixin, admin.ModelAdmin):
    client_branch_field_name = 'client'
    branch_field_name = None

    list_display = ('client', 'type', 'source', 'amount', 'description', 'created_at')
    list_filter = ('type', 'source', 'client__branch')
    search_fields = ('client__client__name', 'client__client__lastname', 'description')
    readonly_fields = ('client', 'type', 'source', 'amount', 'description', 'created_at')

    def get_queryset(self, request):
        qs = super(admin.ModelAdmin, self).get_queryset(request)
        user = request.user
        if user.is_superuser:
            return qs
        if hasattr(user, 'tenant_profile'):
            user_branches = user.tenant_profile.branches.all()
            if user_branches.exists():
                return qs.filter(client__branch__in=user_branches)
        return qs


# ─── StoryImage ───────────────────────────────────────────────
class StoryImageAdmin(BranchRestrictedAdminMixin, admin.ModelAdmin):
    list_display = ('image', 'branch', 'created_at')
    list_filter = ('branch',)


# ─── BranchTestimonials ──────────────────────────────────────
class ReplyForm(forms.Form):
    text = forms.CharField(widget=forms.Textarea, label="Текст ответа")


class BranchTestimonialsAdmin(BranchRestrictedAdminMixin, admin.ModelAdmin):
    client_branch_field_name = 'client'
    branch_field_name = None

    list_display = (
        'source', 'short_review', 'rating', 'sentiment',
        'is_replied', 'phone', 'table', 'created_at'
    )
    list_filter = ('source', 'sentiment', 'rating', 'is_replied', 'client__branch')
    readonly_fields = ('ai_comment', 'vk_sender_id', 'vk_message_id')
    search_fields = ('review', 'phone')
    actions = ['reply_to_review_action']

    def short_review(self, obj):
        return (obj.review[:60] + "...") if obj.review and len(obj.review) > 60 else (obj.review or "-")
    short_review.short_description = "Отзыв"

    def get_queryset(self, request):
        qs = super(admin.ModelAdmin, self).get_queryset(request)
        user = request.user
        if user.is_superuser:
            return qs
        if hasattr(user, 'tenant_profile'):
            user_branches = user.tenant_profile.branches.all()
            if user_branches.exists():
                return qs.filter(client__branch__in=user_branches)
        return qs

    def reply_to_review_action(self, request, queryset):
        initial_count = queryset.count()
        queryset = queryset.filter(is_replied=False)
        actual_count = queryset.count()

        if actual_count == 0:
            if initial_count > 0:
                self.message_user(request, "На выбранные отзывы уже был дан ответ.", level=messages.WARNING)
            else:
                self.message_user(request, "Нет отзывов для ответа.", level=messages.WARNING)
            return

        if 'apply' in request.POST:
            form = ReplyForm(request.POST)
            if form.is_valid():
                text = form.cleaned_data['text']
                success_count = 0
                error_count = 0
                service = VKService()

                for review in queryset:
                    try:
                        if review.client:
                            service.send_message(review.client, text)
                            review.is_replied = True
                            review.save(update_fields=['is_replied'])
                            success_count += 1
                        else:
                            error_count += 1
                    except Exception:
                        error_count += 1

                if success_count > 0:
                    self.message_user(request, f"Ответ отправлен на {success_count} отзывов.")
                if error_count > 0:
                    self.message_user(
                        request,
                        f"Не удалось отправить на {error_count} отзывов.",
                        level=messages.ERROR
                    )
                return redirect(request.get_full_path())
        else:
            form = ReplyForm()

        return render(request, 'admin/reply_form.html', {
            'items': queryset,
            'form': form,
            'title': f'Ответ на {actual_count} отзыв(ов)'
        })

    reply_to_review_action.short_description = "Ответить на отзыв (VK)"


# ─── ClientBranchVisit ────────────────────────────────────────
class ClientBranchVisitAdmin(BranchRestrictedAdminMixin, admin.ModelAdmin):
    client_branch_field_name = 'client'
    branch_field_name = None

    list_display = ('client', 'visited_at')
    list_filter = ('client__branch',)
    search_fields = ('client__client__name', 'client__client__lastname')
    readonly_fields = ('client', 'visited_at')

    def get_queryset(self, request):
        qs = super(admin.ModelAdmin, self).get_queryset(request)
        user = request.user
        if user.is_superuser:
            return qs
        if hasattr(user, 'tenant_profile'):
            user_branches = user.tenant_profile.branches.all()
            if user_branches.exists():
                return qs.filter(client__branch__in=user_branches)
        return qs


# ─── Promotions ───────────────────────────────────────────────
class PromotionsAdmin(BranchRestrictedAdminMixin, admin.ModelAdmin):
    list_display = ('title', 'branch', 'discount', 'dates', 'created_at')
    list_filter = ('branch',)
    search_fields = ('title',)


# ─── Register ─────────────────────────────────────────────────
tenant_admin.register(Branch, BranchAdmin)
tenant_admin.register(BranchConfig, BranchConfigAdmin)
tenant_admin.register(TelegramBot, TelegramBotAdmin)
tenant_admin.register(BotAdmin, BotAdminAdmin)
tenant_admin.register(ClientBranch, ClientBranchAdmin)
tenant_admin.register(CoinTransaction, CoinTransactionAdmin)
tenant_admin.register(StoryImage, StoryImageAdmin)
tenant_admin.register(BranchTestimonials, BranchTestimonialsAdmin)
tenant_admin.register(ClientBranchVisit, ClientBranchVisitAdmin)
tenant_admin.register(Promotions, PromotionsAdmin)
