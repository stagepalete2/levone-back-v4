from rest_framework import serializers

from apps.tenant.catalog.models import Product, Cooldown
from apps.tenant.inventory.models import Inventory

class CatalogRequestSerializer(serializers.Serializer):
    """
    Валидация входящих параметров (Query Params).
    """
    branch_id = serializers.IntegerField(required=True)


class CatalogResponseSerializer(serializers.ModelSerializer):
    """
    Сериализатор товара.
    Возвращает полные пути к картинкам.
    """
    image = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            'id', 
            'name', 
            'description', 
            'image', 
            'price', 
            'is_super_prize'
        ]

    def get_image(self, instance):
        if instance.image:
            try:
                # Строим полный URL (https://domain.com/media/...)
                request = self.context.get('request')
                return request.build_absolute_uri(instance.image.url)
            except Exception:
                # Если контекста нет, возвращаем относительный путь
                return instance.image.url
        return None


class CooldownRequestSerializer(serializers.Serializer):
    """
    Валидация входящих параметров (vk_user_id, branch_id).
    """
    vk_user_id = serializers.IntegerField(required=True)
    branch_id = serializers.IntegerField(required=True)

class CooldownResponseSerializer(serializers.ModelSerializer):
    """
    Сериализатор состояния перезарядки.
    """
    # Превращаем timedelta в понятные секунды (Int)
    time_left_seconds = serializers.SerializerMethodField()
    
    class Meta:
        model = Cooldown
        fields = [
            'is_active',         # property из модели
            'time_left_seconds', # вычисляемое поле
            'last_activated_at'
        ]

    def get_time_left_seconds(self, instance):
        # time_left - это property модели, возвращающая timedelta
        return int(instance.time_left.total_seconds())


class BuyRequestSerializer(serializers.Serializer):
    """
    Валидация входящих данных для покупки.
    """
    vk_user_id = serializers.IntegerField(required=True)
    branch_id = serializers.IntegerField(required=True)
    product_id = serializers.IntegerField(required=True)


class BuyResponseSerializer(serializers.ModelSerializer):
    """
    Сериализатор предмета в инвентаре.
    """
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_image = serializers.SerializerMethodField()
    price = serializers.IntegerField(source='product.price', read_only=True)
    
    # Поля свойств из модели
    status = serializers.CharField(read_only=True)          # 'IN_STOCK' и т.д.
    status_display = serializers.CharField(source='get_status_display', read_only=True) # 'В инвентаре'
    
    class Meta:
        model = Inventory
        fields = [
            'id', 
            'product',          # ID продукта
            'product_name',     # Название (удобно для фронта)
            'product_image',    # Картинка (удобно для фронта)
            'acquired_from',
            'status',
            'price',
            'status_display',
            'activated_at',
            'created_at'        # От TimeStampedModel
        ]

    def get_product_image(self, instance):
        if instance.product.image:
            try:
                request = self.context.get('request')
                return request.build_absolute_uri(instance.product.image.url)
            except Exception:
                return instance.product.image.url
        return None