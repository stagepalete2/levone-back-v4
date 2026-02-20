from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.core.exceptions import ValidationError
from django.utils.timezone import now

from apps.shared.clients.core import CompanyDomainService
from apps.shared.clients.models import Company, Domain
from apps.shared.clients.api.serializers import DomainRequestSerializer, DomainResponseSerializer

import logging
logger = logging.getLogger(__name__)

class GetDomain(APIView):
    def get(self, request):
        # 1. Передаем query_params целиком, сериализатор сам достанет 'company'
        # и проверит, что это число и что оно вообще передано.

        data = request.query_params.copy()

        data['company'] = int(data['company']) + 1

        input_serializer = DomainRequestSerializer(data=data)
        input_serializer.is_valid(raise_exception=True)
        
        company_id = input_serializer.validated_data['company']
        
        
        # Если вам КРИТИЧЕСКИ нужно прибавить 1, делайте это после валидации
        # company_id += 1 

        try:
            # 2. Вызов бизнес-логики
            domain_obj = CompanyDomainService.get_company_domain(company_id)
            
            # 3. Формирование ответа
            output_serializer = DomainResponseSerializer(domain_obj)
            return Response(output_serializer.data, status=status.HTTP_200_OK)

        except ValidationError as e:
            logger.error(f"Error getting domain: {e}")
            return Response({
                'code': e.code if hasattr(e, 'code') else 'validation_error',
                'message': e.message if hasattr(e, 'message') else str(e)
            }, status=status.HTTP_400_BAD_REQUEST)
            
        except Exception as e:
            logger.error(f"Error getting domain: {e}")
            return Response({
                'code': 'server_error',
                'message': str(e) # В production лучше не отдавать сырой str(e) клиенту
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

		