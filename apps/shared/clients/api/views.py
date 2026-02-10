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
        input_serializer = DomainRequestSerializer(data=request.query_params)
        input_serializer.is_valid(raise_exception=True)
        company = input_serializer.validated_data['company']
        try:
            domain_obj = CompanyDomainService.get_company_domain(company)
            
            output_serializer = DomainResponseSerializer(domain_obj)
            return Response(output_serializer.data, status=status.HTTP_200_OK)

        except ValidationError as e:
            logger.error(f"Error getting domain: {e}")
            return Response({
                'code': e.code,
                'message': e.message
            }, status=status.HTTP_400_BAD_REQUEST)
            
        except Exception as e:
            logger.error(f"Error getting domain: {e}")
            return Response({
                'code': 'server_error',
                'message': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


		