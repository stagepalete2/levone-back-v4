import requests
import json
import logging
from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from django.db.models import Count, F, Q, Max
from django.db.models.functions import ExtractDay, ExtractMonth
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.utils.timezone import now

from apps.tenant.branch.models import ClientBranch, Branch
from apps.tenant.game.models import ClientAttempt
from apps.tenant.senler.models import MessageLog
from apps.tenant.stats.models import (
    RFSegment, GuestRFScore, RFMigrationLog, 
    RFSettings, BranchSegmentSnapshot
)
from apps.tenant.stats.iiko import IIKOService
from apps.tenant.stats.dooglys import DooglysService

logger = logging.getLogger(__name__)


class GeneralStatsService:
    """Сервис для общей статистики (Dashboard)"""

    # ────────────────────────────────────────────
    # Предустановленные периоды (код → дней назад)
    # ────────────────────────────────────────────
    PERIOD_CHOICES = {
        'today':     ('Сегодня',       0),
        '7d':        ('7 дней',        7),
        '30d':       ('30 дней',       30),
        '90d':       ('90 дней',       90),
        '365d':      ('За год',        365),
        'all':       ('За всё время',  None),
    }
    DEFAULT_PERIOD = '30d'

    @classmethod
    def resolve_period(cls, period_code: str):
        """
        Возвращает (date_from, date_to) по коду периода.
        date_to всегда = now(), date_from = now() - N дней (или None для 'all').
        """
        if period_code not in cls.PERIOD_CHOICES:
            period_code = cls.DEFAULT_PERIOD

        _, days = cls.PERIOD_CHOICES[period_code]
        date_to = now()

        if days is None:
            date_from = None           # без ограничения
        elif days == 0:
            date_from = date_to.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            date_from = date_to - timedelta(days=days)

        return date_from, date_to, period_code

    @classmethod
    def resolve_custom_period(cls, date_from_str: str, date_to_str: str):
        """
        Возвращает (date_from, date_to) по пользовательским датам из календаря.
        
        :param date_from_str: Дата начала в формате YYYY-MM-DD
        :param date_to_str: Дата окончания в формате YYYY-MM-DD
        :return: (date_from, date_to, 'custom')
        """
        from datetime import datetime
        try:
            # Парсим даты
            date_from = datetime.strptime(date_from_str, '%Y-%m-%d')
            date_to = datetime.strptime(date_to_str, '%Y-%m-%d')
            
            # Устанавливаем время: начало дня для date_from, конец дня для date_to
            date_from = timezone.make_aware(
                date_from.replace(hour=0, minute=0, second=0, microsecond=0)
            )
            date_to = timezone.make_aware(
                date_to.replace(hour=23, minute=59, second=59, microsecond=999999)
            )
            
            return date_from, date_to, 'custom'
        except (ValueError, TypeError):
            # В случае ошибки парсинга возвращаем период по умолчанию
            logger.warning(f"Invalid custom dates: {date_from_str}, {date_to_str}. Using default period.")
            return cls.resolve_period(cls.DEFAULT_PERIOD)

    # ────────────────────────────────────────────
    # Staff Engagement Index
    # ────────────────────────────────────────────
    @staticmethod
    def get_staff_engagement_index(date_from=None, date_to=None):
        """
        (Games served by staff / Total games) * 100
        Считает за указанный период; если date_from=None — за всё время.
        """
        filters = {}
        if date_from:
            filters['created_at__gte'] = date_from
        if date_to:
            filters['created_at__lte'] = date_to

        total_attempts = ClientAttempt.objects.filter(**filters).count()
        if total_attempts == 0:
            return 0

        staff_attempts = ClientAttempt.objects.filter(
            served_by__isnull=False, **filters
        ).count()

        return int((staff_attempts / total_attempts) * 100)

    # ────────────────────────────────────────────
    # Основной метод Dashboard
    # ────────────────────────────────────────────
    @classmethod
    def get_dashboard_stats(cls, period_code: str = None, branch_id: int = None):
        """
        Собирает статистику за указанный период и филиал.

        :param period_code: ключ из PERIOD_CHOICES ('today', '7d', …, 'all')
        :param branch_id: ID филиала для фильтрации (опционально)
        """
        date_from, date_to, period_code = cls.resolve_period(
            period_code or cls.DEFAULT_PERIOD
        )

        base_qs = ClientBranch.objects.all()
        
        # Фильтрация по филиалу
        if branch_id:
            base_qs = base_qs.filter(branch_id=branch_id)

        # ── Фильтр по периоду (created_at) ──
        period_qs = base_qs
        if date_from:
            period_qs = base_qs.filter(created_at__gte=date_from)

        # ── Базовые подсчёты ──
        total_clients = base_qs.values("client").distinct().count()                # всегда «все»
        total_clients_period = period_qs.values("client").distinct().count()        # за период

        # FIX: использован period_qs вместо глобального ClientBranch.objects
        super_prize_new = period_qs.filter(
            is_joined_community=True,
            superprizes__acquired_from='GAME'
        ).distinct().count()

        # Вернулись второй раз
        attempt_filters = {}
        if date_from:
            attempt_filters['created_at__gte'] = date_from
        if branch_id:
            attempt_filters['client__branch_id'] = branch_id
        clients_returned = ClientAttempt.objects.filter(
            **attempt_filters
        ).values("client").annotate(
            cnt=Count("id")
        ).filter(cnt__gte=2).count()

        # Купили подарки
        expense_filter = Q(transactions__type="EXPENSE")
        if date_from:
            expense_filter &= Q(transactions__created_at__gte=date_from)
        bought_prizes = base_qs.filter(expense_filter).values("client").distinct().count()

        # Выложили сторис
        posted_story = period_qs.filter(is_story_uploaded=True).values("client").distinct().count()

        # Рефералы
        referral = period_qs.filter(invited_by__isnull=False).values("client").distinct().count()

        # Staff Engagement Index
        staff_index = cls.get_staff_engagement_index(date_from, date_to)

        # ── Метрики рассылок ──
        msg_filters = Q(status='sent')
        if date_from:
            msg_filters &= Q(sent_at__gte=date_from)

        sent_greetings = MessageLog.objects.filter(
            msg_filters,
            campaign__title__icontains="День Рождения",
        ).count()

        # Activated Birthday Prizes
        try:
            from apps.tenant.inventory.models import SuperPrize
            bp_filters = Q(acquired_from='BIRTHDAY', activated_at__isnull=False)
            if date_from:
                bp_filters &= Q(activated_at__gte=date_from)
            activated_birthday_prizes = SuperPrize.objects.filter(bp_filters).count()
        except Exception as e:
            logger.warning("Could not fetch birthday prizes: %s", e)
            activated_birthday_prizes = 0

        # Open Rate
        total_sent = MessageLog.objects.filter(msg_filters).count()
        total_read = MessageLog.objects.filter(msg_filters, is_read=True).count()
        open_rate = int((total_read / total_sent * 100)) if total_sent > 0 else 0

        # ── VK подписчики (не зависят от периода) ──
        group_subscribers = 0
        mailing_subscribers = 0
        try:
            from apps.tenant.senler.services import VKService
            vk_service = VKService()
            group_subscribers = vk_service.get_group_members_count()
            mailing_subscribers = vk_service.get_mailing_subscribers_count()
        except Exception as e:
            logger.warning("VK service error: %s", e)

        # ── Данные о гостях из POS систем (IIKO / Dooglys) ──
        # Для периода "сегодня" (days=0) берём данные за текущие сутки.
        # Для остальных периодов используем тот же диапазон date_from / date_to.
        qr_scans_today = 0
        pos_guests_today = 0
        scan_index = 0.0
        guests_by_branch = {}  # Детализация по филиалам

        try:
            from apps.tenant.branch.models import ClientBranchVisit
            from datetime import date as _date

            # ── Определяем даты для POS-запросов ──
            if period_code == 'today' or date_from is None:
                # «Сегодня» — текущие сутки
                pos_date_from = _date.today()
                pos_date_to   = _date.today()
            else:
                pos_date_from = date_from.date() if hasattr(date_from, 'date') else date_from
                pos_date_to   = date_to.date()   if hasattr(date_to,   'date') else date_to

            # ── QR-сканирования за период с учётом фильтра по филиалу ──
            qr_visits_filter = Q(visited_at__gte=date_from) if date_from else Q()
            if branch_id:
                qr_visits_filter &= Q(client__branch_id=branch_id)

            qr_scans_today = ClientBranchVisit.objects.filter(qr_visits_filter).count()

            # ── Получение данных о гостях из POS систем ──
            if branch_id:
                branches = Branch.objects.filter(id=branch_id)
            else:
                branches = Branch.objects.all()

            for branch_obj in branches:
                branch_guests = 0
                source_type   = None

                if getattr(branch_obj, 'iiko_organization_id', None) and \
                        branch_obj.iiko_organization_id.strip():
                    # IIKO: поддерживает фильтрацию по датам в OLAP
                    try:
                        iiko_service  = IIKOService()
                        branch_guests = iiko_service.get_olap_guests_count(
                            date_from=pos_date_from,
                            date_to=pos_date_to,
                            department=branch_obj.iiko_organization_id,
                        ).get(branch_obj.iiko_organization_id, 0)
                        source_type = 'IIKO'
                    except Exception as exc:
                        logger.warning("IIKO error for branch %s: %s", branch_obj.id, exc)

                elif getattr(branch_obj, 'dooglys_branch_id', None):
                    # Dooglys: /sales/order/list с Unix Timestamps, X-Pagination-Total-Count
                    try:
                        dooglys_service = DooglysService()
                        branch_guests   = dooglys_service.get_guests_for_period(
                            date_from=pos_date_from,
                            date_to=pos_date_to,
                            branch=branch_obj,
                        )
                        source_type = 'Dooglys'
                    except Exception as exc:
                        logger.warning("Dooglys error for branch %s: %s", branch_obj.id, exc)

                # Сохраняем детализацию по филиалу
                if branch_guests > 0 or source_type:
                    guests_by_branch[branch_obj.id] = {
                        'name':   branch_obj.name,
                        'count':  branch_guests,
                        'source': source_type,
                    }

                pos_guests_today += branch_guests

            # ── Индекс сканирования (QR / POS × 100 %) ──
            if pos_guests_today > 0 and qr_scans_today > 0:
                scan_index = round((qr_scans_today / pos_guests_today) * 100, 2)
            else:
                scan_index = 0.0

        except Exception as exc:
            logger.error("POS systems integration error: %s", exc)

        return {
            "total_clients": total_clients,
            "total_clients_period": total_clients_period,
            # Обратная совместимость (шаблон detail ожидает old key)
            "total_clients_last_month": total_clients_period,
            "new_clients_received_super_prize": super_prize_new,
            "clients_returned_second_time": clients_returned,
            "sent_greetings": sent_greetings,
            "sent_birthday_greetings": sent_greetings,
            "activated_birthday_prizes": activated_birthday_prizes,
            "clients_bought_prizes": bought_prizes,
            "clients_posted_story": posted_story,
            "clients_from_referral": referral,
            "staff_engagement_index": staff_index,
            "group_subscribers": group_subscribers,
            "mailing_subscribers": mailing_subscribers,
            "qr_scans_today": qr_scans_today,
            "pos_guests_today": pos_guests_today,
            "iiko_guests_today": pos_guests_today,  # Для обратной совместимости
            "pos_guests_by_branch": guests_by_branch,  # Детализация по филиалам (IIKO + Dooglys)
            "iiko_guests_by_branch": guests_by_branch,  # Для обратной совместимости
            "scan_index": scan_index,
            "open_rate": open_rate,
            # Период, за который считались POS-данные (для отображения в шаблоне)
            "pos_date_from": locals().get('pos_date_from'),
            "pos_date_to":   locals().get('pos_date_to'),
        }

class RFAnalyticsService:
    """Сервис для RFM анализа и Матрицы"""

    @staticmethod
    def get_matrix_data(branch):
        """
        Подготавливает данные для RF-матрицы на основе последнего Snapshot.
        """
        # 1. Получаем последний снэпшот
        last_snap = BranchSegmentSnapshot.objects.filter(branch=branch).order_by('-date').first()
        if not last_snap:
            return {
                'segments': [],
                'total_guests': 0,
                'last_update': None,
                'kpi': {'vip': 0, 'at_risk': 0, 'lost': 0}
            }

        snapshots = BranchSegmentSnapshot.objects.filter(
            branch=branch, 
            date=last_snap.date
        ).select_related('segment')

        # 2. Формируем список сегментов с количеством
        segments_data = []
        total_guests = 0
        
        # Счетчики KPI
        vip_count = 0
        at_risk_count = 0
        lost_count = 0

        for snap in snapshots:
            seg = snap.segment
            seg.guests_count = snap.guests_count 
            total_guests += snap.guests_count
            segments_data.append(seg)

            # KPI logic based on codes
            if seg.code.endswith('F3'):
                vip_count += snap.guests_count
            if seg.code.startswith('R1'):
                at_risk_count += snap.guests_count
            if seg.code.startswith('R0'):
                lost_count += snap.guests_count

        # 3. Сортировка сегментов
        def safe_sort_key(seg):
            try:
                r_part = seg.code.split('F')[0].replace('R', '')
                f_part = seg.code.split('F')[1]
                return (-int(r_part), int(f_part))
            except (IndexError, ValueError):
                return (0, 0)

        segments_data.sort(key=safe_sort_key)

        return {
            'segments': segments_data,
            'total_guests': total_guests,
            'last_update': last_snap.date,
            'kpi': {
                'vip': vip_count,
                'at_risk': at_risk_count,
                'lost': lost_count
            }
        }

    @staticmethod
    def get_segment_ranges(segments):
        """Извлекает примеры сегментов для заголовков таблицы (F1, F2... R1, R2...)"""
        ranges = {
            'f1': next((s for s in segments if s.code.endswith('F1')), None),
            'f2': next((s for s in segments if s.code.endswith('F2')), None),
            'f3': next((s for s in segments if s.code.endswith('F3')), None),
            'r3': next((s for s in segments if s.code.startswith('R3')), None),
            'r2': next((s for s in segments if s.code.startswith('R2')), None),
            'r1': next((s for s in segments if s.code.startswith('R1')), None),
            'r0': next((s for s in segments if s.code.startswith('R0')), None),
        }
        return ranges
    
class RFCalculator:
    def __init__(self, branch):
        self.branch = branch
        self.settings, _ = RFSettings.objects.get_or_create(branch=branch)
        self.segments = list(RFSegment.objects.all())

    def run_analysis(self):
        today_dt = timezone.now()
        today_date = today_dt.date() 
        
        period_start = today_dt - timezone.timedelta(days=self.settings.analysis_period)

        guests = ClientBranch.objects.filter(branch=self.branch).annotate(
            last_attempt=Max('game_attempts__created_at'),
            attempt_count=Count('game_attempts', filter=Q(game_attempts__created_at__gte=period_start))
        )
        
        # Pre-fetch existing scores to memory
        existing_scores = {
            gs.client_id: gs 
            for gs in GuestRFScore.objects.filter(client__branch=self.branch)
        }

        to_create = []
        to_update = []
        migration_logs = []

        for cb in guests:
            if cb.last_attempt:
                days_since = (today_date - cb.last_attempt.date()).days
            else:
                days_since = 999
                
            segment = self.find_segment_by_ranges(days_since, cb.attempt_count)
            if not segment:
                continue

            score = existing_scores.get(cb.id)
            
            if not score:
                to_create.append(GuestRFScore(
                    client=cb,
                    segment=segment,
                    recency_days=days_since,
                    frequency=cb.attempt_count,
                    r_score=int(segment.code[1]),
                    f_score=int(segment.code[3])
                ))
            else:
                is_changed = False
                
                if score.segment_id != segment.id:
                    migration_logs.append(RFMigrationLog(
                        client=cb,
                        from_segment=score.segment,
                        to_segment=segment
                    ))
                    score.segment = segment
                    score.r_score = int(segment.code[1])
                    score.f_score = int(segment.code[3])
                    is_changed = True
                
                if score.recency_days != days_since or score.frequency != cb.attempt_count:
                    score.recency_days = days_since
                    score.frequency = cb.attempt_count
                    is_changed = True
                
                if is_changed:
                    to_update.append(score)

        # Bulk Operations
        if to_create:
            GuestRFScore.objects.bulk_create(to_create, batch_size=500)
            
        if to_update:
            GuestRFScore.objects.bulk_update(
                to_update, 
                ['segment', 'recency_days', 'frequency', 'r_score', 'f_score'],
                batch_size=500
            )
            
        if migration_logs:
            RFMigrationLog.objects.bulk_create(migration_logs, batch_size=500)

        self._update_segment_snapshot(today_date)

    def _update_segment_snapshot(self, snapshot_date):
        """Создаёт/обновляет BranchSegmentSnapshot на основе текущих GuestRFScore"""
        score_counts = (
            GuestRFScore.objects
            .filter(client__branch=self.branch, segment__isnull=False)
            .values('segment_id')
            .annotate(cnt=Count('id'))
        )

        counts_map = {item['segment_id']: item['cnt'] for item in score_counts}

        for segment in self.segments:
            guest_count = counts_map.get(segment.id, 0)
            BranchSegmentSnapshot.objects.update_or_create(
                branch=self.branch,
                segment=segment,
                date=snapshot_date,
                defaults={'guests_count': guest_count}
            )

    def find_segment_by_ranges(self, days, count):
        """Ищет сегмент на основе числовых диапазонов в БД"""
        for seg in self.segments:
            if (seg.recency_min <= days <= seg.recency_max) and \
               (seg.frequency_min <= count <= seg.frequency_max):
                return seg
        return None

class RFManagementService:
    """Сервис для управления процессами RF (пересчет, настройки)"""

    @staticmethod
    def run_recalculation(branch_id=None):
        if branch_id:
            branches = Branch.objects.filter(id=branch_id)
        else:
            branches = Branch.objects.all()

        if not branches.exists():
            return {"success": False, "error": "Филиалы не найдены", "processed": 0}

        processed_count = 0
        errors = []

        for branch in branches:
            try:
                calculator = RFCalculator(branch)
                calculator.run_analysis()
                processed_count += 1
            except Exception as e:
                errors.append(f"Branch {branch.id}: {str(e)}")
        
        return {
            "success": True,
            "processed": processed_count,
            "branches": list(branches.values_list('name', flat=True)),
            "errors": errors
        }

    @staticmethod
    def update_settings(branch_id, settings_data):
        with transaction.atomic():
            branch = get_object_or_404(Branch, id=branch_id)
            
            period = settings_data.get('analysis_period', 365)
            RFSettings.objects.update_or_create(
                branch=branch, 
                defaults={'analysis_period': period}
            )

            r3 = settings_data.get('r3_max')
            r2 = settings_data.get('r2_max')
            r1 = settings_data.get('r1_max')
            f1 = settings_data.get('f1_max')
            f2 = settings_data.get('f2_max')

            segments = RFSegment.objects.all()
            updated_segments = []

            for seg in segments:
                is_changed = False
                code = seg.code
                
                if code.startswith('R3'):
                    seg.recency_min, seg.recency_max = 0, r3
                    is_changed = True
                elif code.startswith('R2'):
                    seg.recency_min, seg.recency_max = r3 + 1, r2
                    is_changed = True
                elif code.startswith('R1'):
                    seg.recency_min, seg.recency_max = r2 + 1, r1
                    is_changed = True
                elif code.startswith('R0'):
                    seg.recency_min, seg.recency_max = r1 + 1, 9999
                    is_changed = True

                if code.endswith('F1'):
                    seg.frequency_min, seg.frequency_max = 1, f1
                    is_changed = True
                elif code.endswith('F2'):
                    seg.frequency_min, seg.frequency_max = f1 + 1, f2
                    is_changed = True
                elif code.endswith('F3'):
                    seg.frequency_min, seg.frequency_max = f2 + 1, 9999
                    is_changed = True
                
                if is_changed:
                    updated_segments.append(seg)
                
            if updated_segments:
                RFSegment.objects.bulk_update(updated_segments, [
                    'recency_min', 'recency_max', 
                    'frequency_min', 'frequency_max'
                ])
            
            return True

class RFMigrationService:
    """Сервис для анализа переходов (миграций) между сегментами"""

    @staticmethod
    def get_migration_stats(branch, days=30, segment_code=None):
        start_date = now() - timedelta(days=days)
        
        logs_qs = RFMigrationLog.objects.filter(
            client__branch=branch,
            migrated_at__gte=start_date
        ).select_related('from_segment', 'to_segment')

        if segment_code:
            logs_qs = logs_qs.filter(
                Q(from_segment__code=segment_code) | 
                Q(to_segment__code=segment_code)
            )

        flow_stats = logs_qs.values(
            'from_segment__name', 'from_segment__emoji', 'from_segment__code',
            'to_segment__name', 'to_segment__emoji', 'to_segment__code'
        ).annotate(count=Count('id')).order_by('-count')

        sankey_data = []
        for f in flow_stats:
            source = f"{f.get('from_segment__emoji', '')} {f.get('from_segment__name', 'Unknown')}"
            target = f"{f.get('to_segment__emoji', '')} {f.get('to_segment__name', 'Unknown')}"
            sankey_data.append([source, target, f['count']])

        growth = logs_qs.filter(to_segment__code__gt=F('from_segment__code')).count()
        drops_qs = logs_qs.filter(to_segment__code__lt=F('from_segment__code'))
        real_churn = logs_qs.filter(to_segment__code__startswith='R0').count()
        natural_cooling = drops_qs.exclude(to_segment__code__startswith='R0').count()
        
        reactivation = logs_qs.filter(
            from_segment__code__startswith='R0', 
            to_segment__code__gt='R0'
        ).count()

        total_negative = real_churn + natural_cooling
        denominator = growth + total_negative
        retention_rate = int((growth / denominator * 100)) if denominator > 0 else 0

        return {
            'sankey_data': json.dumps(sankey_data, ensure_ascii=False),
            'flow_stats': flow_stats,
            'kpi': {
                'growth': growth,
                'real_churn': real_churn,
                'natural_cooling': natural_cooling,
                'reactivation': reactivation,
                'retention_rate': retention_rate
            }
        }

    @staticmethod
    def get_recent_migrated_guests(branch, days=30, limit=9):
        start_date = now() - timedelta(days=days)
        
        unique_ids = list(RFMigrationLog.objects.filter(
            client__branch=branch,
            migrated_at__gte=start_date
        ).order_by('-migrated_at').values_list('client_id', flat=True).distinct()[:limit])

        if not unique_ids:
            return []

        scores = GuestRFScore.objects.filter(
            client_id__in=unique_ids
        ).select_related('client__client', 'segment')

        all_logs = RFMigrationLog.objects.filter(
            client_id__in=unique_ids
        ).select_related('from_segment', 'to_segment').order_by('-migrated_at')

        logs_by_client = {}
        for log in all_logs:
            if log.client_id not in logs_by_client:
                logs_by_client[log.client_id] = []
            if len(logs_by_client[log.client_id]) < 3:
                logs_by_client[log.client_id].append(log)

        result = []
        for s in scores:
            result.append({
                'info': s.client,
                'current': s,
                'history': logs_by_client.get(s.client_id, [])
            })
        
        return result

class RFGuestService:
    """Сервис для получения данных о гостях в сегментах"""

    @staticmethod
    def get_guests_by_segment(branch_id, segment_code):
        branch = get_object_or_404(Branch, id=branch_id)
        segment = get_object_or_404(RFSegment, code=segment_code)

        guests = GuestRFScore.objects.filter(
            client__branch=branch, 
            segment=segment
        ).select_related(
            'client__client'
        ).annotate(
            last_visit_date=Max('client__game_attempts__created_at')
        ).order_by('-calculated_at')

        return {
            'segment': segment,
            'guests_qs': guests,
            'count': guests.count()
        }


class VKIntegrationService:
    @staticmethod
    def get_profile_url(vk_user_id):
        token = settings.VK_SECRET
        url = "https://api.vk.com/method/users.get"
        params = {
            "user_ids": vk_user_id,
            "fields": "domain",
            "access_token": token,
            "v": "5.131",
        }

        try:
            response = requests.get(url, params=params, timeout=5)
            response.raise_for_status()
            result = response.json()
            
            if "response" in result and result["response"]:
                user_info = result["response"][0]
                profile_name = user_info.get("domain") or f"id{user_info.get('id')}"
                return f"https://vk.com/{profile_name}"
                
        except (requests.RequestException, ValueError, IndexError):
            pass
            
        return None