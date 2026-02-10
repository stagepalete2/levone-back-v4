from django.urls import path

from apps.tenant.inventory.api.views import InventoryView, SuperPrizeInventoryView, InventoryCooldownView, InventoryActivateView

urlpatterns = [
    path('inventory/', InventoryView.as_view(), name='prizes'),
    path('super-prize/', SuperPrizeInventoryView.as_view(), name='superprizes'),
	path('inventory/cooldown/', InventoryCooldownView.as_view(), name='cooldown'),
	path('inventory/activate/', InventoryActivateView.as_view(), name='activate')
]

