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

        if user.is_superuser and not user.company_id:
            return True

        if not user.company_id:
            return False

        if user.company_id != request.tenant.id:
            return False

        return True

    def index(self, request, extra_context=None):
        extra_context = extra_context or {}
    
        if getattr(request.tenant, 'schema_name', None) == 'public':
            return super().index(request, extra_context=extra_context)
        
        from apps.tenant.branch.models import Branch
        from apps.tenant.game.models import DailyCode as GameDailyCodes
        from apps.tenant.quest.models import DailyCode as QuestDailyCodes
        from apps.tenant.branch.models import DailyCode as BirthdayDailyCodes
        
        extra_context = extra_context or {}
        today = timezone.localdate()
        branch_codes = []

        branches = Branch.objects.all()
        
        for branch in branches:
            game_code = GameDailyCodes.objects.filter(date=today, branch=branch).first()
            quest_code = QuestDailyCodes.objects.filter(date=today, branch=branch).first()
            birthday_code = BirthdayDailyCodes.objects.filter(date=today, branch=branch).first()

            branch_codes.append({
                "branch": branch.name,
                "game_code": game_code.code if game_code else "Не сгенерирован",
                "quest_code": quest_code.code if quest_code else "Не сгенерирован",
                "birthday_code" : birthday_code.code if birthday_code else 'Не сгенерирован',
            })
        
        extra_context['today'] = today
        extra_context['branch_codes'] = branch_codes
        return super().index(request, extra_context=extra_context)
    
    class Media:
        js = ('admin/js/admin_sidebar_fix.js',)



public_admin = PublicAdminSite(name='public_admin')
tenant_admin = TenantAdminSite(name='tenant_admin')
