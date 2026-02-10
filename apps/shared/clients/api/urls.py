from django.urls import path

from apps.shared.clients.api.views import GetDomain

urlpatterns = [
	path('company/', GetDomain.as_view(), name='get-domain')
]