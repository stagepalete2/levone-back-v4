import json
from datetime import timedelta
from django.utils import timezone
from django.db.models import Count, Max
from collections import defaultdict

from apps.tenant.delivery.models import Delivery
from apps.tenant.stats.models import RFSegment
from apps.tenant.branch.models import ClientBranch


class DeliveryRFService:
    """Сервис для RFM-аналитики доставки"""

    @staticmethod
    def get_matrix_data():
        """
        Подготавливает данные для RF-матрицы на основе активаций доставки.
        Frequency = количество активаций QR-кодов
        Recency = дней с последней активации
        """
        now = timezone.now()
        
        # Получаем всех клиентов с активациями
        clients_with_activations = Delivery.objects.filter(
            activated_by__isnull=False
        ).values('activated_by').annotate(
            frequency=Count('id'),
            last_activation=Max('created_at')
        )
        
        # Получаем все сегменты
        segments = list(RFSegment.objects.all())
        segment_counts = defaultdict(int)
        
        # Распределяем клиентов по сегментам
        for client_data in clients_with_activations:
            frequency = client_data['frequency']
            last_activation = client_data['last_activation']
            recency_days = (now - last_activation).days if last_activation else 999
            
            # Находим подходящий сегмент
            for segment in segments:
                if (segment.recency_min <= recency_days <= segment.recency_max and
                    segment.frequency_min <= frequency <= segment.frequency_max):
                    segment_counts[segment.code] += 1
                    break
        
        # Добавляем guest_count к каждому сегменту
        segments_with_counts = []
        total_guests = 0
        vip_count = 0
        at_risk_count = 0
        lost_count = 0
        
        for segment in segments:
            count = segment_counts.get(segment.code, 0)
            total_guests += count
            
            # KPI подсчет
            if segment.code.endswith('F3'):
                vip_count += count
            if segment.code.startswith('R1'):
                at_risk_count += count
            if segment.code.startswith('R0'):
                lost_count += count
            
            segments_with_counts.append({
                'code': segment.code,
                'name': segment.name,
                'emoji': segment.emoji,
                'color': segment.color,
                'strategy': segment.strategy,
                'guests_count': count,
                'recency_min': segment.recency_min,
                'recency_max': segment.recency_max,
                'frequency_min': segment.frequency_min,
                'frequency_max': segment.frequency_max,
            })
        
        # Сортировка: R3F1, R3F2, R3F3, R2F1...
        def sort_key(seg):
            code = seg['code']
            r_part = code[:2] if len(code) >= 2 else 'R0'
            f_part = code[2:] if len(code) >= 4 else 'F1'
            r_order = {'R3': 0, 'R2': 1, 'R1': 2, 'R0': 3}
            f_order = {'F1': 0, 'F2': 1, 'F3': 2}
            return (r_order.get(r_part, 99), f_order.get(f_part, 99))
        
        segments_with_counts.sort(key=sort_key)
        
        return {
            'segments': segments_with_counts,
            'total_activations': Delivery.objects.filter(activated_by__isnull=False).count(),
            'unique_clients': clients_with_activations.count(),
            'last_update': now,
            'kpi': {
                'vip': vip_count,
                'at_risk': at_risk_count,
                'lost': lost_count,
            }
        }

    @staticmethod
    def get_segment_ranges(segments):
        """Извлекает примеры сегментов для заголовков таблицы"""
        ranges = {
            'f1': None, 'f2': None, 'f3': None,
            'r3': None, 'r2': None, 'r1': None, 'r0': None
        }
        
        for seg in segments:
            code = seg['code']
            
            if code == 'R3F1':
                ranges['f1'] = seg
                ranges['r3'] = seg
            elif code == 'R3F2':
                ranges['f2'] = seg
            elif code == 'R3F3':
                ranges['f3'] = seg
            elif code == 'R2F1':
                ranges['r2'] = seg
            elif code == 'R1F1':
                ranges['r1'] = seg
            elif code == 'R0F1':
                ranges['r0'] = seg
        
        return ranges

    @staticmethod
    def get_migration_stats(days=30, segment_code=None):
        """
        Подсчёт миграций клиентов между сегментами.
        Упрощённая версия - показывает только текущее распределение.
        """
        now = timezone.now()
        start_date = now - timedelta(days=days)
        
        # Получаем активации за период
        activations = Delivery.objects.filter(
            activated_by__isnull=False,
            created_at__gte=start_date
        ).values('activated_by').annotate(
            count=Count('id')
        )
        
        # Sankey данные (упрощённо - показываем поток в сегменты)
        sankey_data = []
        segments = list(RFSegment.objects.all())
        
        flow_to_segment = defaultdict(int)
        for activation in activations:
            frequency = activation['count']
            # Определяем F-сегмент
            for seg in segments:
                if seg.frequency_min <= frequency <= seg.frequency_max:
                    flow_to_segment[seg.code] += 1
                    break
        
        for seg_code, count in flow_to_segment.items():
            if count > 0:
                sankey_data.append(['Новые активации', seg_code, count])
        
        # KPI
        total = activations.count()
        
        return {
            'sankey_data': json.dumps(sankey_data),
            'flow_stats': [],
            'kpi': {
                'growth': total,
                'real_churn': 0,
                'natural_cooling': 0,
                'reactivation': 0,
            },
            'recent_guests': [],
        }
