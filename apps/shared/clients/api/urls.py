from django.urls import path

from apps.shared.clients.api.views import GetDomain, SharedDeliveryWebhookView

urlpatterns = [
    path('company/', GetDomain.as_view(), name='get-domain'),
    path('delivery/webhook/', SharedDeliveryWebhookView.as_view(), name='shared-delivery-webhook'),
]
