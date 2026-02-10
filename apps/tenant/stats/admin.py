from django.contrib import admin

from apps.shared.config.sites import tenant_admin
from apps.shared.config.mixins import BranchRestrictedAdminMixin
from apps.tenant.stats.models import RFSegment, RFSettings, GuestRFScore, RFMigrationLog, BranchSegmentSnapshot


class RFSegmentAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'emoji', 'recency_min', 'recency_max', 'frequency_min', 'frequency_max', 'color')
    list_filter = ('code',)
    search_fields = ('name', 'code')


class RFSettingsAdmin(BranchRestrictedAdminMixin, admin.ModelAdmin):
    list_display = ('branch', 'analysis_period')
    list_filter = ('branch',)


class GuestRFScoreAdmin(BranchRestrictedAdminMixin, admin.ModelAdmin):
    client_branch_field_name = 'client'
    branch_field_name = None

    list_display = ('client', 'segment', 'recency_days', 'frequency', 'r_score', 'f_score', 'calculated_at')
    list_filter = ('segment', 'client__branch')
    search_fields = ('client__client__name', 'client__client__lastname')
    readonly_fields = ('calculated_at',)

    def get_queryset(self, request):
        qs = super(admin.ModelAdmin, self).get_queryset(request)
        user = request.user
        if user.is_superuser:
            return qs
        if hasattr(user, 'tenant_profile'):
            user_branches = user.tenant_profile.branches.all()
            if user_branches.exists():
                return qs.filter(client__branch__in=user_branches)
        return qs


class BranchSegmentSnapshotAdmin(BranchRestrictedAdminMixin, admin.ModelAdmin):
    list_display = ('branch', 'segment', 'guests_count', 'date', 'updated_at')
    list_filter = ('branch', 'segment', 'date')
    readonly_fields = ('date', 'updated_at')


tenant_admin.register(RFSegment, RFSegmentAdmin)
tenant_admin.register(RFSettings, RFSettingsAdmin)
tenant_admin.register(GuestRFScore, GuestRFScoreAdmin)
tenant_admin.register(BranchSegmentSnapshot, BranchSegmentSnapshotAdmin)
