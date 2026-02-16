from rest_framework import serializers

from apps.tenant.delivery.models import Delivery

class DeliveryActivationSerializer(serializers.Serializer):
    short_code = serializers.CharField(max_length=5, min_length=5)
    branch = serializers.IntegerField()
    vk_user_id = serializers.IntegerField()


class DeliveryWebhookRequestSerializer(serializers.Serializer):
    source = serializers.CharField(max_length=50, help_text='Источник заказа: dooglys или iiko')
    branch_id = serializers.CharField(help_text='ID филиала из соответствующей системы')
    code = serializers.CharField()

class DeliveryWebhookResponseSerializer(serializers.ModelSerializer):
    
    class Meta:
        model = Delivery
        fields = ['code']