from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.db.models import F
from rest_framework.permissions import AllowAny

from apps.shared.guest.models import Client
from apps.tenant.branch.models import ClientBranch, Branch

from apps.tenant.delivery.models import Delivery
from apps.tenant.delivery.api.serializers import DeliveryActivationSerializer, DeliveryWebhookRequestSerializer, DeliveryWebhookResponseSerializer

class DeliveryWebhook(APIView):
    permission_classes = [AllowAny, ]

    def post(self, request):
        serializer = DeliveryWebhookRequestSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        code = serializer.validated_data['code']
        source = serializer.validated_data['source'].lower()
        branch_id = serializer.validated_data['branch_id']

        # Ищем Branch в зависимости от источника
        try:
            if source == 'dooglys':
                branch = Branch.objects.get(dooglys_branch_id=branch_id)
            elif source == 'iiko':
                branch = Branch.objects.get(iiko_organization_id=branch_id)
            else:
                return Response({
                    'error': 'invalid_source',
                    'msg': 'Источник должен быть "dooglys" или "iiko"'
                }, status=status.HTTP_400_BAD_REQUEST)
        except Branch.DoesNotExist:
            return Response({
                'error': 'branch_not_found',
                'msg': f'Филиал с {source}_branch_id={branch_id} не найден'
            }, status=status.HTTP_404_NOT_FOUND)

        # Создаем или получаем запись Delivery
        candidate, created = Delivery.objects.get_or_create(
            code=code,
            branch=branch,
            defaults={'order_source': source}
        )

        if created:
            serializer = DeliveryWebhookResponseSerializer(candidate, many=False)
            return Response(serializer.data, status=status.HTTP_200_OK)
        
        return Response({
            'error': 'already_exist',
            'msg': 'Уже существует'
        }, status=status.HTTP_400_BAD_REQUEST)


class DeliveryCodeView(APIView):
    def post(self, request):
        serializer = DeliveryActivationSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        short_code = serializer.validated_data['short_code']
        vk_user_id = serializer.validated_data['vk_user_id']
        branch_id = serializer.validated_data['branch']

        # 1. Сначала ищем код (и проверяем срок годности)
        candidates = Delivery.objects.filter(
            code__endswith=short_code
        ).order_by('-created_at')

        valid_delivery = None
        now = timezone.now()

        for delivery in candidates:
            if delivery.created_at + delivery.duration > now:
                valid_delivery = delivery
                break
        
        if not valid_delivery:
            return Response(
                {'error': 'Код не найден или просрочен'}, 
                status=status.HTTP_404_NOT_FOUND
            )

        # 2. Ищем пользователя (ClientBranch), который отправил запрос
        # Если клиент или его привязка к филиалу не найдены — 404
        client = get_object_or_404(Client, vk_user_id=vk_user_id)
        branch = get_object_or_404(Branch, id=branch_id)
        client_branch = get_object_or_404(ClientBranch, client=client, branch=branch)

        # 3 и 4. Проверка активатора
        if valid_delivery.activated_by is None:
            # Если еще никто не активировал — присваиваем
            valid_delivery.activated_by = client_branch
            valid_delivery.save()
        else:
            # Если уже кто-то стоит, проверяем, тот ли это человек
            if valid_delivery.activated_by != client_branch:
                return Response(
                    {'error': 'Этот код уже активирован другим пользователем'}, 
                    status=status.HTTP_403_FORBIDDEN
                )
            # Если тот же самый — просто идем дальше (пропускаем)

        return Response(
            {
                'message': 'Delivery code activated successfully', 
                'delivery_id': valid_delivery.id
            }, 
            status=status.HTTP_200_OK
        )