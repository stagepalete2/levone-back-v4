
from django.urls import path

from apps.tenant.catalog.api.views import CatalogView, CooldownView, BuyView

urlpatterns = [
	path('catalog/', CatalogView.as_view(), name='catalog'),
	path('catalog/cooldown/', CooldownView.as_view(), name='cooldown'),
	path('catalog/buy/', BuyView.as_view(), name='buy'),
]