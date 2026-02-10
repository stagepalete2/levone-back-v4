from django.contrib import admin
from django.shortcuts import render, redirect
from django.contrib import messages
from django import forms
from apps.shared.config.sites import tenant_admin
from apps.tenant.branch.models import Branch, BranchConfig, TelegramBot, BotAdmin, ClientBranch, CoinTransaction, StoryImage, BranchTestimonials, Promotions
from apps.tenant.senler.services import VKService

class ClientBranchAdmin(admin.ModelAdmin):
    list_display = ['client', 'branch', 'birth_date', ]
    readonly_fields = ['coins_balance']

class ReplyForm(forms.Form):
    text = forms.CharField(widget=forms.Textarea, label="Текст ответа")

class BranchTestimonialsAdmin(admin.ModelAdmin):
    list_display = ['source', 'short_review', 'rating', 'sentiment', 'is_replied', 'created_at']
    list_filter = ['source', 'sentiment', 'rating', 'is_replied']
    readonly_fields = ['ai_comment', 'vk_sender_id']
    actions = ['reply_to_review_action']

    def short_review(self, obj):
        return obj.review[:50] + "..." if obj.review else "-"
    short_review.short_description = "Отзыв"

    def reply_to_review_action(self, request, queryset):
        # 1. Filter out already replied
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
                    except Exception as e:
                         error_count += 1
                
                if success_count > 0:
                    self.message_user(request, f"Ответ успешно отправлен на {success_count} отзывов.")
                
                if error_count > 0:
                    self.message_user(request, f"Не удалось отправить ответ на {error_count} отзывов (нет профиля или ошибка ВК).", level=messages.ERROR)
                
                # Возвращаемся в список
                return redirect(request.get_full_path())
        else:
            form = ReplyForm()

        return render(request, 'admin/reply_form.html', {
            'items': queryset,
            'form': form,
            'title': f'Ответ на {actual_count} отзыв(ов)'
        })

    reply_to_review_action.short_description = "Ответить на отзыв (VK)"



tenant_admin.register(Branch)
tenant_admin.register(BranchConfig)
tenant_admin.register(TelegramBot)
tenant_admin.register(BotAdmin)
tenant_admin.register(ClientBranch, ClientBranchAdmin)
tenant_admin.register(CoinTransaction)
tenant_admin.register(StoryImage)
tenant_admin.register(BranchTestimonials, BranchTestimonialsAdmin)
tenant_admin.register(Promotions)