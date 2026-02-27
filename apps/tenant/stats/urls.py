# stats.urls.py

from django.urls import path

from apps.tenant.stats.views import (
    StatisticsView, StatisticsDetailView, AwayView,
    ReviewsListView, ReviewReplyView,
    RFAnalyticsView, RFAnalyticsDetailView,
    RFGuestMigrationAnalyticsDetailView, RFRecalculateView, RFSettingsSaveView, RFGetSegmentGuest,
    RFSegmentMailingView, RFStatsResetView,
)

urlpatterns = [
	path("statistics/", StatisticsView.as_view(), name="admin-statistics"),
    path('statistics/<slug:stat_name>/', StatisticsDetailView.as_view(), name='admin-statistics-detail'),
    path("away/<int:vk_user_id>/", AwayView.as_view(), name="away"),

    # Reviews
    path("reviews/", ReviewsListView.as_view(), name="admin-reviews-list"),
    path("reviews/reply/", ReviewReplyView.as_view(), name="admin-review-reply"),

    path('rf/', RFAnalyticsView.as_view(), name='rf-statistics'),
    path('rf/<int:id>/', RFAnalyticsDetailView.as_view(), name='rf-detail-statistics'),
	path('rf/<int:id>/migration/', RFGuestMigrationAnalyticsDetailView.as_view(), name='rf-migration-statistics'),

    path('api/v1/rf/recalculate/', RFRecalculateView.as_view(), name='rf-recalculate'),
    path('api/v1/rf/save-settings/', RFSettingsSaveView.as_view(), name='rf-settings-save'),
    path('api/v1/rf/segment-guest/<str:segment_code>/', RFGetSegmentGuest.as_view(), name='rf-segment-guests'),
    path('api/v1/rf/segment-mailing/', RFSegmentMailingView.as_view(), name='rf-segment-mailing'),
    # Обнуление статистики (не трогает балансы)
    path('api/v1/rf/reset-stats/', RFStatsResetView.as_view(), name='rf-stats-reset'),
]