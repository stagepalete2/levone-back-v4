from rest_framework import serializers
from apps.tenant.inventory.models import SuperPrize

from apps.tenant.game.models import Cooldown
from apps.tenant.catalog.models import Product
from apps.tenant.catalog.api.serializers import CatalogResponseSerializer

from rest_framework import serializers

class GamePlayRequestSerializer(serializers.Serializer):
    """Валидация входящих параметров игры"""
    vk_user_id = serializers.IntegerField(required=True)
    branch_id = serializers.IntegerField(required=True)
    code = serializers.CharField(required=False, allow_blank=True) # Код дня
    
    # ИСПРАВЛЕНИЕ: Убрали allow_blank=True
    employee_id = serializers.IntegerField(required=False, allow_null=True) 
    
    delivery_code = serializers.CharField(required=False, allow_blank=True) # Код доставки
    
class GameRewardSerializer(serializers.Serializer):
    """
    Универсальный ответ.
    type: 'coin' | 'prize' | 'code_required'
    reward: число (монеты) или объект (Inventory)
    """
    type = serializers.ChoiceField(choices=['coin', 'prize', 'code'])
    reward = serializers.JSONField(required=False)

class SuperPrizeSerializer(serializers.ModelSerializer):
    """Сериализатор для супер-приза (Inventory)"""
    prizes = serializers.SerializerMethodField()

    class Meta:
        model = SuperPrize
        fields = ['id', 'client', 'acquired_from', 'prizes']
    
    def get_prizes(self, instance):
        prizes = Product.objects.filter(branch=instance.client.branch, is_super_prize=True).order_by('-created_at')[:4]
        serializer = CatalogResponseSerializer(prizes, many=True)
        return serializer.data


class GameCooldownRequestSerializer(serializers.Serializer):
    """
    Валидация параметров (vk_user_id, branch).
    """
    vk_user_id = serializers.IntegerField(required=True)
    branch_id = serializers.IntegerField(required=True)

class GameCooldownResponseSerializer(serializers.ModelSerializer):
    """
    Сериализатор состояния игровой перезарядки.
    """
    time_left_seconds = serializers.SerializerMethodField()
    
    class Meta:
        model = Cooldown
        fields = [
            'is_active',         # property модели
            'time_left_seconds', # вычисляемое поле
            'last_activated_at',
            'duration'
        ]

    def get_time_left_seconds(self, instance):
        return int(instance.time_left.total_seconds())