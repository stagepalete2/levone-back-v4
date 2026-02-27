import logging

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from django.core.exceptions import ValidationError
from django.utils.timezone import now

from apps.shared.clients.core import CompanyDomainService
from apps.shared.clients.models import Company, Domain
from apps.shared.clients.api.serializers import (
    DomainRequestSerializer,
    DomainResponseSerializer,
    SharedDeliveryWebhookRequestSerializer,
)

logger = logging.getLogger(__name__)


class GetDomain(APIView):
    def get(self, request):
        data = request.query_params.copy()
        data['company'] = int(data['company']) + 1

        input_serializer = DomainRequestSerializer(data=data)
        input_serializer.is_valid(raise_exception=True)
        company_id = input_serializer.validated_data['company']

        try:
            domain_obj = CompanyDomainService.get_company_domain(company_id)
            output_serializer = DomainResponseSerializer(domain_obj)
            return Response(output_serializer.data, status=status.HTTP_200_OK)

        except ValidationError as e:
            logger.error(f"Error getting domain: {e}")
            return Response({
                'code': e.code if hasattr(e, 'code') else 'validation_error',
                'message': e.message if hasattr(e, 'message') else str(e),
            }, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            logger.error(f"Error getting domain: {e}")
            return Response({
                'code': 'server_error',
                'message': str(e),
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SharedDeliveryWebhookView(APIView):
    """
    POST /api/v1/delivery/webhook/
    
    Единая точка входа для всех доставок (Dooglys / IIKO).
    Получает код заказа + branch_id → ищет ресторан во ВСЕХ тенантах → создаёт Delivery.

    Формат запроса:
        {
            "source":    "dooglys" | "iiko",
            "branch_id": 43,        # ID филиала в системе (== dooglys_branch_id в Branch)
            "code":      "XYZ123"   # Уникальный код заказа
        }

    Логика:
    1. Проходим по всем активным тенантам.
    2. В каждом тенанте ищем Branch с dooglys_branch_id == branch_id (или iiko_organization_id).
    3. Как только найдём — создаём Delivery в этом тенанте.
    4. Если нигде не найдём — 404.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = SharedDeliveryWebhookRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        code      = serializer.validated_data['code']
        source    = serializer.validated_data['source'].lower()
        branch_id = serializer.validated_data['branch_id']

        if source not in ('dooglys', 'iiko'):
            return Response({
                'error': 'invalid_source',
                'msg': 'Источник должен быть "dooglys" или "iiko"',
            }, status=status.HTTP_400_BAD_REQUEST)

        # Перебираем все тенанты (исключая публичную схему)
        tenants = Company.objects.filter(is_active=True).exclude(schema_name='public')

        for tenant in tenants:
            result = self._try_create_delivery_in_tenant(
                tenant=tenant,
                source=source,
                branch_id=branch_id,
                code=code,
            )
            if result is not None:
                return result

        return Response({
            'error': 'branch_not_found',
            'msg': f'Филиал с {source}_branch_id={branch_id} не найден ни в одном ресторане',
        }, status=status.HTTP_404_NOT_FOUND)

    @staticmethod
    def _try_create_delivery_in_tenant(tenant, source, branch_id, code):
        """
        Пытается найти Branch и создать Delivery в схеме тенанта.
        Возвращает Response если нашёл, None если не нашёл.
        """
        from django_tenants.utils import schema_context

        with schema_context(tenant.schema_name):
            from apps.tenant.branch.models import Branch
            from apps.tenant.delivery.models import Delivery

            try:
                if source == 'dooglys':
                    branch = Branch.objects.get(dooglys_branch_id=branch_id)
                else:  # iiko
                    branch = Branch.objects.get(iiko_organization_id=str(branch_id))
            except Branch.DoesNotExist:
                return None
            except Exception as e:
                logger.error(f"Error searching branch in tenant {tenant.schema_name}: {e}")
                return None

            # Нашли ресторан — создаём Delivery
            delivery, created = Delivery.objects.get_or_create(
                code=code,
                branch=branch,
                defaults={'order_source': source},
            )

            if created:
                logger.info(
                    f"Created Delivery code={code} branch={branch} "
                    f"tenant={tenant.schema_name}"
                )
                return Response({'code': delivery.code}, status=status.HTTP_200_OK)

            return Response({
                'error': 'already_exist',
                'msg': 'Такой код уже существует',
            }, status=status.HTTP_400_BAD_REQUEST)
