from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.core.exceptions import ValidationError

from apps.tenant.inventory.api.serializers import (
    InventoryRequestSerializer, 
    InventorySerializer, 
    SuperPrizeSerializer,
    SuperPrizeClaimSerializer,
    InventoryCooldownSerializer,
    InventoryActivateSerializer
)
from apps.tenant.inventory.core import InventoryService, CooldownService

class InventoryView(APIView):
    """
    Получить список активных подарков.
    GET /api/.../inventory/?vk_user_id=1&branch=1
    """
    def get(self, request, format=None):
        request_serializer = InventoryRequestSerializer(data=request.query_params)
        if not request_serializer.is_valid():
            return Response(request_serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        data = request_serializer.validated_data

        try:
            inventory = InventoryService.get_client_inventory(
                vk_user_id=data['vk_user_id'],
                branch_id=data['branch_id']
            )
            
            response_serializer = InventorySerializer(
                inventory, 
                many=True,
                context={'request': request}
            )
            return Response(response_serializer.data, status=status.HTTP_200_OK)

        except ValidationError as e:
            return Response({'code': e.code, 'message': e.message}, status=status.HTTP_404_NOT_FOUND)


class SuperPrizeInventoryView(APIView):
    """
    GET: Получить доступные супер-призы (еще не выбранные).
    POST: Выбрать (активировать) супер-приз -> превращает его в Inventory Item.
    """
    def get(self, request, format=None):
        request_serializer = InventoryRequestSerializer(data=request.query_params)
        if not request_serializer.is_valid():
            return Response(request_serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        data = request_serializer.validated_data

        try:
            prizes = InventoryService.get_client_super_prizes(
                vk_user_id=data['vk_user_id'],
                branch_id=data['branch_id']
            )
            serializer = SuperPrizeSerializer(prizes, many=True, context={'request': request})
            return Response(serializer.data, status=status.HTTP_200_OK)
            
        except ValidationError as e:
            return Response({'code': e.code, 'message': e.message}, status=status.HTTP_404_NOT_FOUND)

    def post(self, request, format=None):
        """Выбор приза"""
        # Поддержка старого формата (если параметры в query) и нового (в body)
        # Но лучше следовать body.
        data = request.data.copy()
        
        request_serializer = SuperPrizeClaimSerializer(data=data)
        if not request_serializer.is_valid():
            return Response(request_serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        valid_data = request_serializer.validated_data

        try:
            inventory_item = InventoryService.claim_super_prize(
                vk_user_id=valid_data['vk_user_id'],
                branch_id=valid_data['branch_id'],
                product_id=valid_data['product_id']
            )
            
            serializer = InventorySerializer(inventory_item, context={'request': request})
            return Response(serializer.data, status=status.HTTP_200_OK)

        except ValidationError as e:
            # Возвращаем 404 если не найдено, 400 в остальных случаях
            status_code = status.HTTP_404_NOT_FOUND if e.code in ['not_found', 'product_not_found'] else status.HTTP_400_BAD_REQUEST
            return Response({'code': e.code, 'message': e.message}, status=status_code)
        except Exception as e:
            return Response({'code': 'server_error', 'message': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class InventoryCooldownView(APIView):
    """
    Статус перезарядки инвентаря.
    """
    def get(self, request, format=None):
        request_serializer = InventoryRequestSerializer(data=request.query_params)
        if not request_serializer.is_valid():
            return Response(request_serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        data = request_serializer.validated_data

        try:
            cooldown = CooldownService.get_cooldown_status(
                vk_user_id=data['vk_user_id'],
                branch_id=data['branch_id']
            )
            
            if not cooldown:
                return Response({}, status=status.HTTP_200_OK)
            
            serializer = InventoryCooldownSerializer(cooldown)
            return Response(serializer.data, status=status.HTTP_200_OK)
            
        except ValidationError as e:
            return Response({'code': e.code, 'message': e.message}, status=status.HTTP_404_NOT_FOUND)

    def post(self, request, format=None):
        """Ручная установка кулдауна"""
        request_serializer = InventoryRequestSerializer(data=request.query_params)
        if not request_serializer.is_valid():
            return Response(request_serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        data = request_serializer.validated_data

        try:
            cooldown = CooldownService.activate_cooldown_manually(
                vk_user_id=data['vk_user_id'],
                branch_id=data['branch_id']
            )
            serializer = InventoryCooldownSerializer(cooldown)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except ValidationError as e:
            return Response({'code': e.code, 'message': e.message}, status=status.HTTP_404_NOT_FOUND)


class InventoryActivateView(APIView):
    """
    Активация предмета (использование).
    """
    def post(self, request, format=None):
        request_serializer = InventoryActivateSerializer(data=request.data)
        if not request_serializer.is_valid():
            return Response(request_serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        data = request_serializer.validated_data

        try:
            inventory_item = InventoryService.activate_inventory_item(
                vk_user_id=data['vk_user_id'],
                branch_id=data['branch_id'],
                inventory_id=data['inventory_id']
            )
            
            serializer = InventorySerializer(inventory_item, context={'request': request})
            return Response(serializer.data, status=status.HTTP_200_OK)
            
        except ValidationError as e:
            status_code = status.HTTP_400_BAD_REQUEST
            if e.code == 'not_found':
                status_code = status.HTTP_404_NOT_FOUND
                
            return Response({'code': e.code, 'message': e.message}, status=status_code)