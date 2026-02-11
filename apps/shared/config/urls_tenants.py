# urls_tenants.py

from django.urls import path, include
from apps.shared.config.sites import tenant_admin
from django.conf.urls.static import static
from django.conf import settings

urlpatterns = [
    path('admin/', tenant_admin.urls),
	path('api/v1/', include('apps.tenant.branch.api.urls')),
	path('api/v1/', include('apps.tenant.catalog.api.urls')),
	path('api/v1/', include('apps.tenant.inventory.api.urls')),
	path('api/v1/', include('apps.tenant.quest.api.urls')),
	path('api/v1/', include('apps.tenant.game.api.urls')),

	path('analytics/', include('apps.tenant.stats.urls')),
	path('analytics/', include('apps.tenant.delivery.urls')),
    
	path('admin-tools/', include('apps.tenant.branch.urls')),

	path('api/v1/', include('apps.tenant.delivery.api.urls')),
]


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    # Обычно для STATIC_URL это не нужно, если включен 'django.contrib.staticfiles', 
    # но если нужно явно раздавать собранную статику:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)