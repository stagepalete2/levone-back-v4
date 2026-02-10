from django.contrib import admin
from django_tenants.utils import tenant_context, get_tenant_model, get_tenant_domain_model


class PublicAdminSite(admin.AdminSite):
    site_header = "Levelup.ru - Панель супер-администратора"
    site_title = "Levelup"
    index_template = 'admin/public/index.html'

    def has_permission(self, request):
        return (
            request.user.is_active
            and request.user.is_staff
            and request.user.is_superuser
            and request.tenant.schema_name == 'public'
        )

    def index(self, request, extra_context=None):
        TenantModel = get_tenant_model()
        DomainModel = get_tenant_domain_model()

        tenants_qs = TenantModel.objects.exclude(schema_name='public')
        extra_context = extra_context or {}
        tenant_data = []

        for tenant in tenants_qs:
            domain = DomainModel.objects.filter(tenant=tenant, is_primary=True).first()
            if not domain:
                domain = DomainModel.objects.filter(tenant=tenant).first()

            with tenant_context(tenant):
                tenant_data.append({
                    'tenant': tenant,
                    'domain': domain.domain if domain else "No domain",
                })

        extra_context['tenants'] = tenant_data
        return super().index(request, extra_context=extra_context)


class TenantAdminSite(admin.AdminSite):
    index_template = 'admin/tenant/index.html'
    site_header = "Levelup - Панель администратора"
    site_title = "Levelup"

    def has_permission(self, request):
        user = request.user
        if not user.is_active or not user.is_staff:
            return False

        # Глобальный суперюзер платформы (без привязки к компании) — может заходить везде
        if user.is_superuser and not user.company_id:
            return True

        # Пользователь должен быть привязан к компании
        if not user.company_id:
            return False

        # Обычный админ компании может заходить ТОЛЬКО в свой тенант
        if user.company_id != request.tenant.id:
            return False

        return True

    def index(self, request, extra_context=None):
        extra_context = extra_context or {}
        return super().index(request, extra_context=extra_context)


public_admin = PublicAdminSite(name='public_admin')
tenant_admin = TenantAdminSite(name='tenant_admin')
