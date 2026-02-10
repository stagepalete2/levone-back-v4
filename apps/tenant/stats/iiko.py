"""
IIKO API Service для работы с OLAP отчётами.

Используется для получения количества гостей из ресторанной системы IIKO
и расчёта индекса сканирования QR кодов.

Аутентификация: 
- POST /resto/api/auth с login и password (SHA1)
- Возвращает JWT токен для последующих запросов
"""
import hashlib
import logging
import requests
from typing import Optional, Dict, Any
from datetime import date, datetime

from django_tenants.utils import get_tenant_model

logger = logging.getLogger(__name__)


class IIKOService:
    """
    Сервис для работы с IIKO API.
    
    Конфигурация берётся из CompanyConfig текущего тенанта:
    - iiko_api_url: базовый URL API
    - iiko_api_login: логин
    - iiko_api_password: пароль (шифруется SHA1 при отправке)
    """
    
    def __init__(self, config=None):
        """
        Args:
            config: CompanyConfig instance. Если None, берётся из текущего тенанта.
        """
        self.config = config
        self.token = None
        self.is_configured = False
        
        if self.config:
            self._init_from_config()
        else:
            self._init_from_tenant()
    
    def _init_from_config(self):
        """Инициализация из переданного конфига."""
        if self.config and self.config.iiko_api_url and self.config.iiko_api_login:
            self.base_url = self.config.iiko_api_url.rstrip('/')
            self.login = self.config.iiko_api_login
            self.password = self.config.iiko_api_password or ''
            self.is_configured = True
        else:
            logger.warning("IIKO Service: config missing required fields")
    
    def _init_from_tenant(self):
        """Инициализация из текущего тенанта."""
        try:
            from django.db import connection
            tenant = connection.tenant
            
            if hasattr(tenant, 'config') and tenant.config:
                self.config = tenant.config
                self._init_from_config()
            else:
                logger.warning("IIKO Service: tenant has no config")
        except Exception as e:
            logger.error(f"IIKO Service init error: {e}")
    
    def _hash_password(self, password: str) -> str:
        """SHA1 хэширование пароля для IIKO API."""
        return hashlib.sha1(password.encode('utf-8')).hexdigest()
    
    def _auth(self) -> Optional[str]:
        """
        Аутентификация в IIKO API.
        
        POST /resto/api/auth
        Params: login, pass (SHA1 hash)
        Returns: JWT токен
        """
        if not self.is_configured:
            logger.error("IIKO Service not configured")
            return None
        
        url = f"{self.base_url}/resto/api/auth"
        params = {
            'login': self.login,
            'pass': self._hash_password(self.password)
        }
        
        try:
            response = requests.get(url, params=params, verify=False, timeout=15)
            
            if response.status_code == 200:
                self.token = response.text.strip()
                logger.debug("IIKO auth successful")
                return self.token
            else:
                logger.error(f"IIKO auth failed: {response.status_code} - {response.text}")
                return None
                
        except requests.RequestException as e:
            logger.error(f"IIKO auth connection error: {e}")
            return None
    
    def _make_request(
        self, 
        method: str, 
        endpoint: str, 
        json_data: dict = None,
        params: dict = None
    ) -> Optional[Dict[str, Any]]:
        """
        Выполняет запрос к IIKO API с автоматической аутентификацией.
        """
        # Всегда получаем новый токен (он короткоживущий)
        if not self._auth():
            return None
        
        url = f"{self.base_url}{endpoint}"
        
        # Добавляем токен в параметры
        if params is None:
            params = {}
        params['key'] = self.token
        
        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }
        
        try:
            if method.upper() == 'GET':
                response = requests.get(url, params=params, headers=headers, verify=False, timeout=30)
            elif method.upper() == 'POST':
                response = requests.post(url, params=params, json=json_data, headers=headers, verify=False, timeout=30)
            else:
                raise ValueError(f"Unsupported method: {method}")
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"IIKO API error {endpoint}: {response.status_code} - {response.text}")
                return None
                
        except requests.RequestException as e:
            logger.error(f"IIKO request error: {e}")
            return None
    
    def get_olap_guests_count(
        self, 
        date_from: date = None, 
        date_to: date = None,
        department: str = None
    ) -> Dict[str, int]:
        """
        Получает количество гостей из OLAP отчёта IIKO.
        
        Args:
            date_from: Начало периода (по умолчанию — сегодня)
            date_to: Конец периода (по умолчанию — сегодня)
            department: Фильтр по Department (iiko_organization_id)
        
        Returns:
            Dict с ключами Department и значениями GuestNum
            {"LevOne (Ленина)": 107, "LevOne (Набережная)": 20}
        """
        if not self.is_configured:
            return {}
        
        # Дефолтные даты — сегодня
        if date_from is None:
            date_from = date.today()
        if date_to is None:
            date_to = date.today()
        
        # Форматирование дат
        from_str = date_from.strftime("%Y-%m-%d")
        to_str = date_to.strftime("%Y-%m-%d")
        
        # Тело запроса OLAP
        olap_request = {
            "reportType": "SALES",
            "buildSummary": "false",
            "groupByRowFields": [
                "OpenDate.Typed",
                "Department"
            ],
            "groupByColFields": [],
            "aggregateFields": [
                "GuestNum"
            ],
            "filters": {
                "OpenDate.Typed": {
                    "filterType": "DateRange",
                    "periodType": "CUSTOM",
                    "from": from_str,
                    "to": to_str,
                    "includeLow": True,
                    "includeHigh": True
                }
            }
        }
        
        response = self._make_request('POST', '/resto/api/v2/reports/olap', json_data=olap_request)
        
        if not response or 'data' not in response:
            logger.warning("IIKO OLAP: no data returned")
            return {}
        
        # Агрегируем по Department
        result = {}
        for row in response['data']:
            dept = row.get('Department', 'Unknown')
            guests = row.get('GuestNum', 0)
            
            # Фильтр по department если указан
            if department and department != dept:
                continue
            
            # Суммируем если уже есть (разные даты)
            result[dept] = result.get(dept, 0) + guests
        
        return result
    
    def get_total_guests_today(self, branch=None) -> int:
        """
        Получает общее количество гостей за сегодня.
        
        Args:
            branch: Branch instance для фильтрации по iiko_organization_id
        
        Returns:
            Количество гостей
        """
        department = None
        if branch and branch.iiko_organization_id:
            department = branch.iiko_organization_id
        
        guests_by_dept = self.get_olap_guests_count(department=department)
        
        if department:
            return guests_by_dept.get(department, 0)
        else:
            return sum(guests_by_dept.values())
    
    def calculate_scan_index(self, qr_scans: int, iiko_guests: int) -> float:
        """
        Вычисляет индекс сканирования QR кода.
        
        Формула: (QR сканы / IIKO гости) * 100
        
        Returns:
            Процент (0-100+), или 0 если нет данных
        """
        if iiko_guests == 0:
            return 0.0
        
        index = (qr_scans / iiko_guests) * 100
        return round(index, 2)
