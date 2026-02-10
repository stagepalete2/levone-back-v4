from django.urls import path

from apps.tenant.branch.api.views import BranchInfoView, ClientView, ReviewView, TransactionsView, EmployeeView, PromotionView

urlpatterns = [
	path('branch/', BranchInfoView.as_view(), name='branches'),
	path('client/', ClientView.as_view(), name='clients'),
	path('review/', ReviewView.as_view(), name='review'),
	path('transactions/', TransactionsView.as_view(), name='transactions'),
	path('employees/', EmployeeView.as_view(), name='employees'),
	path('promotions/', PromotionView.as_view(), name='promotions')
]