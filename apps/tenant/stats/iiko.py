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
from datetime import date, datetime, timedelta

from django_tenants.utils import get_tenant_model

logger = logging.getLogger(__name__)

# Кэш токенов: {(base_url, login): (token, expires_at)}
# Токен живёт 15 минут в IIKO — кэшируем чтобы не создавать новое
# соединение на каждый запрос (иначе лицензионные слоты быстро кончаются).
_token_cache: dict = {}
_TOKEN_TTL_SECONDS = 14 * 60  # 14 минут (с запасом до истечения 15 мин)


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
        Аутентификация в IIKO API с кэшированием токена.

        Токен кэшируется на уровне модуля на 14 минут (IIKO выдаёт на 15).
        Это предотвращает 403 "no connections available" при множественных
        вызовах — каждый вызов _make_request больше не создаёт новое соединение.
        """
        if not self.is_configured:
            logger.error("IIKO Service not configured")
            return None

        cache_key = (self.base_url, self.login)
        now = datetime.utcnow()

        # Проверяем кэш
        if cache_key in _token_cache:
            cached_token, expires_at = _token_cache[cache_key]
            if now < expires_at:
                self.token = cached_token
                logger.debug("IIKO auth: using cached token (expires in %ds)",
                             (expires_at - now).seconds)
                return self.token
            else:
                logger.debug("IIKO auth: cached token expired, re-authenticating")
                del _token_cache[cache_key]

        # Запрашиваем новый токен
        url = f"{self.base_url}/resto/api/auth"
        params = {
            'login': self.login,
            'pass': self._hash_password(self.password)
        }

        try:
            response = requests.get(url, params=params, verify=False, timeout=15)

            if response.status_code == 200:
                self.token = response.text.strip()
                _token_cache[cache_key] = (
                    self.token,
                    now + timedelta(seconds=_TOKEN_TTL_SECONDS)
                )
                logger.debug("IIKO auth: new token obtained and cached for %ds", _TOKEN_TTL_SECONDS)
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
        Токен кэшируется внутри экземпляра — повторный _auth() не вызывается,
        если токен уже получен. Это экономит соединения (лицензия IIKO ограничена).
        """
        # Используем уже полученный токен; авторизуемся только если его ещё нет
        if not self.token:
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
            Dict с ключами Department.Id (UUID) и значениями UniqOrderId.OrdersCount (кол-во чеков)
            {"7e37024d-64e4-4399-9b61-e40b0cc466cf": 107, "7b380190-5650-c31e-017c-5b33b9f90011": 20}
        """
        if not self.is_configured:
            return {}
        
        # Дефолтные даты — сегодня
        if date_from is None:
            date_from = date.today() - timedelta(days=1)
        if date_to is None:
            date_to = date.today() - timedelta(days=1)
        
        # Форматирование дат
        from_str = date_from.strftime("%Y-%m-%d")
        to_str = date_to.strftime("%Y-%m-%d")
        
        # Тело запроса OLAP
        # UniqOrderId.OrdersCount — количество уникальных чеков/заказов.
        # Это правильная метрика для индекса сканирования: 1 чек = 1 визит = 1 возможность скана QR.
        # GuestNum (кол-во гостей за столиком) НЕ используем — кассиры вводят вручную,
        # может быть 0, 1, 5 на один чек → искажает статистику в разы.
        olap_request = {
            "reportType": "SALES",
            "buildSummary": "false",
            "groupByRowFields": [
                "Department",
                "Department.Id"
            ],
            "groupByColFields": [],
            "aggregateFields": [
                "UniqOrderId.OrdersCount"
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
        
        # Агрегируем по Department.Id (UUID) — именно он хранится в Branch.iiko_organization_id.
        # Department (строка-имя) НЕ используем как ключ — она не совпадает с UUID из БД.
        result = {}
        for row in response['data']:
            dept_id   = row.get('Department.Id', '')   # UUID — надёжный ключ
            dept_name = row.get('Department', '')       # Имя — только для логов
            guests    = row.get('UniqOrderId.OrdersCount', 0)   # кол-во уникальных чеков

            if not dept_id:
                logger.warning("IIKO OLAP: строка без Department.Id: %s", row)
                continue

            # Фильтр по UUID department если указан
            if department and department != dept_id:
                continue

            # Суммируем одинаковые dept_id (разные даты в группировке)
            result[dept_id] = result.get(dept_id, 0) + guests
            logger.debug('IIKO OLAP row: dept_id=%s name=%s orders=%s', dept_id, dept_name, guests)

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