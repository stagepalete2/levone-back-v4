import requests
import json
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

class GeneralStatsService:
    """Сервис для общей статистики (Dashboard)"""
    
    @staticmethod
    def get_staff_engagement_index(base_qs=None):
        """
        Calculates Staff Engagement Index:
        (Games served by staff / Total games) * 100
        """
        # We need to filter ClientAttempt, not ClientBranch
        # Assuming base_qs is ClientBranch, we can get attempts through relation
        
        # Total attempts in the last 30 days
        month_ago = now() - timedelta(days=30)
        
        total_attempts = ClientAttempt.objects.filter(
            created_at__gte=month_ago
        ).count()
        
        if total_attempts == 0:
            return 0
            
        staff_attempts = ClientAttempt.objects.filter(
            created_at__gte=month_ago,
            served_by__isnull=False
        ).count()
        
        return int((staff_attempts / total_attempts) * 100)

    @staticmethod
    def get_dashboard_stats(base_qs=None):
        """
        Собирает общую статистику.
        :param base_qs: QuerySet ClientBranch (обычно отфильтрованный по тенанту)
        """
        if base_qs is None:
            base_qs = ClientBranch.objects.all()

        month_ago = now() - timedelta(days=30)
        
        # Предварительные агрегации для оптимизации
        total_clients = base_qs.values("client").distinct().count()
        last_month = base_qs.filter(created_at__gte=month_ago).values("client").distinct().count()
        
        # Сложные метрики выносим в отдельные методы или оставляем здесь если они специфичны
        super_prize_new = ClientBranch.objects.filter(
            is_joined_community=True,
            superprizes__acquired_from='GAME'
        ).distinct().count()

        # Вернулись второй раз (Оптимизированный запрос через exists или count в аннотации)
        # Логика: ClientAttempt ссылается на ClientBranch как 'client'
        clients_returned = ClientAttempt.objects.values("client").annotate(
            cnt=Count("id")
        ).filter(cnt__gte=2).count()

        # День рождения (QR сканирован в ДР)
        # Replacing this with "Sent Greetings" as per requirements
        # But keeping logic if they want both? The req says "Metric instead of 'birthdays', sent greetings"
        # We will fetch Sent Greetings count from MessageLog
        
        # bought_prizes logic...
        bought_prizes = base_qs.filter(transactions__type="EXPENSE").values("client").distinct().count() # Fixed type string
        posted_story = base_qs.filter(is_story_uploaded=True).values("client").distinct().count()
        referral = base_qs.filter(invited_by__isnull=False).values("client").distinct().count()
        
        # New Metrics
        staff_index = GeneralStatsService.get_staff_engagement_index(base_qs)
        
        # Sent Birthday Greetings (Last 30 days)
        # We look for MessageLogs linked to campaigns with title containing "День Рождения"
        sent_greetings = MessageLog.objects.filter(
            campaign__title__icontains="День Рождения",
            status='sent',
            sent_at__gte=month_ago
        ).count()

        # Activated Birthday Prizes (Last 30 days)
        # Count SuperPrizes with source BIRTHDAY that were activated
        from apps.tenant.inventory.models import SuperPrize
        activated_birthday_prizes = SuperPrize.objects.filter(
            acquired_from='BIRTHDAY',
            activated_at__isnull=False,
            activated_at__gte=month_ago
        ).count()

        # VK Subscribers (Group + Mailing)
        from apps.tenant.senler.services import VKService
        vk_service = VKService()
        group_subscribers = vk_service.get_group_members_count()
        mailing_subscribers = vk_service.get_mailing_subscribers_count()

        # Scan Index: QR scans today / IIKO guests today * 100
        # Shows how many IIKO guests scanned QR and used our app
        from apps.tenant.stats.iiko import IIKOService
        from apps.tenant.branch.models import ClientBranchVisit
        from django.utils import timezone
        
        iiko_service = IIKOService()
        
        # QR scans today
        today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        qr_scans_today = ClientBranchVisit.objects.filter(
            visited_at__gte=today_start
        ).count()
        
        # IIKO guests today
        iiko_guests_today = iiko_service.get_total_guests_today()
        
        # Calculate scan index
        scan_index = iiko_service.calculate_scan_index(qr_scans_today, iiko_guests_today)
        
        # Open Rate: % of sent messages that were read
        total_sent = MessageLog.objects.filter(
            status='sent',
            sent_at__gte=month_ago
        ).count()
        
        total_read = MessageLog.objects.filter(
            status='sent',
            is_read=True,
            sent_at__gte=month_ago
        ).count()
        
        open_rate = int((total_read / total_sent * 100)) if total_sent > 0 else 0

        return {
            "total_clients": total_clients,
            "total_clients_last_month": last_month,
            "new_clients_received_super_prize": super_prize_new,
            "clients_returned_second_time": clients_returned,
            "sent_greetings": sent_greetings,  # Renamed from sent_birthday_greetings for template
            "sent_birthday_greetings": sent_greetings,  # Keep for backwards compat
            "activated_birthday_prizes": activated_birthday_prizes,
            "clients_bought_prizes": bought_prizes,
            "clients_posted_story": posted_story,
            "clients_from_referral": referral,
            "staff_engagement_index": staff_index,
            "group_subscribers": group_subscribers,
            "mailing_subscribers": mailing_subscribers,
            "qr_scans_today": qr_scans_today,
            "iiko_guests_today": iiko_guests_today,
            "scan_index": scan_index,
            "open_rate": open_rate,  # New: % messages read
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
            # Добавляем атрибут guests_count прямо к объекту сегмента для шаблона
            # (или лучше использовать словарь, но для совместимости с шаблоном оставим так)
            seg.guests_count = snap.guests_count 
            total_guests += snap.guests_count
            segments_data.append(seg)

            # KPI logic based on codes (Hardcoded business rules)
            if seg.code.endswith('F3'):
                vip_count += snap.guests_count
            if seg.code.startswith('R1'):
                at_risk_count += snap.guests_count
            if seg.code.startswith('R0'):
                lost_count += snap.guests_count

        # 3. Сортировка сегментов
        # Используем надежную сортировку: парсим R и F
        def safe_sort_key(seg):
            try:
                # Ожидаемый формат RxFy
                r_part = seg.code.split('F')[0].replace('R', '')
                f_part = seg.code.split('F')[1]
                return (-int(r_part), int(f_part)) # R убывает (3->0), F возрастает (1->3)
            except (IndexError, ValueError):
                return (0, 0) # Fallback

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
        # Это вспомогательная функция для отображения "от 0 до 30 дней" в заголовках
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
        # Используем localdate() для корректного сравнения календарных дней
        today_dt = timezone.now()
        today_date = today_dt.date() 
        
        period_start = today_dt - timezone.timedelta(days=self.settings.analysis_period)

        guests = ClientBranch.objects.filter(branch=self.branch).annotate(
            # Дату последнего визита ищем за всё время
            last_attempt=Max('game_attempts__created_at'), # FIX: client_attempt -> game_attempts (related_name check)
            # Количество визитов считаем за период
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
                # Create new
                to_create.append(GuestRFScore(
                    client=cb,
                    segment=segment,
                    recency_days=days_since,
                    frequency=cb.attempt_count,
                    r_score=int(segment.code[1]),
                    f_score=int(segment.code[3])
                ))
            else:
                # Update existing
                is_changed = False
                
                # Check for segment change (Migration)
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
                
                # Check for metric changes
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

    def find_segment_by_ranges(self, days, count):
        """Ищет сегмент на основе числовых диапазонов в БД"""
        # Оптимизация: сегменты уже загружены в __init__
        for seg in self.segments:
            if (seg.recency_min <= days <= seg.recency_max) and \
               (seg.frequency_min <= count <= seg.frequency_max):
                return seg
        return None

class RFManagementService:
    """Сервис для управления процессами RF (пересчет, настройки)"""

    @staticmethod
    def run_recalculation(branch_id=None):
        """
        Запускает пересчет RF-метрик.
        Если branch_id передан - только для одного, иначе для всех.
        """
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
                # Предполагаем, что RFCalculator.run_analysis() существует
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
        """
        Обновляет настройки RF: период анализа и пороги сегментов.
        """
        with transaction.atomic():
            branch = get_object_or_404(Branch, id=branch_id)
            
            # 1. Обновляем настройки периода
            period = settings_data.get('analysis_period', 365)
            RFSettings.objects.update_or_create(
                branch=branch, 
                defaults={'analysis_period': period}
            )

            # 2. Обновляем пороги сегментов
            # ВАЖНО: Это меняет глобальные настройки сегментов для схемы тенанта
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
                
                # Логика Recency
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

                # Логика Frequency
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
        """
        Расчет Sankey диаграммы и показателей Growth/Churn
        """
        start_date = now() - timedelta(days=days)
        
        # Базовый QuerySet
        logs_qs = RFMigrationLog.objects.filter(
            client__branch=branch,
            migrated_at__gte=start_date
        ).select_related('from_segment', 'to_segment')

        # Фильтрация по конкретному сегменту (Вход или Выход)
        if segment_code:
            logs_qs = logs_qs.filter(
                Q(from_segment__code=segment_code) | 
                Q(to_segment__code=segment_code)
            )

        # Агрегация потоков для Sankey
        flow_stats = logs_qs.values(
            'from_segment__name', 'from_segment__emoji', 'from_segment__code',
            'to_segment__name', 'to_segment__emoji', 'to_segment__code'
        ).annotate(count=Count('id')).order_by('-count')

        # Формирование данных для диаграммы Sankey
        sankey_data = []
        for f in flow_stats:
            source = f"{f.get('from_segment__emoji', '')} {f.get('from_segment__name', 'Unknown')}"
            target = f"{f.get('to_segment__emoji', '')} {f.get('to_segment__name', 'Unknown')}"
            sankey_data.append([source, target, f['count']])

        # Расчет KPI
        # ВАЖНО: Сравнение строк кодов работает корректно только если формат фиксирован (R1 < R3).
        # Если появятся R10, логику нужно менять на парсинг чисел.
        growth = logs_qs.filter(to_segment__code__gt=F('from_segment__code')).count()
        
        # Тех кто "упал"
        drops_qs = logs_qs.filter(to_segment__code__lt=F('from_segment__code'))
        
        real_churn = logs_qs.filter(to_segment__code__startswith='R0').count()
        natural_cooling = drops_qs.exclude(to_segment__code__startswith='R0').count()
        
        reactivation = logs_qs.filter(
            from_segment__code__startswith='R0', 
            to_segment__code__gt='R0'
        ).count()

        # Retention Rate Calculation
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
        """Получает список недавних гостей с их историей"""
        start_date = now() - timedelta(days=days)
        
        # Получаем уникальные ID последних мигрировавших
        unique_ids = list(RFMigrationLog.objects.filter(
            client__branch=branch,
            migrated_at__gte=start_date
        ).order_by('-migrated_at').values_list('client_id', flat=True).distinct()[:limit])

        if not unique_ids:
            return []

        # Загружаем текущие скоры
        scores = GuestRFScore.objects.filter(
            client_id__in=unique_ids
        ).select_related('client__client', 'segment')

        # Загружаем историю (оптимизация: загружаем сразу для всех и мапим в Python)
        all_logs = RFMigrationLog.objects.filter(
            client_id__in=unique_ids
        ).select_related('from_segment', 'to_segment').order_by('-migrated_at')

        # Группировка логов по клиенту
        logs_by_client = {}
        for log in all_logs:
            if log.client_id not in logs_by_client:
                logs_by_client[log.client_id] = []
            if len(logs_by_client[log.client_id]) < 3: # Только последние 3
                logs_by_client[log.client_id].append(log)

        result = []
        for s in scores:
            result.append({
                'info': s.client, # ClientBranch
                'current': s,     # GuestRFScore
                'history': logs_by_client.get(s.client_id, [])
            })
        
        return result

class RFGuestService:
    """Сервис для получения данных о гостях в сегментах"""

    @staticmethod
    def get_guests_by_segment(branch_id, segment_code):
        branch = get_object_or_404(Branch, id=branch_id)
        segment = get_object_or_404(RFSegment, code=segment_code)

        # Оптимизированный запрос с аннотацией последней даты
        # Мы избегаем цикла запросов к client_attempt
        guests = GuestRFScore.objects.filter(
            client__branch=branch, 
            segment=segment
        ).select_related(
            'client__client'
        ).annotate(
            last_visit_date=Max('client__client_attempt__created_on')
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
            pass # Логирование ошибки можно добавить здесь
            
        return None