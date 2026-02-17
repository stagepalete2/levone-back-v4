"""
Dooglys API Service для получения данных о гостях.

Используется для получения количества заказов (= гостей) из системы Dooglys
через эндпоинт /sales/order/list с пагинацией.

API Endpoint: https://dooglys.com/api/v1/
Аутентификация: заголовки Tenant-Domain + Access-Token
Количество чеков: X-Pagination-Total-Count из Response Headers
"""
import logging
import requests
from typing import Optional, Dict, Any, Tuple
from datetime import date, datetime, timedelta

logger = logging.getLogger(__name__)


class DooglysService:
    """
    Сервис для работы с Dooglys API.

    Конфигурация берётся из CompanyConfig текущего тенанта:
    - dooglys_api_url:    базовый URL (по умолчанию https://dooglys.com/api/v1)
    - dooglys_api_token:  Access-Token для аутентификации
    - dooglys_tenant_domain: Tenant-Domain (домен тенанта в Dooglys)
    """

    DEFAULT_API_URL = "https://dooglys.com/api/v1"

    def __init__(self, config=None):
        """
        Args:
            config: CompanyConfig instance. Если None — берётся из текущего тенанта.
        """
        self.config = config
        self.api_token = None
        self.tenant_domain = None
        self.is_configured = False

        if self.config:
            self._init_from_config()
        else:
            self._init_from_tenant()

    # ──────────────────────────────────────────────────
    # Инициализация
    # ──────────────────────────────────────────────────

    def _init_from_config(self):
        """Инициализация из переданного конфига."""
        token = getattr(self.config, 'dooglys_api_token', None)
        domain = getattr(self.config, 'dooglys_tenant_domain', None)

        if token:
            raw_url = getattr(
                self.config, 'dooglys_api_url', self.DEFAULT_API_URL
            ) or self.DEFAULT_API_URL

            # Нормализуем URL: убираем trailing slash, затем гарантируем /api/v1 в конце.
            # Это защита от двух вариантов заполнения в конфиге:
            #   "https://shavermaleo.dooglys.com"        → добавляем /api/v1
            #   "https://shavermaleo.dooglys.com/api/v1" → оставляем как есть
            raw_url = raw_url.rstrip('/')
            if not raw_url.endswith('/api/v1'):
                raw_url = raw_url + '/api/v1'

            self.base_url = raw_url
            self.api_token = token
            self.tenant_domain = domain or ''
            self.is_configured = True
            logger.debug("DooglysService base_url: %s", self.base_url)
        else:
            logger.warning("DooglysService: config не содержит dooglys_api_token")

    def _init_from_tenant(self):
        """Инициализация из текущего тенанта (django-tenants)."""
        try:
            from django.db import connection
            tenant = connection.tenant

            if hasattr(tenant, 'config') and tenant.config:
                self.config = tenant.config
                self._init_from_config()
            else:
                logger.warning("DooglysService: у тенанта нет config")
        except Exception as exc:
            logger.error("DooglysService init error: %s", exc)

    # ──────────────────────────────────────────────────
    # HTTP
    # ──────────────────────────────────────────────────

    def _build_headers(self) -> dict:
        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'Access-Token': self.api_token,
        }
        if self.tenant_domain:
            headers['Tenant-Domain'] = self.tenant_domain
        return headers

    def _make_request(
        self,
        method: str,
        endpoint: str,
        params: dict = None,
        json_data: dict = None,
    ) -> Optional[Tuple[Dict[str, Any], Dict[str, str]]]:
        """
        Выполняет запрос к Dooglys API.

        Returns:
            Tuple (response_body_dict, response_headers_dict) или None при ошибке.
        """
        if not self.is_configured:
            logger.error("DooglysService не настроен")
            return None

        url = f"{self.base_url}{endpoint}"
        headers = self._build_headers()

        try:
            if method.upper() == 'GET':
                response = requests.get(
                    url, params=params, headers=headers, timeout=30
                )
            elif method.upper() == 'POST':
                response = requests.post(
                    url, params=params, json=json_data, headers=headers, timeout=30
                )
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            if response.status_code == 200:
                try:
                    body = response.json()
                except ValueError:
                    body = {}
                # ВАЖНО: НЕ конвертируем в dict() — requests.CaseInsensitiveDict
                # сохраняет регистронезависимый доступ к заголовкам.
                # HTTP/2 и большинство прокси возвращают заголовки в нижнем регистре,
                # поэтому dict(response.headers) сломает поиск 'X-Pagination-Total-Count'.
                return body, response.headers

            logger.error(
                "DooglysService %s %s → %s: %s",
                method, endpoint, response.status_code, response.text[:300],
            )
            return None

        except requests.RequestException as exc:
            logger.error("DooglysService request error: %s", exc)
            return None

    # ──────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────

    @staticmethod
    def _to_unix(dt: datetime) -> int:
        """Конвертирует datetime → Unix Timestamp (целое число)."""
        import calendar
        return int(calendar.timegm(dt.utctimetuple()))

    @staticmethod
    def _day_bounds(target_date: date) -> Tuple[datetime, datetime]:
        """Возвращает (начало суток, конец суток) для заданного дня (UTC)."""
        start = datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0)
        end   = datetime(target_date.year, target_date.month, target_date.day, 23, 59, 59)
        return start, end

    # ──────────────────────────────────────────────────
    # Основные методы
    # ──────────────────────────────────────────────────

    def get_orders_count(
        self,
        date_from: date = None,
        date_to: date = None,
        branch_id: int = None,
    ) -> int:
        """
        Возвращает количество заказов (чеков) за период через /sales/order/list.

        Dooglys использует пагинацию; реальное количество записей
        возвращается в заголовке ответа X-Pagination-Total-Count —
        именно его мы и возвращаем (без необходимости обходить все страницы).

        Args:
            date_from: Дата начала периода (включительно). По умолчанию — сегодня.
            date_to:   Дата конца периода (включительно). По умолчанию — сегодня.
            branch_id: Внутренний Dooglys branch_id для фильтрации по филиалу.

        Returns:
            Количество заказов (int). 0 при ошибке или отсутствии данных.
        """
        if not self.is_configured:
            return 0

        today = date.today()
        if date_from is None:
            date_from = today
        if date_to is None:
            date_to = today

        # Формируем Unix Timestamps: начало date_from … конец date_to
        start_dt, _    = self._day_bounds(date_from)
        _, end_dt      = self._day_bounds(date_to)

        params: dict = {
            'date_accepted_from': start_dt.strftime('%Y-%m-%d %H:%M:%S'),
            'date_accepted_to': end_dt.strftime('%Y-%m-%d %H:%M:%S'),
            'per-page':  1,
            'page':      1,
        }

        if branch_id:
            params['sale_point_id'] = branch_id

        result = self._make_request('GET', '/sales/order/list', params=params)
        if result is None:
            logger.warning(
                "DooglysService: нет ответа от /sales/order/list (sale_point_id=%s)", branch_id
            )
            return 0

        _, headers = result

        # Количество заказов — в заголовке пагинации.
        # CaseInsensitiveDict (requests) обрабатывает регистр автоматически,
        # но добавляем явный fallback на lowercase на случай нестандартных реализаций.
        total_str = (
            headers.get('X-Pagination-Total-Count')
            or headers.get('x-pagination-total-count')
            or '0'
        )

        logger.debug(
            "DooglysService: response headers keys: %s",
            list(headers.keys()),
        )
        try:
            total = int(total_str)
        except (ValueError, TypeError):
            logger.warning(
                "DooglysService: не удалось разобрать X-Pagination-Total-Count='%s'", total_str
            )
            total = 0

        logger.debug(
            "DooglysService: %d заказов за %s–%s (branch_id=%s)",
            total, date_from, date_to, branch_id,
        )
        return total

    def get_guests_count(
        self,
        date_from: date = None,
        date_to: date = None,
        branch_id: int = None,
    ) -> Dict[int, int]:
        """
        Получает количество гостей из Dooglys в разбивке по филиалам.

        Если branch_id указан — возвращает {branch_id: count}.
        Иначе — {branch_id: count} для всех.

        Примечание: при запросе без branch_id Dooglys вернёт общий счётчик.
        Для детализации по каждому филиалу вызовите метод отдельно для каждого.

        Returns:
            {dooglys_branch_id: guests_count}
        """
        count = self.get_orders_count(
            date_from=date_from,
            date_to=date_to,
            branch_id=branch_id,
        )

        if branch_id:
            return {branch_id: count}

        # Без branch_id — возвращаем под ключом 0 (общий итог)
        return {0: count} if count else {}

    def get_total_guests_today(self, branch=None) -> int:
        """
        Возвращает количество заказов (гостей) за СЕГОДНЯ.

        Args:
            branch: Branch instance. Используется branch.dooglas_sale_point_id для фильтрации.

        Returns:
            Количество заказов (int).
        """
        branch_id = None
        if branch and getattr(branch, 'dooglas_sale_point_id', None):
            branch_id = branch.dooglas_sale_point_id

        today = date.today()
        return self.get_orders_count(
            date_from=today,
            date_to=today,
            branch_id=branch_id,
        )

    def get_guests_for_period(
        self,
        date_from: date,
        date_to: date,
        branch=None,
    ) -> int:
        """
        Возвращает количество заказов за произвольный период.

        Args:
            date_from: Начало периода.
            date_to:   Конец периода.
            branch:    Branch instance для фильтрации (опционально).

        Returns:
            Количество заказов (int).
        """
        branch_id = None
        if branch and getattr(branch, 'dooglas_sale_point_id', None):
            branch_id = branch.dooglas_sale_point_id

        return self.get_orders_count(
            date_from=date_from,
            date_to=date_to,
            branch_id=branch_id,
        )

    # ──────────────────────────────────────────────────
    # Индекс сканирования
    # ──────────────────────────────────────────────────

    @staticmethod
    def calculate_scan_index(qr_scans: int, dooglys_guests: int) -> float:
        """
        Вычисляет индекс сканирования QR-кода.

        Формула: (QR сканы / Dooglys заказы) × 100

        Returns:
            Процент (float, 0–100+). 0 если нет данных.
        """
        if dooglys_guests <= 0:
            return 0.0
        return round((qr_scans / dooglys_guests) * 100, 2)