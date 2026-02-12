"""
Dooglys API Service для получения данных о гостях.

Используется для получения количества гостей из системы Dooglys
и расчёта индекса сканирования QR кодов.

API Endpoint: https://dooglys.com/api/v1/
"""
import logging
import requests
from typing import Optional, Dict, Any
from datetime import date, datetime, timedelta

from django_tenants.utils import get_tenant_model

logger = logging.getLogger(__name__)


class DooglysService:
    """
    Сервис для работы с Dooglys API.
    
    Конфигурация берётся из CompanyConfig текущего тенанта:
    - dooglys_api_url: базовый URL API (по умолчанию https://dooglys.com/api/v1)
    - dooglys_api_token: API токен для аутентификации
    """
    
    DEFAULT_API_URL = "https://dooglys.com/api/v1"
    
    def __init__(self, config=None):
        """
        Args:
            config: CompanyConfig instance. Если None, берётся из текущего тенанта.
        """
        self.config = config
        self.api_token = None
        self.is_configured = False
        
        if self.config:
            self._init_from_config()
        else:
            self._init_from_tenant()
    
    def _init_from_config(self):
        """Инициализация из переданного конфига."""
        if self.config and hasattr(self.config, 'dooglys_api_token') and self.config.dooglys_api_token:
            self.base_url = getattr(self.config, 'dooglys_api_url', self.DEFAULT_API_URL).rstrip('/')
            self.api_token = self.config.dooglys_api_token
            self.is_configured = True
        else:
            logger.warning("Dooglys Service: config missing API token")
    
    def _init_from_tenant(self):
        """Инициализация из текущего тенанта."""
        try:
            from django.db import connection
            tenant = connection.tenant
            
            if hasattr(tenant, 'config') and tenant.config:
                self.config = tenant.config
                self._init_from_config()
            else:
                logger.warning("Dooglys Service: tenant has no config")
        except Exception as e:
            logger.error(f"Dooglys Service init error: {e}")
    
    def _make_request(
        self, 
        method: str, 
        endpoint: str, 
        json_data: dict = None,
        params: dict = None
    ) -> Optional[Dict[str, Any]]:
        """
        Выполняет запрос к Dooglys API.
        """
        if not self.is_configured:
            logger.error("Dooglys Service not configured")
            return None
        
        url = f"{self.base_url}{endpoint}"
        
        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.api_token}'
        }
        
        try:
            if method.upper() == 'GET':
                response = requests.get(url, params=params, headers=headers, timeout=30)
            elif method.upper() == 'POST':
                response = requests.post(url, params=params, json=json_data, headers=headers, timeout=30)
            else:
                raise ValueError(f"Unsupported method: {method}")
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Dooglys API error {endpoint}: {response.status_code} - {response.text}")
                return None
                
        except requests.RequestException as e:
            logger.error(f"Dooglys request error: {e}")
            return None
    
    def get_guests_count(
        self, 
        date_from: date = None, 
        date_to: date = None,
        branch_id: int = None
    ) -> Dict[int, int]:
        """
        Получает количество гостей из Dooglys.
        
        Args:
            date_from: Начало периода (по умолчанию — вчера)
            date_to: Конец периода (по умолчанию — вчера)
            branch_id: Фильтр по конкретному филиалу (dooglys_branch_id)
        
        Returns:
            Dict с ключами branch_id и значениями количество гостей
            {1: 107, 2: 20}
        """
        if not self.is_configured:
            return {}
        
        # Дефолтные даты — вчера (так как данные за сегодня могут быть неполными)
        if date_from is None:
            date_from = date.today() - timedelta(days=1)
        if date_to is None:
            date_to = date.today() - timedelta(days=1)
        
        # Параметры запроса
        params = {
            'date_from': date_from.strftime("%Y-%m-%d"),
            'date_to': date_to.strftime("%Y-%m-%d"),
        }
        
        if branch_id:
            params['branch_id'] = branch_id
        
        # Запрос к API
        response = self._make_request('GET', '/guests/count', params=params)
        
        if not response or 'data' not in response:
            logger.warning("Dooglys: no data returned")
            return {}
        
        # Формируем результат
        result = {}
        for item in response['data']:
            bid = item.get('branch_id')
            count = item.get('guests_count', 0)
            if bid:
                result[bid] = result.get(bid, 0) + count
        
        return result
    
    def get_total_guests_today(self, branch=None) -> int:
        """
        Получает общее количество гостей за вчера (или сегодня, если указано).
        
        Args:
            branch: Branch instance для фильтрации по dooglys_branch_id
        
        Returns:
            Количество гостей
        """
        branch_id = None
        if branch and branch.dooglys_branch_id:
            branch_id = branch.dooglys_branch_id
        
        # Получаем данные за вчера (так как за сегодня данные могут быть неполными)
        yesterday = date.today() - timedelta(days=1)
        guests_by_branch = self.get_guests_count(
            date_from=yesterday,
            date_to=yesterday,
            branch_id=branch_id
        )
        
        if branch_id:
            return guests_by_branch.get(branch_id, 0)
        else:
            return sum(guests_by_branch.values())
    
    def calculate_scan_index(self, qr_scans: int, dooglys_guests: int) -> float:
        """
        Вычисляет индекс сканирования QR кода.
        
        Формула: (QR сканы / Dooglys гости) * 100
        
        Returns:
            Процент (0-100+), или 0 если нет данных
        """
        if dooglys_guests == 0:
            return 0.0
        
        index = (qr_scans / dooglys_guests) * 100
        return round(index, 2)