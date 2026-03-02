import logging

from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db.models import Sum

from apps.tenant.branch.core import ClientService
from apps.tenant.branch.models import ClientBranch, CoinTransaction

from apps.tenant.inventory.models import SuperPrize
from apps.tenant.catalog.models import Product
from apps.tenant.game.models import ClientAttempt, DailyCode, Cooldown
from apps.tenant.delivery.models import Delivery

logger = logging.getLogger(__name__)

class GameService:

    @staticmethod
    def play_game(vk_user_id: int, branch_id: int, code: str = None, employee_id: int = None):
        """
        Основная логика игры.
        """
        logger.info(f"play_game called: vk_user_id={vk_user_id}, branch_id={branch_id}, code={'***' if code else None}")
        # 1. Получаем ID официанта (если передан)
        served_by_client = None
        if employee_id:
             # Ищем сотрудника (предполагаем, что сотрудник - тоже ClientBranch, 
             # либо логика поиска сотрудника должна быть здесь)
             served_by_client = ClientBranch.objects.filter(
                 client__vk_user_id=employee_id, 
                 branch_id=branch_id
             ).first()

        # 2. Получение профиля игрока
        # Важно: transaction.atomic начинается ДО select_for_update
        with transaction.atomic():
            # Получаем клиента и блокируем строку для защиты от накрутки
            client_queryset = ClientService.get_client_profile_queryset(vk_user_id, branch_id)
            locked_client = client_queryset.select_for_update().first()

            if not locked_client:
                 raise ValidationError('Клиент не найден', code='not_found')
            
            # 3. Работа с кулдауном (используем модель из apps.tenant.game)
            cooldown, _ = Cooldown.objects.get_or_create(client=locked_client)

            if cooldown.is_active:
                 raise ValidationError(
                    message=f'Игра перезаряжается. Осталось {int(cooldown.time_left.total_seconds())} сек.',
                    code='cooldown'
                )

            # 4. Считаем попытки
            attempt_num = ClientAttempt.objects.filter(client=locked_client).count() + 1
            
            # --- СЦЕНАРИЙ 1: СУПЕР ПРИЗ (1-я попытка) ---
            # Проверяем, получал ли уже (на случай сброса истории попыток)
            has_super_prize = SuperPrize.objects.filter(
                client=locked_client,
                acquired_from='GAME'
            ).exists()

            if attempt_num == 1 and not has_super_prize:
                logger.info(f"First game for client {locked_client.id}: awarding super prize")
                return GameService._give_super_prize(locked_client, cooldown)

            # --- СЦЕНАРИЙ 2: 2-е посещение — 2000 баллов, код не нужен ---
            if attempt_num == 2:
                logger.info(f"Second game for client {locked_client.id}: awarding 2000 coins")
                return GameService._give_coin_reward(locked_client, cooldown, amount=2000)

            # --- СЦЕНАРИЙ 3: С 3-го посещения — всегда требуем код (кроме delivery) ---
            # Таблица наград: 3-е -> 700, 4-е -> 300, 5-е и далее -> 1000
            is_delivery_user = GameService._check_delivery_user(locked_client)

            if is_delivery_user:
                # Delivery: код не нужен, начисляем по таблице
                logger.info(f"Delivery mode for client {locked_client.id}, attempt #{attempt_num}, skipping code")
                reward = GameService._get_reward_by_attempt(attempt_num)
                return GameService._give_coin_reward(locked_client, cooldown, amount=reward)

            if not code:
                return {'type': 'code', 'reward': None}

            return GameService._give_daily_code_reward(
                locked_client,
                cooldown,
                code,
                branch_id,
                served_by_client,
                attempt_num,
            )

    # --- ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ---

    @staticmethod
    def _give_super_prize(client: ClientBranch, cooldown: Cooldown):
        """
        1. Создаем 'билет' SuperPrize (без товара).
        2. Возвращаем билет и список товаров на выбор.
        """
        
        super_prize = SuperPrize.objects.create(
            client=client,
            product=None, 
            acquired_from='GAME',
        )
        
        ClientAttempt.objects.create(
            client=client, 
        )
        GameService._update_cooldown(cooldown)

        return {
            'type': 'prize', 
            'reward': super_prize,
        }

    @staticmethod
    def _get_reward_by_attempt(attempt_num: int) -> int:
        """Таблица наград по номеру посещения (начиная с 3-го)."""
        if attempt_num == 3:
            return 700
        elif attempt_num == 4:
            return 300
        else:
            return 1000

    @staticmethod
    def _give_coin_reward(client: ClientBranch, cooldown: Cooldown, amount: int):
        """Начисляет указанное количество баллов и фиксирует попытку."""
        CoinTransaction.objects.create_transfer(
            client_branch=client,
            amount=amount,
            transaction_type=CoinTransaction.Type.INCOME,
            source=CoinTransaction.Source.GAME,
            description=f'Победа в игре (+{amount})'
        )
        ClientAttempt.objects.create(client=client)
        GameService._update_cooldown(cooldown)
        return {'type': 'coin', 'reward': amount}

    @staticmethod
    def _give_daily_code_reward(client: ClientBranch, cooldown: Cooldown, code: str, branch_id: int, served_by=None, attempt_num: int = 5):
        """Логика с кодом дня: проверяет код и начисляет баллы по таблице посещений."""

        # 1. Проверка кода
        today = timezone.localdate()
        daily_code = DailyCode.objects.filter(branch_id=branch_id, date=today).first()

        if not daily_code:
            # Автогенерация кода если celery не создал его
            from apps.shared.config.utils import generate_code
            daily_code = DailyCode.objects.create(
                branch_id=branch_id,
                date=today,
                code=generate_code()
            )

        if daily_code.code != code.upper().strip():
            raise ValidationError(message='Неверный код', code='invalid_code')

        # 2. Расчет награды по таблице посещений
        reward = GameService._get_reward_by_attempt(attempt_num)

        CoinTransaction.objects.create_transfer(
            client_branch=client,
            amount=reward,
            transaction_type=CoinTransaction.Type.INCOME,
            source=CoinTransaction.Source.GAME,
            description=f'Победа в игре (+{reward})'
        )

        ClientAttempt.objects.create(
            client=client,
            served_by=served_by
        )
        GameService._update_cooldown(cooldown)

        return {'type': 'coin', 'reward': reward}

    @staticmethod
    def _check_delivery_user(client: ClientBranch) -> bool:
        """
        Проверяет, активировал ли пользователь код доставки.
        Если да — он может пропускать код дня каждую 3-ю игру.
        """
        return Delivery.objects.filter(
            activated_by=client
        ).exists()

    @staticmethod
    def _update_cooldown(cooldown):
        cooldown.last_activated_at = timezone.now()
        cooldown.save(update_fields=['last_activated_at'])


class CooldownService:
    @staticmethod
    def get_cooldown_status(vk_user_id: int, branch_id: int):
        """
        Получает статус перезарядки игры.
        """
        client_profile = ClientService.get_client_profile(vk_user_id, branch_id)
        
        # Ищем кулдаун (безопасно через related_name или прямой запрос)
        if hasattr(client_profile, 'game_cooldown_client'):
            return client_profile.game_cooldown_client
        
        return Cooldown.objects.filter(client=client_profile).first()

    @staticmethod
    def activate_cooldown(vk_user_id: int, branch_id: int):
        """
        Активирует (обновляет) таймер перезарядки вручную.
        """
        client_profile = ClientService.get_client_profile(vk_user_id, branch_id)
        
        cooldown, created = Cooldown.objects.get_or_create(
            client=client_profile,
            defaults={'last_activated_at': timezone.now()}
        )

        if not created:
            cooldown.last_activated_at = timezone.now()
            cooldown.save(update_fields=['last_activated_at'])
            
        return cooldown

    @staticmethod
    def reset_cooldown(vk_user_id: int, branch_id: int):
        """
        Сбрасывает таймер (удаляет запись), позволяя играть снова.
        """
        client_profile = ClientService.get_client_profile(vk_user_id, branch_id)
        
        # Если используем related_name
        if hasattr(client_profile, 'game_cooldown_client'):
            cooldown = client_profile.game_cooldown_client
            # Сохраняем копию данных для возврата (как в старом коде), если нужно
            # Но т.к. мы удаляем, вернем пустую структуру или состояние "не активен"
            cooldown.delete()
            return True # Успешно сброшен
            
        # Прямой поиск
        cooldown = Cooldown.objects.filter(client=client_profile).first()
        if cooldown:
            cooldown.delete()
            return True
            
        return False # Нечего было сбрасывать