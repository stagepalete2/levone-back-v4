from django.shortcuts import render


from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db import connection

from apps.tenant.game.api.serializers import GamePlayRequestSerializer, SuperPrizeSerializer, GameCooldownRequestSerializer, GameCooldownResponseSerializer
from apps.tenant.game.core import GameService, CooldownService
from apps.tenant.senler.tasks import schedule_post_game_message

class GamePlayView(APIView):
    """
    POST /api/.../game/play/
    """
    def post(self, request, format=None):
        data = request.data.copy()
        if 'branch' in data and 'branch_id' not in data:
            data['branch_id'] = data['branch']
            
        request_serializer = GamePlayRequestSerializer(data=data)
        if not request_serializer.is_valid():
            return Response(request_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        valid_data = request_serializer.validated_data

        try:
            result = GameService.play_game(
                vk_user_id=valid_data['vk_user_id'],
                branch_id=valid_data['branch_id'],
                code=valid_data.get('code'),
                employee_id=valid_data.get('employee_id')
            )

            response_data = {'type': result['type']}

            if result['type'] == 'prize':
                prize_serializer = SuperPrizeSerializer(
                    result['reward'], 
                    context={'request': request}
                )
                response_data['reward'] = prize_serializer.data
            
            elif result['type'] == 'coin':
                response_data['reward'] = result['reward']
            
            elif result['type'] == 'code':
                response_data['message'] = 'Введите код дня'

            # Schedule post-game message (3 hours later with quiet hours)
            if result['type'] in ('prize', 'coin'):
                # Get client_branch_id from the result or query it
                from apps.tenant.branch.models import ClientBranch
                client_branch = ClientBranch.objects.filter(
                    client__vk_user_id=valid_data['vk_user_id'],
                    branch_id=valid_data['branch_id']
                ).first()
                
                if client_branch:
                    schedule_post_game_message.delay(
                        client_branch_id=client_branch.id,
                        schema_name=connection.schema_name
                    )

            return Response(response_data, status=status.HTTP_200_OK)

        except ValidationError as e:
            return Response({
                "code": e.code, 
                "message": e.message
            }, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            return Response({
                "code": "server_error", 
                "message": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)



class GameCooldownView(APIView):
    """
    Управление перезарядкой игры.
    GET / POST / DELETE  /api/.../game/cooldown/
    """

    def get(self, request, format=None):
        """Получить статус"""
        request_serializer = GameCooldownRequestSerializer(data={
            'vk_user_id': request.query_params.get('vk_user_id'),
            'branch_id': request.query_params.get('branch')
        })
        
        if not request_serializer.is_valid():
            return Response(request_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        valid_data = request_serializer.validated_data

        try:
            cooldown = CooldownService.get_cooldown_status(
                vk_user_id=valid_data['vk_user_id'],
                branch_id=valid_data['branch_id']
            )

            if not cooldown:
                return Response({}, status=status.HTTP_200_OK)

            response_serializer = GameCooldownResponseSerializer(cooldown)
            return Response(response_serializer.data, status=status.HTTP_200_OK)

        except ValidationError as e:
            return Response({'code': e.code, 'message': e.message}, status=status.HTTP_404_NOT_FOUND)

    def post(self, request, format=None):
        """Активировать таймер вручную"""
        # Поддержка query_params для POST (как в старом коде), но лучше бы в body
        data = request.query_params.copy()
        # Если данных нет в query_params, смотрим в body (для совместимости)
        if not data.get('vk_user_id'):
            data = request.data.copy()
            if 'branch' in data and 'branch_id' not in data:
                data['branch_id'] = data['branch']
        else:
             # Маппинг для query_params
             if 'branch' in data and 'branch_id' not in data:
                data['branch_id'] = data['branch']

        request_serializer = GameCooldownRequestSerializer(data=data)
        if not request_serializer.is_valid():
            return Response(request_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        valid_data = request_serializer.validated_data

        try:
            cooldown = CooldownService.activate_cooldown(
                vk_user_id=valid_data['vk_user_id'],
                branch_id=valid_data['branch_id']
            )
            
            response_serializer = GameCooldownResponseSerializer(cooldown)
            return Response(response_serializer.data, status=status.HTTP_200_OK)

        except ValidationError as e:
            return Response({'code': e.code, 'message': e.message}, status=status.HTTP_404_NOT_FOUND)

    def delete(self, request, format=None):
        """Сбросить таймер (удалить запись)"""
        request_serializer = GameCooldownRequestSerializer(data={
            'vk_user_id': request.query_params.get('vk_user_id'),
            'branch_id': request.query_params.get('branch')
        })

        if not request_serializer.is_valid():
            return Response(request_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        valid_data = request_serializer.validated_data

        try:
            CooldownService.reset_cooldown(
                vk_user_id=valid_data['vk_user_id'],
                branch_id=valid_data['branch_id']
            )
            
            # Возвращаем структуру сброшенного таймера (время 0)
            # Можно вернуть просто 200 OK или 204 No Content
            return Response(
                {
                    "is_active": False,
                    "time_left_seconds": 0,
                    "last_activated_at": None
                }, 
                status=status.HTTP_200_OK
            )

        except ValidationError as e:
            return Response({'code': e.code, 'message': e.message}, status=status.HTTP_404_NOT_FOUND)
# game/views.py (пример)
# from mailing.tasks import schedule_post_game_message
# from django.db import connection

# def game_finished(request):
#     # ... логика сохранения попытки ...
#     # client_branch = ...
    
#     # Запускаем задачу планирования сообщения
#     schedule_post_game_message.delay(
#         client_branch_id=client_branch.id,
#         schema_name=connection.schema_name
#     )