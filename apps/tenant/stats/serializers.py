from rest_framework import serializers
from .models import RFSegment, GuestRFScore, RFMigrationLog

class MigrationFilterSerializer(serializers.Serializer):
    """Валидация фильтров для страницы миграции"""
    days = serializers.IntegerField(min_value=1, max_value=3650, default=30, required=False)
    segment = serializers.CharField(max_length=10, required=False, allow_blank=True)

class RFSegmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = RFSegment
        fields = ['id', 'code', 'name', 'emoji', 'color', 'recency_min', 'recency_max', 'frequency_min', 'frequency_max']

class GuestRFScoreSerializer(serializers.ModelSerializer):
    segment = RFSegmentSerializer(read_only=True)
    
    class Meta:
        model = GuestRFScore
        fields = ['client', 'recency_days', 'frequency', 'r_score', 'f_score', 'segment']


class RFRecalculateSerializer(serializers.Serializer):
    """Валидация запроса на пересчет"""
    branch = serializers.IntegerField(required=False, allow_null=True)


class RFSettingsUpdateSerializer(serializers.Serializer):
    """Валидация настроек RFM"""
    branch = serializers.IntegerField()
    analysis_period = serializers.IntegerField(min_value=1, default=365)
    
    # Пороги
    r3_max = serializers.IntegerField(min_value=0)
    r2_max = serializers.IntegerField(min_value=0)
    r1_max = serializers.IntegerField(min_value=0)
    f1_max = serializers.IntegerField(min_value=0)
    f2_max = serializers.IntegerField(min_value=0)

    def validate(self, data):
        # Проверка логической целостности порогов
        if not (data['r3_max'] < data['r2_max'] < data['r1_max']):
             raise serializers.ValidationError("Пороги Recency должны возрастать: R3 < R2 < R1")
        
        if not (data['f1_max'] < data['f2_max']):
             raise serializers.ValidationError("Пороги Frequency должны возрастать: F1 < F2")
        
        return data


class RFGuestListSerializer(serializers.Serializer):
    """Форматирование вывода списка гостей"""
    vk_id = serializers.IntegerField(source='client.client.vk_user_id')
    name = serializers.CharField(source='client.client.full_name')
    total_visits = serializers.IntegerField(source='frequency')
    coins = serializers.IntegerField(source='client.coins_balance')
    last_visit = serializers.SerializerMethodField()

    def get_last_visit(self, obj):
        # last_visit_date получен через annotate в сервисе
        date = getattr(obj, 'last_visit_date', None)
        return date.strftime('%d.%m.%Y') if date else "—"