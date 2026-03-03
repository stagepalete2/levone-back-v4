from django.utils.timezone import now
from django.core.exceptions import ValidationError
from apps.shared.clients.models import Company, Domain

class CompanyDomainService:
    @staticmethod
    def get_company_domain_by_client_id(client_id):
        """
        Принимает client_id, находит Company, проверяет доступы и возвращает объект Domain.
        Если что-то не так — выбрасывает исключение с понятным кодом.
        """
        try:
            company = Company.objects.get(client_id=client_id)
        except Company.DoesNotExist:
            raise ValidationError(
                message='Компания не найдена',
                code='not_found'
            )

        if not company.is_active:
            raise ValidationError(
                message='Компания неактивна', 
                code='inactive'
            )

        if company.paid_until is not None and company.paid_until < now().date():
            raise ValidationError(
                message='Период оплаты истек', 
                code='unpaid'
            )

        domain = Domain.objects.select_related('tenant').filter(tenant=company).first()
        if not domain:
            raise ValidationError(
                message='Домен не найден', 
                code='not_found'
            )
            
        return domain

    @staticmethod
    def get_company_domain(company):
        """
        Принимает объект Company, проверяет доступы и возвращает объект Domain.
        Если что-то не так — выбрасывает исключение с понятным кодом.
        """
        
        if not company.is_active:
            raise ValidationError(
                message='Компания неактивна', 
                code='inactive'
            )

        if company.paid_until is not None and company.paid_until < now().date():
            raise ValidationError(
                message='Период оплаты истек', 
                code='unpaid'
            )

        domain = Domain.objects.select_related('tenant').filter(tenant=company).first()
        if not domain:
            raise ValidationError(
                message='Домен не найден', 
                code='not_found'
            )
            
        return domain