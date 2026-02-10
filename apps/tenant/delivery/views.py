from django.views.generic import TemplateView
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied

from apps.shared.config.sites import tenant_admin
from apps.tenant.delivery.models import Delivery
from apps.tenant.delivery.core import DeliveryRFService
from apps.tenant.stats.models import RFSegment


class BaseAdminDeliveryView(LoginRequiredMixin, UserPassesTestMixin):
    """Базовый класс для проверки прав доступа"""
    login_url = '/admin/login/'
    redirect_field_name = 'next'

    def test_func(self):
        return self.request.user.is_superuser or self.request.user.is_staff

    def handle_no_permission(self):
        raise PermissionDenied("Доступ к статистике запрещен")
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(tenant_admin.each_context(self.request))
        return context


class DeliveryRFAnalyticsView(BaseAdminDeliveryView, TemplateView):
    """Матрица RFM для доставки"""
    template_name = 'delivery_rfm/statistics.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Получаем статистику через сервис
        matrix_data = DeliveryRFService.get_matrix_data()
        ranges = DeliveryRFService.get_segment_ranges(matrix_data['segments'])
        
        context.update({
            'segments': matrix_data['segments'],
            'total_activations': matrix_data['total_activations'],
            'unique_clients': matrix_data['unique_clients'],
            'last_update': matrix_data['last_update'],
            
            'vip_count': matrix_data['kpi']['vip'],
            'at_risk_count': matrix_data['kpi']['at_risk'],
            'lost_count': matrix_data['kpi']['lost'],
            
            'f1_range': ranges['f1'], 
            'f2_range': ranges['f2'], 
            'f3_range': ranges['f3'],
            'r3_range': ranges['r3'], 
            'r2_range': ranges['r2'], 
            'r1_range': ranges['r1'], 
            'r0_range': ranges['r0'],
        })
        return context


class DeliveryRFMigrationView(BaseAdminDeliveryView, TemplateView):
    """История миграций для доставки"""
    template_name = 'delivery_rfm/migration.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Получаем период из параметров
        days = int(self.request.GET.get('days', 30))
        segment_code = self.request.GET.get('segment', '')
        
        # Получаем данные миграций
        stats = DeliveryRFService.get_migration_stats(days=days, segment_code=segment_code)
        
        context.update({
            'sankey_data': stats['sankey_data'],
            'flow_stats': stats.get('flow_stats', []),
            
            'growth_count': stats['kpi']['growth'],
            'real_churn_count': stats['kpi']['real_churn'],
            'natural_cooling_count': stats['kpi']['natural_cooling'],
            'reactivation_count': stats['kpi']['reactivation'],
            
            'recent_guests': stats.get('recent_guests', []),
            'all_segments': RFSegment.objects.all().order_by('-code'),
            'days': days,
            'selected_segment': segment_code,
        })
        return context
