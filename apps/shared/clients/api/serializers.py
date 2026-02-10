from rest_framework import serializers

from apps.shared.clients.models import Company

class DomainRequestSerializer(serializers.Serializer):
    """Валидация входящих параметров (Query Params)"""
    company = serializers.PrimaryKeyRelatedField(
        queryset=Company.objects.all(),
        required=True
    )

class DomainResponseSerializer(serializers.Serializer):
    """Формирование красивого ответа"""
    company_id = serializers.IntegerField(source='tenant.id')
    domain = serializers.CharField()
    is_active = serializers.BooleanField(source='tenant.is_active')

    group_id = serializers.CharField(source='tenant.config.vk_group_id', allow_null=True, default=None)
    group_name = serializers.CharField(source='tenant.config.vk_group_name', allow_null=True, default=None)