from django.contrib import admin
from django_tenants.utils import tenant_context, get_tenant_model, get_tenant_domain_model
from django.utils import timezone

class PublicAdminSite(admin.AdminSite):
    site_header = "Levelup.ru - Панель супер-администратора"
    site_title = "Levelup"
    index_template = 'admin/public/index.html'

    def has_permission(self, request):
        return (
            request.user.is_active
            and request.user.is_staff
            and request.tenant.schema_name == 'public'
        ) or (
            request.user.is_active
            and request.user.is_staff
            and request.user.is_superuser
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

        # Глобальный суперпользователь без привязки к компании — полный доступ
        if user.is_superuser and not user.company_id:
            return True

        current_tenant_id = request.tenant.id

        # Проверяем основной (FK) тенант
        if user.company_id and user.company_id == current_tenant_id:
            return True

        # Проверяем список доступных тенантов (M2M)
        if user.companies.filter(pk=current_tenant_id).exists():
            return True

        return False

    def index(self, request, extra_context=None):
        extra_context = extra_context or {}
    
        if getattr(request.tenant, 'schema_name', None) == 'public':
            return super().index(request, extra_context=extra_context)
        
        from apps.tenant.branch.models import Branch
        from apps.tenant.game.models import DailyCode as GameDailyCodes
        from apps.tenant.quest.models import DailyCode as QuestDailyCodes
        from apps.tenant.branch.models import DailyCode as BirthdayDailyCodes
        from apps.shared.config.utils import generate_code
        
        extra_context = extra_context or {}
        today = timezone.localdate()
        branch_codes = []

        branches = Branch.objects.all()
        
        for branch in branches:
            # Автогенерация кодов если не были созданы (фикс бага с celery)
            game_code_obj, _ = GameDailyCodes.objects.get_or_create(
                date=today, branch=branch,
                defaults={"code": generate_code()}
            )
            quest_code_obj, _ = QuestDailyCodes.objects.get_or_create(
                date=today, branch=branch,
                defaults={"code": generate_code()}
            )
            birthday_code_obj, _ = BirthdayDailyCodes.objects.get_or_create(
                date=today, branch=branch,
                defaults={"code": generate_code()}
            )

            branch_codes.append({
                "branch": branch.name,
                "game_code": game_code_obj.code,
                "quest_code": quest_code_obj.code,
                "birthday_code": birthday_code_obj.code,
            })
        
        extra_context['today'] = today
        extra_context['branch_codes'] = branch_codes
        # Передаём флаг наличия права просмотра статистики в шаблон
        extra_context['can_view_stats'] = (
            request.user.is_superuser
            or request.user.has_perm('users.can_view_stats')
        )
        return super().index(request, extra_context=extra_context)
    
    class Media:
        js = ('admin/js/admin_sidebar_fix.js',)



public_admin = PublicAdminSite(name='public_admin')
tenant_admin = TenantAdminSite(name='tenant_admin')

