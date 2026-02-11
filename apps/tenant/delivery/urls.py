from django.urls import path
from apps.tenant.delivery.views import (
    DeliveryRFAnalyticsView, 
    DeliveryRFMigrationView
)

urlpatterns = [
    # Добавляем <int:id> для идентификации филиала
    path('branch/<int:id>/delivery/rf/', DeliveryRFAnalyticsView.as_view(), name='delivery-rf-statistics'),
    path('branch/<int:id>/delivery/rf/migration/', DeliveryRFMigrationView.as_view(), name='delivery-rf-migration'),
]