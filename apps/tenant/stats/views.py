from django.shortcuts import redirect
from django.views.generic import TemplateView, DetailView, View
from django.http import Http404, JsonResponse
from django.core.exceptions import PermissionDenied
from django.urls import reverse
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Count, F, Q
from datetime import timedelta
import json

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone

from apps.shared.config.sites import tenant_admin

from apps.tenant.branch.models import Branch, ClientBranch, CoinTransaction, BranchTestimonials


from apps.tenant.game.models import ClientAttempt
from apps.tenant.stats.core import GeneralStatsService, RFAnalyticsService, RFMigrationService, VKIntegrationService, RFManagementService, RFGuestService
from apps.tenant.stats.serializers import MigrationFilterSerializer, RFRecalculateSerializer, RFSettingsUpdateSerializer, RFGuestListSerializer
from apps.tenant.stats.models import RFSegment, RFSettings, GuestRFScore

class BaseAdminStatsView(LoginRequiredMixin, UserPassesTestMixin):
    """Базовый класс для проверки прав доступа"""
    login_url = '/admin/login/'
    redirect_field_name = 'next'

    def test_func(self):
        return self.request.user.is_superuser or self.request.user.is_staff

    def handle_no_permission(self):
        raise PermissionDenied("Доступ к статистике запрещен")
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Добавляем контекст админки (меню, хедеры)
        context.update(tenant_admin.each_context(self.request))
        return context


class PeriodMixin:
    """
    Миксин, читающий GET-параметр ?period= или custom_date_from/custom_date_to
    и добавляющий в контекст resolved-диапазон + список вариантов для UI.
    """

    def get_period_context(self):
        # Проверяем, есть ли пользовательские даты
        custom_date_from = self.request.GET.get('custom_date_from')
        custom_date_to = self.request.GET.get('custom_date_to')
        
        if custom_date_from and custom_date_to:
            # Используем пользовательские даты
            date_from, date_to, period_code = GeneralStatsService.resolve_custom_period(
                custom_date_from, custom_date_to
            )
        else:
            # Используем предустановленный период
            period_code = self.request.GET.get('period', GeneralStatsService.DEFAULT_PERIOD)
            date_from, date_to, period_code = GeneralStatsService.resolve_period(period_code)
        
        return {
            'period_code': period_code,
            'date_from': date_from,
            'date_to': date_to,
            'period_choices': GeneralStatsService.PERIOD_CHOICES,
            'custom_date_from': custom_date_from,
            'custom_date_to': custom_date_to,
        }


class BranchMixin:
    """
    Миксин, читающий GET-параметр ?branch= и добавляющий
    в контекст информацию о выбранном филиале.
    """

    def get_branch_context(self):
        branch_id = self.request.GET.get('branch')
        selected_branch = None
        
        if branch_id:
            try:
                selected_branch = Branch.objects.get(id=int(branch_id))
            except (Branch.DoesNotExist, ValueError):
                pass
        
        return {
            'all_branches': Branch.objects.all().order_by('name'),
            'selected_branch': selected_branch,
            'selected_branch_id': selected_branch.id if selected_branch else None,
        }


class StatisticsView(PeriodMixin, BranchMixin, BaseAdminStatsView, TemplateView):
    template_name = "general/statistics.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        period_ctx = self.get_period_context()
        branch_ctx = self.get_branch_context()
        
        context.update(period_ctx)
        context.update(branch_ctx)

        context["stats"] = GeneralStatsService.get_dashboard_stats(
            period_code=period_ctx['period_code'],
            branch_id=branch_ctx.get('selected_branch_id'),
            date_from=period_ctx.get('date_from'),
            date_to=period_ctx.get('date_to'),
        )

        # Build period_params string for template links
        branch_id = branch_ctx.get('selected_branch_id')
        custom_from = period_ctx.get('custom_date_from')
        custom_to = period_ctx.get('custom_date_to')
        period_code = period_ctx.get('period_code', '30d')
        parts = []
        if branch_id:
            parts.append(f'branch={branch_id}')
        if custom_from and custom_to:
            parts.append(f'custom_date_from={custom_from}')
            parts.append(f'custom_date_to={custom_to}')
        elif period_code and period_code != 'custom':
            parts.append(f'period={period_code}')
        context['period_params'] = '&'.join(parts)
        
        return context


class StatisticsDetailView(PeriodMixin, BranchMixin, BaseAdminStatsView, TemplateView):
    template_name = 'general/statistics_detail.html'

    def get_context_data(self, stat_name, **kwargs):
        context = super().get_context_data(**kwargs)

        period_ctx = self.get_period_context()
        branch_ctx = self.get_branch_context()
        
        context.update(period_ctx)
        context.update(branch_ctx)

        date_from = period_ctx['date_from']
        date_to = period_ctx['date_to']

        # Базовый QuerySet
        qs = ClientBranch.objects.all()
        
        # Фильтр по филиалу если выбран
        if branch_ctx.get('selected_branch_id'):
            qs = qs.filter(branch_id=branch_ctx['selected_branch_id'])

        # period_qs с фильтрацией по обеим датам
        if date_from and date_to:
            period_qs = qs.filter(created_at__gte=date_from, created_at__lte=date_to)
        elif date_from:
            period_qs = qs.filter(created_at__gte=date_from)
        else:
            period_qs = qs

        branch_id = branch_ctx.get('selected_branch_id')

        # --- КАРТА СТАТИСТИКИ ---
        title_map = {
            # 1. QR-сканирований за период
            "qr_scans": lambda: self._get_qr_scan_clients(qs, date_from, date_to, branch_id),

            # 2. Общее количество гостей в рассылке
            "mailing_subscribers": (
                'Общее количество гостей в рассылке',
                qs.filter(is_joined_community=True)
            ),

            # 3. Новые в группе и рассылке, получившие первый подарок
            "new_clients_received_super_prize": lambda: self._get_new_prize_clients(qs, date_from, date_to, branch_id),

            # 4. Вернулись и сыграли в игру повторно
            "clients_returned_second_time": lambda: self._get_returned_clients(qs, date_from, date_to, branch_id),

            # 5. Купили подарки за баллы
            "clients_bought_prizes": lambda: self._get_bought_prizes_clients(qs, date_from, date_to, branch_id),

            # 6. Подписались в сообщество ВК
            "group_subscribers": (
                'Подписались в сообщество ВК',
                qs.filter(is_joined_community=True)
            ),

            # 7. Подписались на рассылку ВК
            "mailing_period": (
                'Подписались на рассылку ВК',
                period_qs.filter(is_joined_community=True)
            ),

            # 8. Отправлено поздравлений с ДР
            "sent_greetings": lambda: self._get_birthday_greeting_clients(qs, date_from, date_to, branch_id),

            # 9. Пришли отметить день рождения
            "clients_birthday_qr": lambda: self._get_birthday_clients(qs, date_from, date_to, branch_id),

            # 10. % открываемости — клиенты прочитавшие сообщение
            "open_rate": lambda: self._get_read_message_clients(qs, date_from, date_to, branch_id),

            # 11. Опубликовали историй в ВК
            "clients_posted_story": (
                'Опубликовали историй в ВК',
                period_qs.filter(is_story_uploaded=True)
            ),

            # 12. Перешли из историй ВК
            "clients_from_referral": (
                'Перешли из историй ВК',
                period_qs.filter(invited_by__isnull=False)
            ),
        }

        # Статистика из внешних POS-систем — список гостей недоступен
        external_stats = {
            "pos_guests":   'Гостей по POS-системе',
            "scan_index":   'Индекс сканирования',
        }

        entry = title_map.get(stat_name)

        if entry is not None:
            if callable(entry):
                title, filtered_qs = entry()
            else:
                title, filtered_qs = entry
            context['stat'] = title
            context["clients"] = filtered_qs.distinct()
        elif stat_name in external_stats:
            context['stat'] = external_stats[stat_name]
            context['clients'] = ClientBranch.objects.none()
            context['external_stat'] = True

        context["stat_name"] = stat_name
        context["breadcrumbs"] = [
            {"title": "Домой", "url": reverse("admin:index")},
            {"title": "Общая статистика", "url": reverse("admin-statistics")},
            {"title": context.get('stat', stat_name), "url": ""},
        ]
        return context

    # ── Вспомогательные методы ──

    @staticmethod
    def _get_returned_clients(qs, date_from, date_to=None, branch_id=None):
        attempt_filters = {}
        if date_from:
            attempt_filters['created_at__gte'] = date_from
        if date_to:
            attempt_filters['created_at__lte'] = date_to
        if branch_id:
            attempt_filters['client__branch_id'] = branch_id
        repeat_client_ids = ClientAttempt.objects.filter(
            **attempt_filters
        ).values('client').annotate(
            attempt_count=Count('id')
        ).filter(attempt_count__gte=2).values_list('client', flat=True)
        return ('Вернулись и сыграли в игру повторно', qs.filter(id__in=repeat_client_ids))

    @staticmethod
    def _get_birthday_clients(qs, date_from, date_to=None, branch_id=None):
        filters = Q(
            client__birth_date__isnull=False,
            created_at__day=F('client__birth_date__day'),
            created_at__month=F('client__birth_date__month'),
        )
        if date_from:
            filters &= Q(created_at__gte=date_from)
        if date_to:
            filters &= Q(created_at__lte=date_to)
        if branch_id:
            filters &= Q(branch_id=branch_id)
        birthday_attempt_ids = ClientAttempt.objects.filter(filters).values_list('client', flat=True)
        return ('Пришли отметить день рождения', qs.filter(id__in=birthday_attempt_ids))

    @staticmethod
    def _get_new_prize_clients(qs, date_from, date_to=None, branch_id=None):
        """Клиенты, вступившие в группу и получившие первый подарок за игру."""
        from apps.tenant.branch.models import ClientSuperPrize
        prize_filters = Q(acquired_from='GAME')
        if date_from:
            prize_filters &= Q(created_at__gte=date_from)
        if date_to:
            prize_filters &= Q(created_at__lte=date_to)
        if branch_id:
            prize_filters &= Q(client__branch_id=branch_id)
        client_ids = ClientSuperPrize.objects.filter(prize_filters).values_list('client_id', flat=True)
        return (
            'Новые в группе и рассылке, получившие первый подарок',
            qs.filter(id__in=client_ids, is_joined_community=True)
        )

    @staticmethod
    def _get_bought_prizes_clients(qs, date_from, date_to=None, branch_id=None):
        """Клиенты, купившие подарки за баллы (через CoinTransaction)."""
        tx_filters = Q(type='EXPENSE')
        if date_from:
            tx_filters &= Q(created_at__gte=date_from)
        if date_to:
            tx_filters &= Q(created_at__lte=date_to)
        if branch_id:
            tx_filters &= Q(client__branch_id=branch_id)
        client_ids = CoinTransaction.objects.filter(tx_filters).values_list('client_id', flat=True)
        return ('Купили подарки за баллы', qs.filter(id__in=client_ids))

    @staticmethod
    def _get_qr_scan_clients(qs, date_from, date_to=None, branch_id=None):
        """Клиенты, отсканировавшие QR за период (через ClientBranchVisit)."""
        from apps.tenant.branch.models import ClientBranchVisit
        visit_filters = Q()
        if date_from:
            visit_filters &= Q(created_at__gte=date_from)
        if date_to:
            visit_filters &= Q(created_at__lte=date_to)
        if branch_id:
            visit_filters &= Q(branch_id=branch_id)
        scan_ids = ClientBranchVisit.objects.filter(visit_filters).values_list('client_id', flat=True)
        return ('Отсканировали QR-код за период', qs.filter(id__in=scan_ids))

    @staticmethod
    def _get_birthday_greeting_clients(qs, date_from, date_to=None, branch_id=None):
        """Клиенты, получившие поздравление с ДР."""
        from apps.tenant.senler.models import MessageLog
        log_filters = Q(campaign__title__icontains="День Рождения")
        if date_from:
            log_filters &= Q(created_at__gte=date_from)
        if date_to:
            log_filters &= Q(created_at__lte=date_to)
        if branch_id:
            log_filters &= Q(client__branch_id=branch_id)
        client_ids = MessageLog.objects.filter(log_filters).values_list('client_id', flat=True)
        return ('Отправлено поздравлений с ДР', qs.filter(id__in=client_ids))

    @staticmethod
    def _get_read_message_clients(qs, date_from, date_to=None, branch_id=None):
        """Клиенты, прочитавшие хотя бы одно сообщение за период."""
        from apps.tenant.senler.models import MessageLog
        log_filters = Q(is_read=True)
        if date_from:
            log_filters &= Q(created_at__gte=date_from)
        if date_to:
            log_filters &= Q(created_at__lte=date_to)
        if branch_id:
            log_filters &= Q(client__branch_id=branch_id)
        client_ids = MessageLog.objects.filter(log_filters).values_list('client_id', flat=True)
        return ('% открываемости сообщений в ВК', qs.filter(id__in=client_ids))


class AwayView(LoginRequiredMixin, View):
    """Редирект на VK профиль"""
    def get(self, request, vk_user_id, *args, **kwargs):
        url = VKIntegrationService.get_profile_url(vk_user_id)
        if not url:
            raise Http404("VK profile not found or API error")
        return redirect(url)


class ReviewsListView(PeriodMixin, BranchMixin, BaseAdminStatsView, TemplateView):
    """Страница отзывов из ВК с фильтрацией по тональности"""
    template_name = 'general/reviews_list.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        period_ctx = self.get_period_context()
        branch_ctx = self.get_branch_context()
        context.update(period_ctx)
        context.update(branch_ctx)

        date_from = period_ctx['date_from']
        date_to = period_ctx['date_to']
        branch_id = branch_ctx.get('selected_branch_id')

        # Base filter
        filters = Q()
        if date_from:
            filters &= Q(created_at__gte=date_from)
        if date_to:
            filters &= Q(created_at__lte=date_to)
        if branch_id:
            filters &= Q(client__branch_id=branch_id)

        all_reviews = BranchTestimonials.objects.filter(filters).select_related(
            'client__client', 'client__branch'
        ).order_by('-created_at')

        # Sentiment filter
        sentiment = self.request.GET.get('sentiment')
        if sentiment in ('POSITIVE', 'NEGATIVE', 'NEUTRAL', 'SPAM'):
            reviews = all_reviews.filter(sentiment=sentiment)
        else:
            sentiment = None
            reviews = all_reviews

        # Build back_params for link to statistics
        back_parts = []
        if branch_id:
            back_parts.append(f'branch={branch_id}')
        custom_from = self.request.GET.get('custom_date_from')
        custom_to = self.request.GET.get('custom_date_to')
        if custom_from and custom_to:
            back_parts.append(f'custom_date_from={custom_from}')
            back_parts.append(f'custom_date_to={custom_to}')
        elif period_ctx['period_code'] and period_ctx['period_code'] != 'custom':
            back_parts.append(f'period={period_ctx["period_code"]}')

        base_parts = list(back_parts)
        base_params = '&'.join(base_parts)

        context.update({
            'reviews': reviews,
            'current_sentiment': sentiment,
            'total_count': all_reviews.count(),
            'positive_count': all_reviews.filter(sentiment='POSITIVE').count(),
            'negative_count': all_reviews.filter(sentiment='NEGATIVE').count(),
            'neutral_count': all_reviews.filter(sentiment='NEUTRAL').count(),
            'spam_count': all_reviews.filter(sentiment='SPAM').count(),
            'back_params': '&'.join(back_parts),
            'base_params': base_params,
        })
        return context


class ReviewReplyView(BaseAdminStatsView, View):
    """API для отправки ответа на отзыв через VK"""

    def post(self, request, *args, **kwargs):
        try:
            data = json.loads(request.body)
            review_id = data.get('review_id')
            text = data.get('text', '').strip()

            if not review_id or not text:
                return JsonResponse({'success': False, 'error': 'Укажите ID отзыва и текст'}, status=400)

            review = BranchTestimonials.objects.get(id=review_id)

            if not review.client:
                return JsonResponse({'success': False, 'error': 'Клиент не привязан к отзыву'}, status=400)

            from apps.tenant.senler.services import VKService
            service = VKService()
            if not service.is_configured:
                return JsonResponse({'success': False, 'error': 'VK не настроен'}, status=400)

            service.send_message(review.client, text)
            review.is_replied = True
            review.save(update_fields=['is_replied'])

            return JsonResponse({'success': True})
        except BranchTestimonials.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'Отзыв не найден'}, status=404)
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=500)


class RFAnalyticsView(BaseAdminStatsView, TemplateView):
    template_name = 'rfm/rfm_statistics.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['branches'] = Branch.objects.all()
        return context


class RFAnalyticsDetailView(BaseAdminStatsView, DetailView):
    template_name = "rfm/rfm_statistics_detail.html"
    model = Branch
    pk_url_kwarg = 'id'
    context_object_name = 'branch'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        branch = self.object

        matrix_data = RFAnalyticsService.get_matrix_data(branch)
        ranges = RFAnalyticsService.get_segment_ranges(matrix_data['segments'])
        settings_obj = RFSettings.objects.filter(branch=branch).first()
        
        top_guests = GuestRFScore.objects.filter(
            client__branch=branch, 
            segment__code='R3F3'
        ).select_related('client__client')[:10]

        context.update({
            'segments': matrix_data['segments'],
            'total_guests': matrix_data['total_guests'],
            'last_update': matrix_data['last_update'],
            
            'vip_count': matrix_data['kpi']['vip'],
            'at_risk_count': matrix_data['kpi']['at_risk'],
            'lost_count': matrix_data['kpi']['lost'],

            'f1_range': ranges['f1'], 'f2_range': ranges['f2'], 'f3_range': ranges['f3'],
            'r3_range': ranges['r3'], 'r2_range': ranges['r2'], 'r1_range': ranges['r1'], 'r0_range': ranges['r0'],
            
            'settings': settings_obj,
            'initial_guests': top_guests
        })
        return context


class RFGuestMigrationAnalyticsDetailView(BaseAdminStatsView, DetailView):
    template_name = "rfm/migration_analysis_detail.html"
    model = Branch
    pk_url_kwarg = 'id'
    context_object_name = 'branch'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        branch = self.object

        validator = MigrationFilterSerializer(data=self.request.GET)
        if not validator.is_valid():
            data = {'days': 30, 'segment': ''}
        else:
            data = validator.validated_data

        stats = RFMigrationService.get_migration_stats(
            branch=branch, 
            days=data['days'], 
            segment_code=data.get('segment')
        )

        recent_guests = RFMigrationService.get_recent_migrated_guests(
            branch=branch, 
            days=data['days']
        )

        all_segments = RFSegment.objects.all().order_by('-code')

        context.update({
            'sankey_data': stats['sankey_data'],
            'flow_stats': stats['flow_stats'],
            
            'growth_count': stats['kpi']['growth'],
            'real_churn_count': stats['kpi']['real_churn'],
            'natural_cooling_count': stats['kpi']['natural_cooling'],
            'reactivation_count': stats['kpi']['reactivation'],
            'retention_rate': stats['kpi']['retention_rate'],
            
            'recent_guests': recent_guests,
            'all_segments': all_segments,
            'days': data['days'],
            'selected_segment': data.get('segment'),
        })

        return context


class RFRecalculateView(APIView):
    def post(self, request, *args, **kwargs):
        serializer = RFRecalculateSerializer(data=request.data)
        if serializer.is_valid():
            result = RFManagementService.run_recalculation(
                branch_id=serializer.validated_data.get('branch')
            )
            
            if not result['success']:
                return Response(
                    {"error": result['error']}, 
                    status=status.HTTP_404_NOT_FOUND
                )

            return Response({
                "message": "Принудительный пересчёт RF успешно запущен.",
                "details": f"Обработано филиалов: {result['processed']}",
                "debug": result['branches'],
                "errors": result.get('errors', [])
            }, status=status.HTTP_200_OK)
            
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class RFSettingsSaveView(APIView):
    def post(self, request, *args, **kwargs):
        serializer = RFSettingsUpdateSerializer(data=request.data)
        
        if serializer.is_valid():
            try:
                RFManagementService.update_settings(
                    branch_id=serializer.validated_data['branch'],
                    settings_data=serializer.validated_data
                )
                return Response({
                    'status': 'success',
                    'message': 'Настройки успешно обновлены'
                }, status=status.HTTP_200_OK)
                
            except Exception as e:
                return Response({
                    'status': 'error', 
                    'message': f"Ошибка сохранения: {str(e)}"
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        return Response({
            'status': 'error',
            'message': 'Ошибка валидации данных',
            'errors': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)


class RFGetSegmentGuest(APIView):
    def get(self, request, segment_code, *args, **kwargs):
        branch_id = request.query_params.get('branch')
        if not branch_id:
            return Response(
                {"error": "Параметр branch обязателен"}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            result = RFGuestService.get_guests_by_segment(
                branch_id=branch_id, 
                segment_code=segment_code
            )
            
            guest_serializer = RFGuestListSerializer(result['guests_qs'], many=True)
            
            segment = result['segment']
            last_campaign_info = None
            if segment.last_campaign_date:
                delta = timezone.now() - segment.last_campaign_date
                days_ago = delta.days
                if days_ago == 0:
                    last_campaign_info = "сегодня"
                elif days_ago == 1:
                    last_campaign_info = "вчера"
                else:
                    last_campaign_info = f"{days_ago} дн. назад"
            
            return Response({
                'segment_name': segment.name,
                'segment_emoji': segment.emoji,
                'strategy': segment.strategy,
                'count': result['count'],
                'last_campaign': last_campaign_info,
                'guests': guest_serializer.data,
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {"error": str(e)}, 
                status=status.HTTP_404_NOT_FOUND
            )


class RFSegmentMailingView(APIView):
    def post(self, request, *args, **kwargs):
        branch_id = request.data.get('branch')
        segment_code = request.data.get('segment_code')
        text = request.data.get('text', '').strip()

        if not branch_id or not text:
            return Response(
                {"success": False, "error": "Укажите branch и text"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            branch = Branch.objects.get(id=branch_id)
            from apps.tenant.senler.services import VKService
            service = VKService()
            if not service.is_configured:
                return Response({"success": False, "error": "VK не настроен"}, status=400)

            if segment_code == 'all':
                clients = ClientBranch.objects.filter(
                    branch=branch,
                    is_allowed_message=True,
                    client__vk_user_id__isnull=False
                ).select_related('client')
            else:
                from apps.tenant.stats.models import GuestRFScore, RFSegment
                segment = RFSegment.objects.get(code=segment_code)
                scores = GuestRFScore.objects.filter(
                    client__branch=branch,
                    segment=segment
                ).select_related('client__client')
                clients = [s.client for s in scores if s.client.client and s.client.client.vk_user_id]

                segment.last_campaign_date = timezone.now()
                segment.save(update_fields=['last_campaign_date'])

            if not clients:
                return Response({"success": False, "error": "Нет получателей"}, status=400)

            service.send_batch_messages(clients, text)

            count = len(clients) if isinstance(clients, list) else clients.count()
            return Response({
                "success": True,
                "message": f"Рассылка отправлена {count} получателям"
            })

        except Branch.DoesNotExist:
            return Response({"success": False, "error": "Филиал не найден"}, status=404)
        except Exception as e:
            return Response({"success": False, "error": str(e)}, status=500)