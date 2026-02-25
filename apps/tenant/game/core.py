import logging

from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError

from apps.tenant.branch.core import ClientService
from apps.tenant.branch.models import ClientBranch, CoinTransaction

from apps.tenant.inventory.models import SuperPrize
from apps.tenant.game.models import ClientAttempt, DailyCode, Cooldown

logger = logging.getLogger(__name__)


class _RewardTable:
    """Таблица начисления баллов по номеру посещения."""
    VISIT_REWARDS = {
        2: 2000,
        3: 700,
        4: 300,
    }
    # Начиная с 5-го посещения — 1000 баллов за каждое
    DEFAULT_REWARD = 1000


class GameService:

    @staticmethod
    def play_game(vk_user_id: int, branch_id: int, code: str = None, employee_id: int = None):
        """
        Основная логика игры.

        Логика начисления баллов:
          1-е посещение  → Супер приз (остаётся навсегда)
          2-е посещение  → 2000 баллов
          3-е посещение  → 700 баллов
          4-е посещение  → 300 баллов
          5-е и далее    → 1000 баллов за каждое
        """
        logger.info(f"play_game called: vk_user_id={vk_user_id}, branch_id={branch_id}")

        # 1. Получаем ID официанта (если передан)
        served_by_client = None
        if employee_id:
            served_by_client = ClientBranch.objects.filter(
                client__vk_user_id=employee_id,
                branch_id=branch_id
            ).first()

        with transaction.atomic():
            # 2. Получаем клиента с блокировкой строки против накрутки
            client_queryset = ClientService.get_client_profile_queryset(vk_user_id, branch_id)
            locked_client = client_queryset.select_for_update().first()

            if not locked_client:
                raise ValidationError('Клиент не найден', code='not_found')

            # 3. Проверяем кулдаун
            cooldown, _ = Cooldown.objects.get_or_create(client=locked_client)

            if cooldown.is_active:
                raise ValidationError(
                    message=f'Игра перезаряжается. Осталось {int(cooldown.time_left.total_seconds())} сек.',
                    code='cooldown'
                )

            # 4. Номер текущего посещения (уже совершённые + 1)
            attempt_num = ClientAttempt.objects.filter(client=locked_client).count() + 1
            logger.info(f"Client {locked_client.id}: visit #{attempt_num}")

            # --- ПОСЕЩЕНИЕ 1: СУПЕР ПРИЗ ---
            has_super_prize = SuperPrize.objects.filter(
                client=locked_client,
                acquired_from='GAME'
            ).exists()

            if attempt_num == 1 and not has_super_prize:
                logger.info(f"First visit for client {locked_client.id}: awarding super prize")
                return GameService._give_super_prize(locked_client, cooldown)

            # --- ПОСЕЩЕНИЕ 2: 2000 баллов, код не нужен ---
            if attempt_num == 2:
                logger.info(f"Client {locked_client.id}: visit #2 → 2000 coins (no code required)")
                return GameService._give_coin_reward(locked_client, cooldown, 2000, served_by_client)

            # --- ПОСЕЩЕНИЯ 3 И ДАЛЕЕ: всегда требуется код дня ---
            # Определяем сумму по номеру посещения: 3→700, 4→300, 5+→1000
            reward_amount = _RewardTable.VISIT_REWARDS.get(attempt_num, _RewardTable.DEFAULT_REWARD)

            if not code:
                logger.info(f"Client {locked_client.id}: visit #{attempt_num}, code required")
                return {'type': 'code_required', 'reward': None}

            logger.info(f"Client {locked_client.id}: visit #{attempt_num} → {reward_amount} coins (with code)")
            return GameService._give_daily_code_reward(
                locked_client, cooldown, code, branch_id, reward_amount, served_by_client
            )

    # --- ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ---

    @staticmethod
    def _give_super_prize(client: ClientBranch, cooldown: Cooldown):
        """
        1-е посещение: создаём «билет» SuperPrize (без товара).
        Возвращаем билет и список товаров на выбор.
        """
        super_prize = SuperPrize.objects.create(
            client=client,
            product=None,
            acquired_from='GAME',
        )

        ClientAttempt.objects.create(client=client)
        GameService._update_cooldown(cooldown)

        return {
            'type': 'prize',
            'reward': super_prize,
        }

    @staticmethod
    def _give_coin_reward(client: ClientBranch, cooldown: Cooldown, amount: int, served_by=None):
        """
        Начисляем баллы согласно таблице посещений:
          2-е → 2000, 3-е → 700, 4-е → 300, 5-е и далее → 1000.
        """
        CoinTransaction.objects.create_transfer(
            client_branch=client,
            amount=amount,
            transaction_type=CoinTransaction.Type.INCOME,
            source=CoinTransaction.Source.GAME,
            description=f'Победа в игре (+{amount})'
        )

        ClientAttempt.objects.create(client=client, served_by=served_by)
        GameService._update_cooldown(cooldown)

        return {'type': 'coin', 'reward': amount}

    @staticmethod
    def _give_daily_code_reward(
        client: ClientBranch,
        cooldown: Cooldown,
        code: str,
        branch_id: int,
        amount: int,
        served_by=None
    ):
        """
        С 3-го посещения и далее — проверяем код дня, затем начисляем баллы.
          3-е → 700, 4-е → 300, 5-е и далее → 1000.
        """
        today = timezone.localdate()
        daily_code = DailyCode.objects.filter(branch_id=branch_id, date=today).first()

        if not daily_code:
            raise ValidationError(message='Код дня ещё не создан', code='code_not_set')

        if daily_code.code != code.upper().strip():
            raise ValidationError(message='Неверный код', code='invalid_code')

        CoinTransaction.objects.create_transfer(
            client_branch=client,
            amount=amount,
            transaction_type=CoinTransaction.Type.INCOME,
            source=CoinTransaction.Source.GAME,
            description=f'Победа в игре (+{amount})'
        )

        ClientAttempt.objects.create(client=client, served_by=served_by)
        GameService._update_cooldown(cooldown)

        return {'type': 'coin', 'reward': amount}

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
    