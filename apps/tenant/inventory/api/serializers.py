from rest_framework import serializers
from django.utils import timezone

from apps.tenant.inventory.models import Inventory, SuperPrize, Cooldown
from apps.tenant.catalog.models import Product
from apps.tenant.catalog.api.serializers import CatalogResponseSerializer

# --- REQUEST SERIALIZERS ---

class InventoryRequestSerializer(serializers.Serializer):
    """Базовая валидация vk_user_id и branch_id"""
    vk_user_id = serializers.IntegerField(required=True)
    branch_id = serializers.IntegerField(required=True)

class SuperPrizeClaimSerializer(serializers.Serializer):
    """Валидация выбора супер-приза"""
    vk_user_id = serializers.IntegerField(required=True)
    branch_id = serializers.IntegerField(required=True)
    product_id = serializers.IntegerField(required=True)

# Alias — тот же формат подходит для ДР приза
BirthdayPrizeClaimSerializer = SuperPrizeClaimSerializer

class InventoryActivateSerializer(serializers.Serializer):
    """Валидация активации предмета"""
    vk_user_id = serializers.IntegerField(required=True)
    branch_id = serializers.IntegerField(required=True)
    inventory_id = serializers.IntegerField(required=True)

# --- RESPONSE SERIALIZERS ---

class InventorySerializer(serializers.ModelSerializer):
    """Отображение предмета инвентаря"""
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_image = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    is_birthday_prize = serializers.BooleanField(source='product.is_birthday_prize', read_only=True)

    class Meta:
        model = Inventory
        fields = [
            'id',
            'product',
            'product_name',
            'product_image',
            'acquired_from',
            'is_birthday_prize',
            'status',
            'status_display',
            'activated_at',
            'created_at',
            'duration'
        ]

    def get_product_image(self, instance):
        if instance.product.image:
            try:
                request = self.context.get('request')
                return request.build_absolute_uri(instance.product.image.url)
            except Exception:
                return instance.product.image.url
        return None

class SuperPrizeSerializer(serializers.ModelSerializer):
    """Отображение неактивированного обычного супер-приза"""
    prizes = serializers.SerializerMethodField()

    class Meta:
        model = SuperPrize
        fields = ['id', 'client', 'acquired_from', 'is_used', 'prizes']

    def get_prizes(self, instance):
        prizes = Product.objects.filter(
            branch=instance.client.branch,
            is_super_prize=True,
            is_active=True,
        ).order_by('-created_at')[:4]
        serializer = CatalogResponseSerializer(prizes, many=True, context={'request': self.context.get('request')})
        return serializer.data


class BirthdayStatusSerializer(serializers.Serializer):
    """Ответ о статусе ДР режима"""
    is_birthday_mode = serializers.BooleanField()
    has_pending_prize = serializers.BooleanField()


class InventoryCooldownSerializer(serializers.ModelSerializer):
    time_left_seconds = serializers.SerializerMethodField()

    class Meta:
        model = Cooldown
        fields = ['is_active', 'time_left_seconds', 'last_activated_at']

    def get_time_left_seconds(self, instance):
        return int(instance.time_left.total_seconds())