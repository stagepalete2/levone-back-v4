from rest_framework import serializers

from apps.tenant.delivery.models import Delivery

class DeliveryActivationSerializer(serializers.Serializer):
    short_code = serializers.CharField(max_length=5, min_length=5)
    branch = serializers.IntegerField()
    vk_user_id = serializers.IntegerField()


class DeliveryWebhookRequestSerializer(serializers.Serializer):
    branch = serializers.IntegerField()
    code = serializers.CharField()

class DeliveryWebhookResponseSerializer(serializers.ModelSerializer):
    
    class Meta:
        model = Delivery
        fields = ['code']