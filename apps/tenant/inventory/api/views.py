from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.core.exceptions import ValidationError

from apps.tenant.inventory.api.serializers import (
    InventoryRequestSerializer,
    InventorySerializer,
    SuperPrizeSerializer,
    SuperPrizeClaimSerializer,
    BirthdayPrizeClaimSerializer,
    BirthdayStatusSerializer,
    InventoryCooldownSerializer,
    InventoryActivateSerializer,
)
from apps.tenant.catalog.api.serializers import CatalogResponseSerializer
from apps.tenant.inventory.core import InventoryService, CooldownService


class InventoryView(APIView):
    """
    GET /api/v1/inventory/?vk_user_id=1&branch_id=1
    """
    def get(self, request, format=None):
        s = InventoryRequestSerializer(data=request.query_params)
        if not s.is_valid():
            return Response(s.errors, status=status.HTTP_400_BAD_REQUEST)
        d = s.validated_data
        try:
            inventory = InventoryService.get_client_inventory(
                vk_user_id=d['vk_user_id'], branch_id=d['branch_id'])
            return Response(InventorySerializer(inventory, many=True,
                context={'request': request}).data)
        except ValidationError as e:
            return Response({'code': e.code, 'message': e.message}, status=status.HTTP_404_NOT_FOUND)


class SuperPrizeInventoryView(APIView):
    """Обычные супер-призы (GAME/MANUAL)."""
    def get(self, request, format=None):
        s = InventoryRequestSerializer(data=request.query_params)
        if not s.is_valid():
            return Response(s.errors, status=status.HTTP_400_BAD_REQUEST)
        d = s.validated_data
        try:
            prizes = InventoryService.get_client_super_prizes(
                vk_user_id=d['vk_user_id'], branch_id=d['branch_id'])
            return Response(SuperPrizeSerializer(prizes, many=True,
                context={'request': request}).data)
        except ValidationError as e:
            return Response({'code': e.code, 'message': e.message}, status=status.HTTP_404_NOT_FOUND)

    def post(self, request, format=None):
        s = SuperPrizeClaimSerializer(data=request.data)
        if not s.is_valid():
            return Response(s.errors, status=status.HTTP_400_BAD_REQUEST)
        d = s.validated_data
        try:
            item = InventoryService.claim_super_prize(
                vk_user_id=d['vk_user_id'], branch_id=d['branch_id'], product_id=d['product_id'])
            return Response(InventorySerializer(item, context={'request': request}).data)
        except ValidationError as e:
            sc = status.HTTP_404_NOT_FOUND if e.code in ['not_found', 'product_not_found'] else status.HTTP_400_BAD_REQUEST
            return Response({'code': e.code, 'message': e.message}, status=sc)
        except Exception as e:
            return Response({'code': 'server_error', 'message': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class BirthdayStatusView(APIView):
    """
    GET /api/v1/birthday/status/?vk_user_id=1&branch_id=1
    Возвращает is_birthday_mode — попадает ли гость в окно ±5 дней от ДР.
    """
    def get(self, request, format=None):
        s = InventoryRequestSerializer(data=request.query_params)
        if not s.is_valid():
            return Response(s.errors, status=status.HTTP_400_BAD_REQUEST)
        d = s.validated_data
        try:
            result = InventoryService.get_birthday_status(
                vk_user_id=d['vk_user_id'], branch_id=d['branch_id'])
            return Response(BirthdayStatusSerializer(result).data)
        except ValidationError as e:
            return Response({'code': e.code, 'message': e.message}, status=status.HTTP_404_NOT_FOUND)


class BirthdayPrizeView(APIView):
    """
    GET  /api/v1/birthday/prize/?vk_user_id=1&branch_id=1
         Возвращает список catalog.Product (is_birthday_prize=True).
         Только если гость в окне ±5 дней ДР.

    POST /api/v1/birthday/prize/
         Body: { vk_user_id, branch_id, product_id }
         Создаёт Inventory(acquired_from='BIRTHDAY_PRIZE', activated_at=None).
         Активация только через InventoryActivateView в кафе.
    """
    def get(self, request, format=None):
        s = InventoryRequestSerializer(data=request.query_params)
        if not s.is_valid():
            return Response(s.errors, status=status.HTTP_400_BAD_REQUEST)
        d = s.validated_data
        try:
            products = InventoryService.get_client_birthday_prizes(
                vk_user_id=d['vk_user_id'], branch_id=d['branch_id'])
            return Response(CatalogResponseSerializer(
                products, many=True, context={'request': request}).data)
        except ValidationError as e:
            sc = status.HTTP_403_FORBIDDEN if e.code == 'not_birthday_window' else status.HTTP_404_NOT_FOUND
            return Response({'code': e.code, 'message': e.message}, status=sc)

    def post(self, request, format=None):
        s = BirthdayPrizeClaimSerializer(data=request.data)
        if not s.is_valid():
            return Response(s.errors, status=status.HTTP_400_BAD_REQUEST)
        d = s.validated_data
        try:
            item = InventoryService.claim_birthday_prize(
                vk_user_id=d['vk_user_id'], branch_id=d['branch_id'], product_id=d['product_id'])
            return Response(InventorySerializer(item, context={'request': request}).data)
        except ValidationError as e:
            if e.code == 'not_birthday_window':
                return Response({'code': e.code, 'message': e.message}, status=status.HTTP_403_FORBIDDEN)
            sc = status.HTTP_404_NOT_FOUND if e.code in ['not_found', 'product_not_found'] else status.HTTP_400_BAD_REQUEST
            return Response({'code': e.code, 'message': e.message}, status=sc)
        except Exception as e:
            return Response({'code': 'server_error', 'message': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class InventoryCooldownView(APIView):
    """Статус перезарядки."""
    def get(self, request, format=None):
        s = InventoryRequestSerializer(data=request.query_params)
        if not s.is_valid():
            return Response(s.errors, status=status.HTTP_400_BAD_REQUEST)
        d = s.validated_data
        try:
            cooldown = CooldownService.get_cooldown_status(
                vk_user_id=d['vk_user_id'], branch_id=d['branch_id'])
            if not cooldown:
                return Response({})
            return Response(InventoryCooldownSerializer(cooldown).data)
        except ValidationError as e:
            return Response({'code': e.code, 'message': e.message}, status=status.HTTP_404_NOT_FOUND)

    def post(self, request, format=None):
        s = InventoryRequestSerializer(data=request.query_params)
        if not s.is_valid():
            return Response(s.errors, status=status.HTTP_400_BAD_REQUEST)
        d = s.validated_data
        try:
            cooldown = CooldownService.activate_cooldown_manually(
                vk_user_id=d['vk_user_id'], branch_id=d['branch_id'])
            return Response(InventoryCooldownSerializer(cooldown).data)
        except ValidationError as e:
            return Response({'code': e.code, 'message': e.message}, status=status.HTTP_404_NOT_FOUND)


class InventoryActivateView(APIView):
    """
    POST /api/v1/inventory/activate/
    Активация предмета (показать официанту).
    Для BIRTHDAY_PRIZE — без cooldown, только в кафе.
    """
    def post(self, request, format=None):
        s = InventoryActivateSerializer(data=request.data)
        if not s.is_valid():
            return Response(s.errors, status=status.HTTP_400_BAD_REQUEST)
        d = s.validated_data
        try:
            item = InventoryService.activate_inventory_item(
                vk_user_id=d['vk_user_id'], branch_id=d['branch_id'], inventory_id=d['inventory_id'])
            return Response(InventorySerializer(item, context={'request': request}).data)
        except ValidationError as e:
            sc = status.HTTP_404_NOT_FOUND if e.code == 'not_found' else status.HTTP_400_BAD_REQUEST
            return Response({'code': e.code, 'message': e.message}, status=sc)