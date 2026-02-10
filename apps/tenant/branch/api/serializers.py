from rest_framework import serializers

from apps.shared.guest.models import Client
from apps.tenant.branch.models import Branch, StoryImage, ClientBranch, CoinTransaction, Promotions

class BranchInfoRequestSerializer(serializers.Serializer):
    """
    Валидация входящего параметра branch_id.
    """
    branch_id = serializers.IntegerField(required=True)


class BranchInfoResponseSerializer(serializers.ModelSerializer):
    """
    Формирование красивого ответа.
    Данные собираются из самой Branch, связанной Config и StoryImage.
    """
    yandex_map = serializers.SerializerMethodField()
    gis_map = serializers.SerializerMethodField()
    
    story = serializers.SerializerMethodField()

    logotype_image = serializers.ImageField(source='tenant.config.logotype_image',  allow_null=True, default=None)
    coin_image = serializers.ImageField(source='tenant.config.coin_image',  allow_null=True, default=None)

    class Meta:
        model = Branch
        fields = [
            'id', 
            'name', 
            'description', 
            'yandex_map', 
            'gis_map', 
            'story',
            'logotype_image',
            'coin_image'
        ]

    def get_yandex_map(self, instance):
        if hasattr(instance, 'config'):
            return instance.config.yandex_map
        return None

    def get_gis_map(self, instance):
        if hasattr(instance, 'config'):
            return instance.config.gis_map
        return None

    def get_story(self, instance):
        latest_story = StoryImage.objects.filter(branch=instance).order_by('-created_at').first()
        
        if latest_story and latest_story.image:
            try:
                request = self.context.get('request')
                return request.build_absolute_uri(latest_story.image.url)
            except Exception:
                return latest_story.image.url
        return None



class ClientGetRequestSerializer(serializers.Serializer):
    """Валидация параметров для GET запроса"""
    vk_user_id = serializers.IntegerField(required=True)
    branch_id = serializers.IntegerField(required=True)

class ClientRegistrationSerializer(serializers.Serializer):
    """Валидация данных для регистрации/обновления (POST)"""
    vk_user_id = serializers.IntegerField(required=True)
    branch_id = serializers.IntegerField(required=True)
    
    # Поля профиля
    name = serializers.CharField(required=False, allow_blank=True)
    lastname = serializers.CharField(required=False, allow_blank=True)
    sex = serializers.IntegerField(required=False, allow_null=True)
    birth_date = serializers.DateField(required=False, allow_null=True)
    # Сюда можно добавить аватарку и другие поля BaseClient

class ClientUpdateRequestSerializer(serializers.ModelSerializer):
    """
    Валидация для PATCH.
    Запрещаем менять баланс и привязку к ветке через API.
    """
    vk_user_id = serializers.IntegerField(write_only=True, required=True)
    branch_id = serializers.IntegerField(write_only=True, required=True)

    class Meta:
        model = ClientBranch
        fields = [
            'vk_user_id', 'branch_id', 
            'is_story_uploaded', 'is_joined_community', 
            'is_allowed_message', 'birth_date',
            'invited_by'
        ]


class ClientProfileResponseSerializer(serializers.ModelSerializer):
    """
    Полный профиль клиента для фронтенда.
    Объединяет данные ClientBranch и BaseClient.
    """
    # Данные из BaseClient (flat structure)
    vk_user_id = serializers.IntegerField(source='client.vk_user_id')
    name = serializers.CharField(source='client.name')
    lastname = serializers.CharField(source='client.lastname')
    sex = serializers.IntegerField(source='client.sex')
    
    # Вычисляемые поля (из вашей модели)
    coins_balance = serializers.IntegerField() 

    class Meta:
        model = ClientBranch
        fields = [
            'id', # ID записи ClientBranch
            'vk_user_id', 
            'name', 
            'lastname', 
            'sex', 
            'birth_date',
            'coins_balance',
            'is_story_uploaded',
            'is_joined_community',
            'is_allowed_message',
            'is_super_prize_won',
            'is_employee'
        ]


class ReviewCreateSerializer(serializers.Serializer):
    """
    Валидация входящих данных для отзыва.
    """
    vk_user_id = serializers.IntegerField(required=True)
    branch_id = serializers.IntegerField(required=True)
    
    # DRF автоматически проверит, что число целое и входит в диапазон
    rating = serializers.IntegerField(min_value=1, max_value=5, required=True)
    
    phone = serializers.CharField(required=True)
    table = serializers.IntegerField(required=True)
    review = serializers.CharField(required=True, allow_blank=False)



class TransactionHistoryRequestSerializer(serializers.Serializer):
    """
    Валидация параметров запроса истории.
    """
    vk_user_id = serializers.IntegerField(required=True)
    branch_id = serializers.IntegerField(required=True)

class TransactionSerializer(serializers.ModelSerializer):
    """
    Сериализатор одной транзакции.
    """
    # Превращаем машинные коды (INCOME/EXPENSE) в читаемые (Доход/Трата)
    type_display = serializers.CharField(source='get_type_display', read_only=True)
    source_display = serializers.CharField(source='get_source_display', read_only=True)
    
    # Форматируем дату в удобный вид
    created_at_formatted = serializers.DateTimeField(source='created_at', format="%d.%m.%Y %H:%M")

    class Meta:
        model = CoinTransaction
        fields = [
            'id',
            'amount',
            'type',
            'type_display',   # Человекочитаемый тип
            'source',
            'source_display', # Человекочитаемый источник
            'description',
            'created_at',     # ISO формат
            'created_at_formatted' # Красивый формат
        ]


class EmployeeRequestSerializer(serializers.Serializer):
    branch = serializers.IntegerField()


class EmployeeResponseSerializer(serializers.ModelSerializer):

    class Meta:
        model = Client
        fields = ['vk_user_id', 'name', 'lastname', 'sex']


class PromotionRequestSerializer(serializers.Serializer):
    branch = serializers.IntegerField()


class PromotionResponseSerializer(serializers.ModelSerializer):

    images = serializers.SerializerMethodField()

    class Meta:
        model = Promotions
        fields = ['title', 'discount', 'dates', 'images']
    
    def get_images(self, instance):
        if instance.images:
            try:
                # Строим полный URL (https://domain.com/media/...)
                request = self.context.get('request')
                return request.build_absolute_uri(instance.images.url)
            except Exception:
                return instance.images.url
        return None