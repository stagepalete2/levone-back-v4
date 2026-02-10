from django.urls import path
from .views import DeliveryCodeView, DeliveryWebhook

urlpatterns = [
	path('webhook/', DeliveryWebhook.as_view(), name='webhook'),
    path('code/', DeliveryCodeView.as_view(), name='delivery-code'),
]