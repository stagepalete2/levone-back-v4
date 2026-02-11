from django.shortcuts import redirect
from django.views.generic import TemplateView, DetailView, View
from django.http import Http404
from django.core.exceptions import PermissionDenied
from django.urls import reverse
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Count, F, Q
from datetime import timedelta

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone

from apps.shared.config.sites import tenant_admin

from apps.tenant.branch.models import Branch, ClientBranch, CoinTransaction


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
    Миксин, читающий GET-параметр ?period= и добавляющий
    в контекст resolved-диапазон + список вариантов для UI.
    """

    def get_period_context(self):
        period_code = self.request.GET.get('period', GeneralStatsService.DEFAULT_PERIOD)
        date_from, date_to, period_code = GeneralStatsService.resolve_period(period_code)
        return {
            'period_code': period_code,
            'date_from': date_from,
            'date_to': date_to,
            'period_choices': GeneralStatsService.PERIOD_CHOICES,
        }


class StatisticsView(PeriodMixin, BaseAdminStatsView, TemplateView):
    template_name = "general/statistics.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        period_ctx = self.get_period_context()
        context.update(period_ctx)

        # Получаем статистику за выбранный период
        context["stats"] = GeneralStatsService.get_dashboard_stats(
            period_code=period_ctx['period_code']
        )
        return context


class StatisticsDetailView(PeriodMixin, BaseAdminStatsView, TemplateView):
    template_name = 'general/statistics_detail.html'

    def get_context_data(self, stat_name, **kwargs):
        context = super().get_context_data(**kwargs)

        period_ctx = self.get_period_context()
        context.update(period_ctx)

        date_from = period_ctx['date_from']

        # Базовый QuerySet
        qs = ClientBranch.objects.all()
        if date_from:
            period_qs = qs.filter(created_at__gte=date_from)
        else:
            period_qs = qs

        # --- ПОДГОТОВКА СЛОЖНЫХ ФИЛЬТРОВ (ленивые — считаем только нужный) ---

        # --- КАРТА СТАТИСТИКИ (Mapping) ---
        title_map = {
            # 1. Всего клиентов (не зависит от периода)
            "total_clients": (
                'Общее количество оцифрованных гостей', 
                qs
            ),

            # 2. Новые за период
            "total_clients_last_month": (
                'Новые за период', 
                period_qs
            ),

            # 3. Получили суперприз (GAME)
            "new_clients_received_super_prize": (
                'Выиграли суперприз', 
                period_qs.filter(
                    is_joined_community=True,
                    superprizes__acquired_from='GAME'
                )
            ),

            # 4. Вернулись 2-й раз
            "clients_returned_second_time": lambda: self._get_returned_clients(qs, date_from),

            # 5. Скан в День Рождения
            "clients_birthday_qr": lambda: self._get_birthday_clients(qs, date_from),

            # 6. Купили подарки (Трата коинов)
            "clients_bought_prizes": (
                'Купили подарки', 
                self._get_bought_prizes_qs(qs, date_from)
            ),

            # 7. Выложили сторис
            "clients_posted_story": (
                'Опубликовали истории', 
                period_qs.filter(is_story_uploaded=True)
            ),

            # 8. Рефералы
            "clients_from_referral": (
                'Перешли по реферальной ссылке', 
                period_qs.filter(invited_by__isnull=False)
            ),
        }

        entry = title_map.get(stat_name)

        if entry is not None:
            if callable(entry):
                # Ленивые тяжёлые запросы
                title, filtered_qs = entry()
            else:
                title, filtered_qs = entry

            context['stat'] = title
            context["clients"] = filtered_qs.distinct()
        
        context["stat_name"] = stat_name
        context["breadcrumbs"] = [
            {"title": "Домой", "url": reverse("admin:index")},
            {"title": "Общая статистика", "url": reverse("admin-statistics")},
            {"title": context.get('stat', stat_name), "url": ""},
        ]
        return context

    # ── Вспомогательные методы (вынесены, чтобы не считать всё подряд) ──

    @staticmethod
    def _get_returned_clients(qs, date_from):
        attempt_filters = {}
        if date_from:
            attempt_filters['created_at__gte'] = date_from
        repeat_client_ids = ClientAttempt.objects.filter(
            **attempt_filters
        ).values('client').annotate(
            attempt_count=Count('id')
        ).filter(attempt_count__gte=2).values_list('client', flat=True)
        return ('Вернулись повторно', qs.filter(id__in=repeat_client_ids))

    @staticmethod
    def _get_birthday_clients(qs, date_from):
        filters = Q(
            client__birth_date__isnull=False,
            created_at__day=F('client__birth_date__day'),
            created_at__month=F('client__birth_date__month'),
        )
        if date_from:
            filters &= Q(created_at__gte=date_from)
        birthday_attempt_ids = ClientAttempt.objects.filter(filters).values_list('client', flat=True)
        return ('Сканировали в День Рождения', qs.filter(id__in=birthday_attempt_ids))

    @staticmethod
    def _get_bought_prizes_qs(qs, date_from):
        expense_filter = Q(transactions__type="EXPENSE")
        if date_from:
            expense_filter &= Q(transactions__created_at__gte=date_from)
        return qs.filter(expense_filter)


class AwayView(LoginRequiredMixin, View):
    """Редирект на VK профиль"""
    def get(self, request, vk_user_id, *args, **kwargs):
        url = VKIntegrationService.get_profile_url(vk_user_id)
        if not url:
            raise Http404("VK profile not found or API error")
        return redirect(url)


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

        # 1. Получаем данные матрицы через сервис
        matrix_data = RFAnalyticsService.get_matrix_data(branch)
        
        # 2. Получаем диапазоны для заголовков (F1, R1 и т.д.)
        ranges = RFAnalyticsService.get_segment_ranges(matrix_data['segments'])
        
        # 3. Настройки и примеры гостей
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

        # 1. Валидация входных данных
        validator = MigrationFilterSerializer(data=self.request.GET)
        if not validator.is_valid():
            data = {'days': 30, 'segment': ''}
        else:
            data = validator.validated_data

        # 2. Получение статистики через сервис
        stats = RFMigrationService.get_migration_stats(
            branch=branch, 
            days=data['days'], 
            segment_code=data.get('segment')
        )

        # 3. Получение списка гостей для таблицы
        recent_guests = RFMigrationService.get_recent_migrated_guests(
            branch=branch, 
            days=data['days']
        )

        # 4. Вспомогательные данные
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
    """
    Принудительный пересчёт RF для всех гостей текущего тенанта.
    """
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
    """
    Сохранение настроек и порогов RF-анализа.
    """
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
    """
    Получение списка гостей конкретного сегмента.
    """
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
            
            # Calculate days since last campaign
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
