from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.core.exceptions import ValidationError

from apps.tenant.catalog.api.serializers import CatalogRequestSerializer, CatalogResponseSerializer, CooldownRequestSerializer, CooldownResponseSerializer, BuyRequestSerializer, BuyResponseSerializer
from apps.tenant.catalog.core import CatalogService, CooldownService

class CatalogView(APIView):
    """
    Получение списка товаров (каталога) магазина.
    GET /api/.../catalog/?branch=1
    """

    def get(self, request, format=None):
        request_serializer = CatalogRequestSerializer(data={
            'branch_id': request.query_params.get('branch')
        })
        
        if not request_serializer.is_valid():
            return Response(request_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        branch_id = request_serializer.validated_data['branch_id']

        try:
            products = CatalogService.get_active_products(branch_id=branch_id)

            response_serializer = CatalogResponseSerializer(
                products, 
                many=True, 
                context={'request': request}
            )
            
            return Response(response_serializer.data, status=status.HTTP_200_OK)

        except ValidationError as e:
            return Response({
                "code": e.code, 
                "message": e.message
            }, status=status.HTTP_404_NOT_FOUND)
            
        except Exception as e:
            return Response({
                "code": "server_error", 
                "message": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class CooldownView(APIView):
    """
    Управление таймером (перезарядкой) получения подарков.
    """

    def get(self, request, format=None):
        '''
        Получить статус перезарядки.
        GET /api/.../cooldown/?vk_user_id=123&branch=1
        '''
        # 1. Валидация параметров
        # Маппинг branch -> branch_id
        input_data = {
            'vk_user_id': request.query_params.get('vk_user_id'),
            'branch_id': request.query_params.get('branch')
        }
        request_serializer = CooldownRequestSerializer(data=input_data)
        if not request_serializer.is_valid():
            return Response(request_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        valid_data = request_serializer.validated_data

        try:
            # 2. Обращение к сервису
            cooldown = CooldownService.get_cooldown_status(
                vk_user_id=valid_data['vk_user_id'],
                branch_id=valid_data['branch_id']
            )

            # 3. Ответ
            if not cooldown:
                # Если записи нет, возвращаем пустой JSON (как в старом коде)
                # Или можно вернуть дефолтную структуру: {"is_active": False, "time_left_seconds": 0}
                return Response({}, status=status.HTTP_200_OK)
            
            response_serializer = CooldownResponseSerializer(cooldown)
            return Response(response_serializer.data, status=status.HTTP_200_OK)

        except ValidationError as e:
            return Response({'code': e.code, 'message': e.message}, status=status.HTTP_404_NOT_FOUND)
    
    def post(self, request, format=None):
        '''
        Сбросить/Активировать таймер.
        POST /api/.../cooldown/
        Body: { "vk_user_id": 123, "branch": 1 }
        '''
        # 1. Валидация тела запроса
        # Если фронт шлет в body параметр "branch", маппим его
        data = request.data.copy()
        if 'branch' in data and 'branch_id' not in data:
            data['branch_id'] = data['branch']

        request_serializer = CooldownRequestSerializer(data=data)
        if not request_serializer.is_valid():
            return Response(request_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        valid_data = request_serializer.validated_data

        try:
            # 2. Активация через сервис
            cooldown = CooldownService.activate_cooldown(
                vk_user_id=valid_data['vk_user_id'],
                branch_id=valid_data['branch_id']
            )

            response_serializer = CooldownResponseSerializer(cooldown)
            return Response(response_serializer.data, status=status.HTTP_200_OK)

        except ValidationError as e:
            return Response({'code': e.code, 'message': e.message}, status=status.HTTP_404_NOT_FOUND)


class BuyView(APIView):
    """
    Покупка подарка.
    POST /api/.../buy/
    Body: { "vk_user_id": 123, "branch": 1, "product_id": 55 }
    """

    def post(self, request, format=None):
        # 1. Подготовка данных (маппинг branch -> branch_id)
        data = request.data.copy()
        if 'branch' in data and 'branch_id' not in data:
            data['branch_id'] = data['branch']

        # 2. Валидация
        request_serializer = BuyRequestSerializer(data=data)
        if not request_serializer.is_valid():
            return Response(request_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        valid_data = request_serializer.validated_data

        try:
            # 3. Вызов сервиса
            inventory_item = CatalogService.buy_product(
                vk_user_id=valid_data['vk_user_id'],
                branch_id=valid_data['branch_id'],
                product_id=valid_data['product_id']
            )

            # 4. Ответ
            # Передаем request в context, чтобы product_image был с полным доменом
            response_serializer = BuyResponseSerializer(
                inventory_item, 
                context={'request': request}
            )
            return Response(response_serializer.data, status=status.HTTP_200_OK)

        except ValidationError as e:
            # Обработка ошибок бизнес-логики
            status_code = status.HTTP_400_BAD_REQUEST
            if e.code in ['product_not_found', 'not_found']:
                status_code = status.HTTP_404_NOT_FOUND
            
            return Response({
                "code": e.code, 
                "message": e.message
            }, status=status_code)

        except Exception as e:
            return Response({
                "code": "server_error", 
                "message": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)