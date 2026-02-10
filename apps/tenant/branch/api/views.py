from rest_framework.views import APIView
from rest_framework import status
from rest_framework.response import Response
from django.core.exceptions import ValidationError

from apps.tenant.branch.models import BotAdmin
from apps.tenant.branch.core import BranchService, ClientService, ReviewService
from apps.tenant.branch.api.serializers import BranchInfoResponseSerializer, BranchInfoRequestSerializer, ClientGetRequestSerializer, ClientProfileResponseSerializer, ClientRegistrationSerializer, ClientUpdateRequestSerializer, ReviewCreateSerializer, TransactionHistoryRequestSerializer, TransactionSerializer, EmployeeRequestSerializer, EmployeeResponseSerializer, PromotionRequestSerializer, PromotionResponseSerializer


class BranchInfoView(APIView):
	'''
	Получить всю информацию о ресторане
	GET /api/.../branch_info/?branch_id=1
	'''
	def get(self, request, format=None):
		request_serializer = BranchInfoRequestSerializer(data={
			'branch_id': request.query_params.get('branch')
		})
		
		if not request_serializer.is_valid():
			return Response(request_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

		valid_data = request_serializer.validated_data

		try:
			branch_instance = BranchService.get_branch_full_info(
				branch_id=valid_data['branch_id']
			)

			response_serializer = BranchInfoResponseSerializer(
				branch_instance, 
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


class ClientView(APIView):
	"""
	Единая точка входа для работы с профилем гостя.
	"""

	def get(self, request):
		serializer = ClientGetRequestSerializer(data=request.query_params)
		serializer.is_valid(raise_exception=True) # Само вернет 400 ошибку в стандартном формате DRF
		
		params = serializer.validated_data
		
		try:
			profile = ClientService.get_client_profile(**params) # Распаковка аргументов
			return Response(ClientProfileResponseSerializer(profile).data)
		except ValidationError as e:
			return Response({'code': e.code, 'message': e.message}, status=404)

	def post(self, request):
		"""Регистрация или вход"""
		input_serializer = ClientRegistrationSerializer(data=request.data)
		if not input_serializer.is_valid():
			return Response(input_serializer.errors, status=status.HTTP_400_BAD_REQUEST)
			
		data = input_serializer.validated_data

		try:
			client_profile = ClientService.register_or_update_client(
				vk_user_id=data['vk_user_id'],
				branch_id=data['branch_id'],
				data=data
			)
			
			# Record visit (QR scan) with 6-hour cooldown
			# This tracks when guests actually visit the restaurant
			from apps.tenant.branch.models import ClientBranchVisit, ClientBranch
			try:
				client_branch = ClientBranch.objects.get(
					client__vk_user_id=data['vk_user_id'],
					branch_id=data['branch_id']
				)
				ClientBranchVisit.record_visit(client_branch)
			except ClientBranch.DoesNotExist:
				pass  # New client, visit will be recorded on next scan
			
			return Response(
				ClientProfileResponseSerializer(client_profile).data, 
				status=status.HTTP_200_OK
			)
			
		except ValidationError as e:
			return Response({'code': e.code, 'message': e.message}, status=status.HTTP_404_NOT_FOUND)

	def patch(self, request):
		"""Частичное обновление настроек (сторис, подписка и т.д.)"""
		input_serializer = ClientUpdateRequestSerializer(data=request.data)
		if not input_serializer.is_valid():
			return Response(input_serializer.errors, status=status.HTTP_400_BAD_REQUEST)
		
		data = input_serializer.validated_data
		vk_user_id = data.pop('vk_user_id')
		branch_id = data.pop('branch_id')

		print(data)

		try:
			updated_profile = ClientService.update_profile_details(
				vk_user_id=vk_user_id,
				branch_id=branch_id,
				validated_data=data
			)
			
			return Response(
				ClientProfileResponseSerializer(updated_profile).data, 
				status=status.HTTP_200_OK
			)
			
		except ValidationError as e:
			return Response({'code': e.code, 'message': e.message}, status=status.HTTP_404_NOT_FOUND)
        



class ReviewView(APIView):
	"""
	Эндпоинт для оставления отзыва.
	POST /api/.../review/
	"""

	def post(self, request, format=None):
		serializer = ReviewCreateSerializer(data=request.data)
		if not serializer.is_valid():
			return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

		try:
			ReviewService.create_review(serializer.validated_data)
			
			return Response({'is_sent': True}, status=status.HTTP_200_OK)

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



class TransactionsView(APIView):
	"""
	Получение истории начисления и списания монет.
	GET /api/.../transactions/?vk_user_id=123&branch=1
	"""

	def get(self, request, format=None):
		# 1. Валидация Query Params (vk_user_id, branch)
		# Маппим старый параметр 'branch' в 'branch_id' для сериализатора
		input_data = {
			'vk_user_id': request.query_params.get('vk_user_id'),
			'branch_id': request.query_params.get('branch')
		}
		
		request_serializer = TransactionHistoryRequestSerializer(data=input_data)
		if not request_serializer.is_valid():
			return Response(request_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

		valid_data = request_serializer.validated_data

		try:
			# 2. Получение данных через сервис
			transactions = ClientService.get_client_transactions(
				vk_user_id=valid_data['vk_user_id'],
				branch_id=valid_data['branch_id']
			)

			# 3. Сериализация списка (many=True)
			response_serializer = TransactionSerializer(transactions, many=True)
			
			return Response(response_serializer.data, status=status.HTTP_200_OK)

		except ValidationError as e:
			# Если клиент или ресторан не найдены
			return Response({
				"code": e.code, 
				"message": e.message
			}, status=status.HTTP_404_NOT_FOUND)
			
		except Exception as e:
			return Response({
				"code": "server_error", 
				"message": str(e)
			}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)




class TelegramWebhookView(APIView):
    """
    Принимает вебхуки от Telegram.
    Используется для привязки админа к чату (/start <token>).
    """
    def post(self, request):
        data = request.data
        message = data.get('message', {})
        
        if not message:
             return Response('OK') # Игнорируем обновления без message

        text = message.get('text', '') 
        chat_id = message.get('chat', {}).get('id')
        
        # Логика подключения админа
        if text and text.startswith('/start '):
            try:
                # Безопасное извлечение токена
                parts = text.split(' ')
                if len(parts) < 2:
                    return Response('OK')
                
                token = parts[1]
                
                admin_entry = BotAdmin.objects.get(verification_token=token)
                
                # Сохраняем chat_id
                admin_entry.chat_id = str(chat_id)
                admin_entry.save()
                
                # Тут можно отправить ответное сообщение в Телеграм (успешно подключено)
                # но request должен вернуть 200 быстро.
                
            except BotAdmin.DoesNotExist:
                # Токен неверный или устарел
                pass
            except Exception as e:
                # Логируем ошибку, но телеграму отдаем OK, чтобы он не спамил
                print(f"Webhook error: {e}")

        return Response('OK', status=status.HTTP_200_OK)


class EmployeeView(APIView):
	def get(self, request, format=None):
		data = request.query_params
		request_serializer = EmployeeRequestSerializer(data=data)

		if not request_serializer.is_valid():
			return Response(request_serializer.errors, status=status.HTTP_400_BAD_REQUEST)
		
		valid_data = request_serializer.validated_data

		employee_clients = ClientService.get_employees(branch=valid_data['branch'])

		response_serializer = EmployeeResponseSerializer(employee_clients, many=True) 

		return Response(response_serializer.data, status=status.HTTP_200_OK)


class PromotionView(APIView):
	def get(self, request, format=None):
		data = request.query_params
		request_serializer = PromotionRequestSerializer(data=data)

		if not request_serializer.is_valid():
			return Response(request_serializer.errors, status=status.HTTP_400_BAD_REQUEST)
		
		valid_data = request_serializer.validated_data

		promotions = BranchService.get_promotions(branch = valid_data['branch'])

		response_serializer = PromotionResponseSerializer(promotions, many=True, context={'request' : request})

		return Response(response_serializer.data, status=status.HTTP_200_OK)

