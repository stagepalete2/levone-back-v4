"""
VK Mini Apps Launch Params верификация.

Этот модуль проверяет подпись VK launch parameters по алгоритму:
https://dev.vk.com/mini-apps/development/launch-params-sign

ВАЖНО: Работает ОПЦИОНАЛЬНО — если заголовок X-Launch-Params не передан,
запрос пропускается как раньше. Это сделано для обратной совместимости.
Когда фронтенд будет обновлён — можно сделать проверку обязательной.
"""

import hmac
import hashlib
import base64
import logging
from collections import OrderedDict
from urllib.parse import urlencode, parse_qs, unquote

from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

logger = logging.getLogger(__name__)


class VKLaunchParamsUser:
    """
    Обёртка для VK user — используется DRF как request.user
    когда launch params верифицированы.
    """
    def __init__(self, vk_user_id):
        self.vk_user_id = int(vk_user_id)
        self.pk = self.vk_user_id
        self.is_authenticated = True
        self.is_active = True
        self.is_staff = False
        self.is_superuser = False

    def __str__(self):
        return f"VKUser({self.vk_user_id})"


def verify_vk_launch_params(query_string, vk_secret):
    """
    Проверяет подпись VK launch params.

    Алгоритм VK:
    1. Берём все параметры, которые начинаются с 'vk_'
    2. Сортируем их по ключу
    3. Формируем query string
    4. Вычисляем HMAC-SHA256 с секретом приложения
    5. Кодируем в base64url (без padding '=')
    6. Сравниваем с параметром 'sign'

    Returns:
        dict с параметрами если подпись верна, None если нет
    """
    if not query_string or not vk_secret:
        return None

    # Парсим параметры
    try:
        params = parse_qs(query_string, keep_blank_values=True)
    except Exception:
        return None

    # Извлекаем sign
    sign_values = params.get('sign')
    if not sign_values:
        return None
    sign = sign_values[0]

    # Оставляем только vk_* параметры, сортируем по ключу
    vk_params = OrderedDict(
        sorted(
            (k, v[0]) for k, v in params.items()
            if k.startswith('vk_')
        )
    )

    if not vk_params:
        return None

    # Формируем строку для подписи
    params_string = urlencode(vk_params)

    # HMAC-SHA256
    hash_code = hmac.new(
        vk_secret.encode('utf-8'),
        params_string.encode('utf-8'),
        hashlib.sha256
    ).digest()

    # base64url без padding
    expected_sign = (
        base64.urlsafe_b64encode(hash_code)
        .decode('utf-8')
        .rstrip('=')
    )

    # Безопасное сравнение (защита от timing attack)
    if hmac.compare_digest(sign, expected_sign):
        return dict(vk_params)

    return None


class VKMiniAppAuthentication(BaseAuthentication):
    """
    DRF Authentication class для VK Mini Apps.

    Ищет VK launch params в заголовке X-Launch-Params.
    Если заголовок есть — верифицирует подпись.
    Если заголовка нет — возвращает None (пропускает, чтобы не ломать текущий код).

    Использование в settings.py:
        REST_FRAMEWORK = {
            'DEFAULT_AUTHENTICATION_CLASSES': [
                'apps.shared.config.vk_auth.VKMiniAppAuthentication',
                'rest_framework.authentication.SessionAuthentication',
            ],
        }
    """

    def authenticate(self, request):
        # Берём launch params из заголовка
        launch_params = request.META.get('HTTP_X_LAUNCH_PARAMS', '')

        if not launch_params:
            # Нет заголовка — пропускаем (обратная совместимость)
            # Текущий код продолжает работать без изменений
            return None

        vk_secret = getattr(settings, 'VK_SECRET', None)
        if not vk_secret:
            logger.warning("VK_SECRET не задан в settings — пропускаю верификацию")
            return None

        # Декодируем URL-encoded строку если нужно
        decoded_params = unquote(launch_params)

        verified = verify_vk_launch_params(decoded_params, vk_secret)

        if verified is None:
            # Подпись невалидна
            raise AuthenticationFailed(
                'Невалидная подпись VK launch params. '
                'Убедитесь, что приложение запущено из VK.'
            )

        vk_user_id = verified.get('vk_user_id')
        if not vk_user_id:
            raise AuthenticationFailed('vk_user_id отсутствует в launch params')

        user = VKLaunchParamsUser(vk_user_id)
        return (user, verified)

    def authenticate_header(self, request):
        return 'VK-Launch-Params'
