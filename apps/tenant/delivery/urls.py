from django.urls import path
from apps.tenant.delivery.views import (
    DeliveryRFAnalyticsView, 
    DeliveryRFMigrationView
)

urlpatterns = [
    path('delivery/rf/', DeliveryRFAnalyticsView.as_view(), name='delivery-rf-statistics'),
    path('delivery/rf/migration/', DeliveryRFMigrationView.as_view(), name='delivery-rf-migration'),
]
