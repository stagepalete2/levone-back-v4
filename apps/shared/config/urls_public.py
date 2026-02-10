from django.urls import path, include
from django.conf.urls.static import static
from apps.shared.config.sites import public_admin
from django.conf.urls.static import static
from django.conf import settings

urlpatterns = [
	path('admin/', public_admin.urls),
	path('api/v1/', include('apps.shared.clients.api.urls'))
] 

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT) 