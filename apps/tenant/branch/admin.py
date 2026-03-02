from django.contrib import admin
from django.shortcuts import render, redirect
from django.contrib import messages
from django import forms
from django.utils.html import format_html

from apps.shared.config.sites import tenant_admin
from apps.shared.config.mixins import BranchRestrictedAdminMixin
from apps.tenant.branch.models import (
    Branch, BranchConfig, TelegramBot, BotAdmin,
    ClientBranch, CoinTransaction, StoryImage,
    BranchTestimonials, Promotions, ClientBranchVisit, DailyCode,
    TestimonialReply
)

from apps.tenant.senler.services import VKService


# ─── Helpers ───────────────────────────────────────────────────

def _get_company_for_current_tenant():
    """
    Returns the Company object for the current tenant by looking up
    connection.schema_name → Domain → Company (shared models, public schema).
    Branch has no direct FK to Company, so this is the only way.
    """
    from django.db import connection
    from apps.shared.clients.models import Domain

    schema_name = connection.schema_name
    if not schema_name or schema_name == 'public':
        return None

    # Domain and Company are shared models → always accessible from any schema context
    domain = (
        Domain.objects
        .filter(tenant__schema_name=schema_name, is_primary=True)
        .select_related('tenant')
        .first()
    )
    if not domain:
        domain = (
            Domain.objects
            .filter(tenant__schema_name=schema_name)
            .select_related('tenant')
            .first()
        )
    return domain.tenant if domain else None


def _get_vk_mini_app_id(company):
    """
    Returns the vk_mini_app_id stored in CompanyConfig.
    Falls back to empty string if not configured.
    """
    if not company:
        return ''
    try:
        return company.config.vk_mini_app_id or '53418653'
    except Exception:
        return ''


# ─── Branch ────────────────────────────────────────────────────

class BirthdayDailyCodeAdmin(admin.ModelAdmin):
    list_display = ('code', 'date', 'branch', 'created_at')
    list_filter = ('branch', 'date')
    search_fields = ('code',)

class BranchConfigInline(admin.StackedInline):
    model = BranchConfig
    can_delete = False
    verbose_name = 'Настройки'
    verbose_name_plural = 'Настройки'


class BranchAdmin(BranchRestrictedAdminMixin, admin.ModelAdmin):
    branch_field_name = None

    list_display = ('name', 'id', 'iiko_organization_id', 'get_vk_link_btn', 'created_at')
    search_fields = ('name',)
    inlines = [BranchConfigInline]
    readonly_fields = ('vk_mini_app_widget',)

    # ── list column: shows a small "🔗 Ссылка" link that opens a modal ──
    def get_vk_link_btn(self, obj):
        if not obj.pk:
            return '—'
        company = _get_company_for_current_tenant()
        app_id = _get_vk_mini_app_id(company)
        company_id = company.id if company else ''
        if not app_id:
            return format_html(
                '<span style="color:#aaa;font-size:11px;">VK App ID не задан</span>'
            )
        # Render a small button; clicking opens the modal defined in the widget
        return format_html(
            '<button type="button" '
            '  onclick="levVkModal({branch_id}, {company_id}, \'{app_id}\', \'{branch_name}\')" '
            '  style="background:#4a76a8;color:#fff;border:none;padding:3px 10px;'
            '         border-radius:4px;cursor:pointer;font-size:11px;font-weight:600;">'
            '🔗 QR / Ссылка'
            '</button>',
            branch_id=obj.pk,
            company_id=company_id,
            app_id=app_id,
            branch_name=obj.name.replace("'", "\\'"),
        )
    get_vk_link_btn.short_description = 'VK Мини-Апп'

    # ── detail page: full interactive widget ──
    # ── detail page: full interactive widget ──
    def vk_mini_app_widget(self, obj):
        """
        Renders an interactive widget on the Branch change page.

        The widget lets the admin manually enter a table number, then:
          • copies the generated link to clipboard
          • generates and downloads a QR-code PNG (all client-side, no DB write)
        """
        if not obj.pk:
            return '💡 Сохраните торговую точку, чтобы увидеть виджет генерации ссылки и QR-кода.'

        company = _get_company_for_current_tenant()
        app_id = _get_vk_mini_app_id(company)
        company_id = company.id - 1 if company else None

        if not app_id:
            return format_html(
                '<div style="padding:14px;background:#fff8e1;border-left:4px solid #ffc107;'
                'border-radius:4px;font-size:13px;">'
                '⚠️ <strong>VK Mini-App ID не задан.</strong><br>'
                'Укажите его в <a href="/admin/company/companyconfig/">Настройках компании</a> '
                '→ поле <em>«ID VK Мини-Апп»</em>.'
                '</div>'
            )

        if not company_id:
            return format_html(
                '<div style="padding:14px;background:#fff3f3;border-left:4px solid #dc3545;'
                'border-radius:4px;font-size:13px;">'
                '⚠️ Не удалось определить компанию для текущего тенанта.'
                '</div>'
            )

        branch_id = obj.pk

        # УБРАНА ПЕРЕМЕННАЯ base_url отсюда, теперь URL формируется прямо в JS

        return format_html(
            '''
            <div id="vk-widget-{bid}" style="
                background:#f8f9fa;border:1px solid #e0e0e0;border-radius:12px;
                padding:20px 22px;max-width:560px;font-family:system-ui,sans-serif;">

              <div style="margin-bottom:14px;">
                <span style="font-size:13px;font-weight:700;color:#1B2838;">📱 VK Мини-Апп — генерация ссылки и QR-кода</span>
                <div style="font-size:11px;color:#888;margin-top:3px;">
                  Ссылка: <code>company={cid}&branch={bid}&table=<em>N</em></code>
                </div>
              </div>

              <div style="display:flex;align-items:center;gap:10px;margin-bottom:14px;">
                <label style="font-size:13px;font-weight:600;color:#444;white-space:nowrap;">
                  Номер стола:
                </label>
                <input
                  type="number"
                  id="vk-table-{bid}"
                  min="1"
                  placeholder="Введите номер стола"
                  oninput="levUpdateUrl({bid})"
                  style="border:1px solid #ccc;border-radius:6px;padding:7px 10px;
                         font-size:14px;font-weight:600;width:140px;
                         outline:none;transition:border-color .2s;"
                  onfocus="this.style.borderColor='#4a76a8'"
                  onblur="this.style.borderColor='#ccc'"
                />
              </div>

              <div style="margin-bottom:14px;">
                <code id="vk-url-{bid}" style="
                    display:block;word-break:break-all;font-size:11px;
                    background:#fff;border:1px solid #ddd;border-radius:6px;
                    padding:8px 10px;color:#555;min-height:34px;line-height:1.5;">
                  ← укажите номер стола выше
                </code>
              </div>

              <div style="display:flex;gap:8px;flex-wrap:wrap;">
                <button type="button" onclick="levCopyUrl({bid})"
                  id="vk-copy-btn-{bid}"
                  style="background:#4a76a8;color:#fff;border:none;border-radius:8px;
                         padding:9px 18px;font-size:13px;font-weight:700;cursor:pointer;
                         transition:background .15s;">
                  📋 Копировать ссылку
                </button>
                <button type="button" onclick="levDownloadQr({bid}, '{branch_name}')"
                  id="vk-qr-btn-{bid}"
                  style="background:#28a745;color:#fff;border:none;border-radius:8px;
                         padding:9px 18px;font-size:13px;font-weight:700;cursor:pointer;
                         transition:background .15s;">
                  📱 Скачать QR-код
                </button>
                <span id="vk-status-{bid}" style="font-size:12px;color:#28a745;
                      align-self:center;display:none;font-weight:600;"></span>
              </div>

              <div id="vk-qr-canvas-{bid}" style="display:none;"></div>
            </div>

            <script>
            /* ── VK Mini-App widget for branch {bid} ── */
            (function() {{
              // ✅ ИЗМЕНЕНИЕ: Формируем URL напрямую, чтобы избежать экранирования амперсандов
              var BASE_URL = 'https://vk.com/app{app_id}/#/?company={cid}&branch={bid}&table=';
              var BID      = '{bid}';

              window.levUpdateUrl = window.levUpdateUrl || function(bid) {{
                var table  = document.getElementById('vk-table-' + bid).value.trim();
                var urlEl  = document.getElementById('vk-url-' + bid);
                var cBtn   = document.getElementById('vk-copy-btn-' + bid);
                var qBtn   = document.getElementById('vk-qr-btn-' + bid);
                var status = document.getElementById('vk-status-' + bid);
                if (status) status.style.display = 'none';
                if (!table || parseInt(table) < 1) {{
                  urlEl.textContent = '← укажите номер стола выше';
                  urlEl.style.color = '#aaa';
                  return;
                }}
                urlEl.textContent = BASE_URL + table;
                urlEl.style.color = '#1B2838';
              }};

              function getUrl(bid) {{
                var table = document.getElementById('vk-table-' + bid).value.trim();
                if (!table || parseInt(table) < 1) return null;
                return BASE_URL + table;
              }}

              window.levCopyUrl = window.levCopyUrl || function(bid) {{
                var url    = getUrl(bid);
                var status = document.getElementById('vk-status-' + bid);
                if (!url) {{
                  alert('Сначала введите номер стола!');
                  document.getElementById('vk-table-' + bid).focus();
                  return;
                }}
                navigator.clipboard.writeText(url).then(function() {{
                  status.textContent = '✅ Скопировано!';
                  status.style.display = 'inline';
                  setTimeout(function() {{ status.style.display = 'none'; }}, 2500);
                }}).catch(function() {{
                  var ta = document.createElement('textarea');
                  ta.value = url;
                  ta.style.position = 'fixed';
                  ta.style.opacity  = '0';
                  document.body.appendChild(ta);
                  ta.select();
                  document.execCommand('copy');
                  document.body.removeChild(ta);
                  status.textContent = '✅ Скопировано!';
                  status.style.display = 'inline';
                  setTimeout(function() {{ status.style.display = 'none'; }}, 2500);
                }});
              }};

              window.levDownloadQr = window.levDownloadQr || function(bid, branchName) {{
                var url = getUrl(bid);
                if (!url) {{
                  alert('Сначала введите номер стола!');
                  document.getElementById('vk-table-' + bid).focus();
                  return;
                }}
                var table  = document.getElementById('vk-table-' + bid).value.trim();
                var status = document.getElementById('vk-status-' + bid);
                var canvasDiv = document.getElementById('vk-qr-canvas-' + bid);

                function doQr() {{
                  if (typeof QRCode === 'undefined') {{
                    setTimeout(doQr, 150);
                    return;
                  }}
                  canvasDiv.innerHTML = '';
                  canvasDiv.style.display = 'none';
                  new QRCode(canvasDiv, {{
                    text: url,
                    width: 512,
                    height: 512,
                    correctLevel: QRCode.CorrectLevel.H
                  }});
                  setTimeout(function() {{
                    var canvas = canvasDiv.querySelector('canvas');
                    if (!canvas) {{ alert('Ошибка генерации QR-кода'); return; }}
                    var link = document.createElement('a');
                    link.download = 'vk_qr_' + branchName.replace(/[^a-zA-Z0-9а-яёА-ЯЁ]/g, '_') + '_table' + table + '.png';
                    link.href = canvas.toDataURL('image/png');
                    link.click();
                    status.textContent = '✅ QR скачан!';
                    status.style.display = 'inline';
                    setTimeout(function() {{ status.style.display = 'none'; }}, 3000);
                  }}, 300);
                }}
                doQr();
              }};
            }})();
            </script>
            ''',
            bid=branch_id,
            cid=company_id,
            app_id=app_id,  # ✅ Добавлен app_id в аргументы
            branch_name=obj.name.replace("'", "\\'"),
        )
    vk_mini_app_widget.short_description = 'VK Мини-Апп (ссылка и QR-код)'

    def get_fieldsets(self, request, obj=None):
        return [
            (None, {
                'fields': (
                    'name', 'description',
                    'iiko_organization_id',
                    'dooglys_branch_id',
                    'dooglas_sale_point_id',
                )
            }),
            ('📱 VK Мини-Апп', {
                'fields': ('vk_mini_app_widget',),
                'description': (
                    'Генерация глубоких ссылок и QR-кодов для VK Мини-Апп. '
                    'Данные не сохраняются — номер стола вводится вручную при каждой генерации. '
                    'ID приложения настраивается в Настройках компании.'
                ),
            }),
        ]

    class Media:
        js = (
            # QRCode.js loaded from CDN; fallback handled inside widget JS
            'https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js',
        )

    def get_queryset(self, request):
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
        'is_allowed_message', 'joined_community_via_app',
        'allowed_message_via_app', 'is_employee', 'created_at'
    )
    list_filter = ('branch', 'is_employee', 'is_story_uploaded', 'is_joined_community',
                   'joined_community_via_app', 'allowed_message_via_app')
    search_fields = ('client__name', 'client__lastname', 'client__vk_user_id')
    readonly_fields = ('coins_balance', 'joined_community_via_app', 'allowed_message_via_app')


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


class TestimonialReplyInline(admin.TabularInline):
    """Inline для показа истории ответов как диалог"""
    model = TestimonialReply
    extra = 0
    readonly_fields = ('text', 'sent_at', 'sent_by', 'is_sent_successfully', 'error_message')
    can_delete = False
    verbose_name = 'Ответ'
    verbose_name_plural = '💬 История ответов (диалог)'

    def has_add_permission(self, request, obj=None):
        return False


class BranchTestimonialsAdmin(BranchRestrictedAdminMixin, admin.ModelAdmin):
    client_branch_field_name = 'client'
    branch_field_name = None

    list_display = (
        'source', 'short_review', 'display_rating', 'sentiment',
        'replies_count', 'is_replied', 'phone', 'table', 'created_at'
    )
    list_filter = ('source', 'sentiment', 'rating', 'is_replied', 'client__branch')
    readonly_fields = ('ai_comment', 'vk_sender_id', 'vk_message_id', 'source', 'display_dialog')
    search_fields = ('review', 'phone')
    actions = ['reply_to_review_action']
    inlines = [TestimonialReplyInline]

    def short_review(self, obj):
        return (obj.review[:60] + "...") if obj.review and len(obj.review) > 60 else (obj.review or "-")
    short_review.short_description = "Отзыв"

    def display_rating(self, obj):
        """Показывает оценку только для отзывов из приложения"""
        if obj.rating is None:
            return "—"
        return f"{'⭐️' * obj.rating} ({obj.rating}/5)"
    display_rating.short_description = "Оценка"

    def replies_count(self, obj):
        """Показывает количество ответов"""
        count = obj.replies.count()
        if count == 0:
            return "—"
        return f"💬 {count}"
    replies_count.short_description = "Ответы"

    def display_dialog(self, obj):
        """Показывает историю диалога прямо на странице отзыва"""
        replies = obj.replies.all().order_by('sent_at')
        if not replies:
            return format_html('<span style="color:#999;">Ответов пока нет</span>')
        
        html_parts = []
        
        # Сам отзыв
        client_name = str(obj.client) if obj.client else (obj.vk_sender_id or "Гость")
        source_label = "из приложения" if obj.source == 'APP' else "из ВК"
        html_parts.append(
            f'<div style="background:#e3f2fd;border-radius:8px;padding:10px 14px;margin-bottom:8px;max-width:80%;">'
            f'<div style="font-size:11px;color:#666;margin-bottom:4px;">👤 {client_name} ({source_label}) — {obj.created_at:%d.%m.%Y %H:%M}</div>'
            f'<div>{obj.review}</div>'
            f'</div>'
        )
        
        # Ответы
        for reply in replies:
            sent_by = reply.sent_by.get_full_name() if reply.sent_by else "Администратор"
            status_icon = "✅" if reply.is_sent_successfully else "❌"
            html_parts.append(
                f'<div style="background:#e8f5e9;border-radius:8px;padding:10px 14px;margin-bottom:8px;margin-left:auto;max-width:80%;text-align:right;">'
                f'<div style="font-size:11px;color:#666;margin-bottom:4px;">{status_icon} {sent_by} — {reply.sent_at:%d.%m.%Y %H:%M}</div>'
                f'<div style="text-align:left;">{reply.text}</div>'
                f'{"<div style=font-size:11px;color:red;>Ошибка: " + reply.error_message + "</div>" if reply.error_message else ""}'
                f'</div>'
            )
        
        return format_html('<div style="max-width:600px;">{}</div>', format_html(''.join(html_parts)))
    display_dialog.short_description = "💬 Диалог"

    def get_fieldsets(self, request, obj=None):
        fieldsets = [
            ('Отзыв', {
                'fields': ('source', 'client', 'review', 'rating', 'phone', 'table', 'vk_sender_id', 'vk_message_id')
            }),
            ('AI Анализ', {
                'fields': ('sentiment', 'ai_comment'),
                'classes': ('collapse',),
            }),
        ]
        # Показываем диалог только для существующих отзывов с ответами
        if obj and obj.pk and obj.replies.exists():
            fieldsets.insert(1, ('💬 Диалог', {
                'fields': ('display_dialog',),
            }))
        return fieldsets

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
        """Ответить на отзывы — отправляет ВК сообщение И СОХРАНЯЕТ текст ответа в историю"""
        if 'apply' in request.POST:
            form = ReplyForm(request.POST)
            if form.is_valid():
                text = form.cleaned_data['text']
                success_count = 0
                error_count = 0
                service = VKService()

                for review in queryset:
                    try:
                        error_msg = None
                        sent_ok = False
                        
                        if review.client:
                            try:
                                service.send_message(review.client, text, template_type='review_reply')
                                sent_ok = True
                            except Exception as e:
                                error_msg = str(e)
                        else:
                            error_msg = "Клиент не привязан к отзыву"
                        
                        # Сохраняем ответ в историю ВСЕГДА
                        TestimonialReply.objects.create(
                            testimonial=review,
                            text=text,
                            sent_by=request.user,
                            is_sent_successfully=sent_ok,
                            error_message=error_msg
                        )
                        
                        # Обновляем флаг
                        review.is_replied = True
                        review.save(update_fields=['is_replied'])
                        
                        if sent_ok:
                            success_count += 1
                        else:
                            error_count += 1
                    except Exception as e:
                        error_count += 1
                        # Даже при ошибке пишем в историю
                        try:
                            TestimonialReply.objects.create(
                                testimonial=review,
                                text=text,
                                sent_by=request.user,
                                is_sent_successfully=False,
                                error_message=str(e)
                            )
                        except Exception:
                            pass

                if success_count > 0:
                    self.message_user(request, f"✅ Ответ отправлен на {success_count} отзывов.")
                if error_count > 0:
                    self.message_user(
                        request,
                        f"❌ Не удалось отправить на {error_count} отзывов (ответы сохранены в историю).",
                        level=messages.WARNING
                    )
                return redirect(request.get_full_path())
        else:
            form = ReplyForm()

        return render(request, 'admin/reply_form.html', {
            'items': queryset,
            'form': form,
            'title': f'Ответ на {queryset.count()} отзыв(ов)'
        })

    reply_to_review_action.short_description = "💬 Ответить на отзыв (VK)"


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
tenant_admin.register(DailyCode, BirthdayDailyCodeAdmin)
# TestimonialReply управляется через inline в BranchTestimonialsAdmin — отдельная регистрация не нужна