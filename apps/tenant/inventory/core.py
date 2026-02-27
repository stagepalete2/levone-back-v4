import logging
from django.db import transaction
from django.utils import timezone
import datetime
from django.db.models import Q, F
from django.core.exceptions import ValidationError

logger = logging.getLogger(__name__)

from apps.tenant.branch.core import ClientService
from apps.tenant.catalog.models import Product
from apps.tenant.inventory.models import Inventory, SuperPrize, Cooldown

# Окно ДР: за 5 дней до и 5 дней после включительно
BIRTHDAY_WINDOW_BEFORE = 5
BIRTHDAY_WINDOW_AFTER = 5


def _is_in_birthday_window(birth_date, reference_date=None):
    """
    Проверяет, попадает ли reference_date (по умолчанию сегодня) в окно ДР
    [birthday - BEFORE, birthday + AFTER].
    Учитывает переход года (например ДР 1 января, сегодня 29 декабря).
    Возвращает (bool, date) — True если в окне, и саму дату ДР этого/следующего года.
    """
    if not birth_date:
        return False, None

    today = reference_date or timezone.now().date()

    for year_offset in (0, 1, -1):
        try:
            bday_this = birth_date.replace(year=today.year + year_offset)
        except ValueError:
            # 29 февраля → 28 февраля в невисокосный год
            bday_this = birth_date.replace(year=today.year + year_offset, day=28)

        window_start = bday_this - datetime.timedelta(days=BIRTHDAY_WINDOW_BEFORE)
        window_end   = bday_this + datetime.timedelta(days=BIRTHDAY_WINDOW_AFTER)

        if window_start <= today <= window_end:
            return True, bday_this

    return False, None


class InventoryService:

    @staticmethod
    def get_client_inventory(vk_user_id: int, branch_id: int):
        """
        Получает активный инвентарь (не просроченный).
        """
        client_profile = ClientService.get_client_profile(vk_user_id, branch_id)
        
        now = timezone.now()
        
        inventory = Inventory.objects.filter(
            client=client_profile
        ).select_related('product').filter(
            Q(activated_at__isnull=True) |
            Q(activated_at__gte=now - F('duration'))
        ).order_by('-created_at')
        
        return inventory

    # ------------------------------------------------------------------
    # BIRTHDAY PRIZE — выдача
    # ------------------------------------------------------------------

    @staticmethod
    def grant_birthday_prize_single(client_branch):
        """
        Проверяет, попадает ли сегодня в окно ±5 дней от ДР клиента.
        Если да — выдаёт SuperPrize(acquired_from='BIRTHDAY').
        Возвращает True если подарок создан.
        """
        in_window, _ = _is_in_birthday_window(client_branch.birth_date)
        if not in_window:
            return False

        today = timezone.now().date()
        year_start = datetime.date(today.year, 1, 1)
        year_end   = datetime.date(today.year, 12, 31)

        exists = SuperPrize.objects.filter(
            client=client_branch,
            acquired_from='BIRTHDAY',
            created_at__date__gte=year_start,
            created_at__date__lte=year_end,
        ).exists()

        if not exists:
            SuperPrize.objects.create(
                client=client_branch,
                acquired_from='BIRTHDAY',
                product=None,
                activated_at=None,
            )
            logger.info(f"Granted BIRTHDAY prize to {client_branch}")
            return True

        return False

    @staticmethod
    def grant_birthday_prizes_batch(target_date):
        """
        Выдаёт SuperPrize всем клиентам, у которых ДР в target_date.
        target_date — конкретная дата (обычно сегодня+7 или сегодня).
        """
        from apps.tenant.branch.models import ClientBranch

        birthday_clients = ClientBranch.objects.filter(
            birth_date__month=target_date.month,
            birth_date__day=target_date.day,
        )

        year_start = datetime.date(timezone.now().year, 1, 1)
        year_end   = datetime.date(timezone.now().year, 12, 31)
        created_count = 0

        for cb in birthday_clients:
            exists = SuperPrize.objects.filter(
                client=cb,
                acquired_from='BIRTHDAY',
                created_at__date__gte=year_start,
                created_at__date__lte=year_end,
            ).exists()

            if not exists:
                SuperPrize.objects.create(
                    client=cb,
                    acquired_from='BIRTHDAY',
                    product=None,
                    activated_at=None,
                )
                created_count += 1

        return created_count

    @staticmethod
    def revoke_expired_birthday_prizes():
        """
        Удаляет не активированные BIRTHDAY SuperPrize у тех, чьё окно ±5 дней уже закрылось.
        Запускается ежедневно: ищем именинников 5+1=6 дней назад.
        """
        today = timezone.now().date()
        expired_bday = today - datetime.timedelta(days=BIRTHDAY_WINDOW_AFTER + 1)

        expired_prizes = SuperPrize.objects.filter(
            acquired_from='BIRTHDAY',
            activated_at__isnull=True,
            client__birth_date__month=expired_bday.month,
            client__birth_date__day=expired_bday.day,
        )

        count, _ = expired_prizes.delete()
        return count

    # ------------------------------------------------------------------
    # Проверка статуса ДР для гостя
    # ------------------------------------------------------------------

    @staticmethod
    def get_birthday_status(vk_user_id: int, branch_id: int) -> dict:
        """
        Возвращает {'is_birthday_mode': bool, 'already_claimed': bool}
        already_claimed=True если подарок ДР уже получен в любом филиале в этом году.
        """
        client_profile = ClientService.get_client_profile(vk_user_id, branch_id)
        in_window, _ = _is_in_birthday_window(client_profile.birth_date)

        already_claimed = False
        if in_window:
            today = timezone.now().date()
            already_claimed = Inventory.objects.filter(
                client__client=client_profile.client,
                acquired_from='BIRTHDAY_PRIZE',
                created_at__year=today.year,
            ).exists()

        return {'is_birthday_mode': in_window, 'already_claimed': already_claimed}

    # ------------------------------------------------------------------
    # SUPER PRIZE (обычный, из игры)
    # ------------------------------------------------------------------

    @staticmethod
    def get_client_super_prizes(vk_user_id: int, branch_id: int):
        """
        Возвращает доступные (не использованные) ОБЫЧНЫЕ супер-призы (GAME / MANUAL).
        """
        client_profile = ClientService.get_client_profile(vk_user_id, branch_id)

        prizes = SuperPrize.objects.filter(
            client=client_profile,
            activated_at__isnull=True,
            acquired_from__in=['GAME', 'MANUAL'],
        ).order_by('created_at')

        return prizes

    @staticmethod
    def claim_super_prize(vk_user_id: int, branch_id: int, product_id: int):
        """
        Клиент выбирает конкретный товар для ОБЫЧНОГО супер-приза.
        Продукт должен иметь is_super_prize=True.
        """
        client_profile = ClientService.get_client_profile(vk_user_id, branch_id)

        with transaction.atomic():
            product = Product.objects.filter(id=product_id, is_super_prize=True).first()
            if not product:
                raise ValidationError(message='Приз не найден или не доступен', code='product_not_found')

            super_prize = SuperPrize.objects.select_for_update().filter(
                client=client_profile,
                activated_at__isnull=True,
                acquired_from__in=['GAME', 'MANUAL'],
            ).order_by('created_at').first()

            if not super_prize:
                raise ValidationError(message='Нет доступных супер-призов', code='not_found')

            super_prize.product = product
            super_prize.activated_at = timezone.now()
            super_prize.save()

            inventory_item = Inventory.objects.create(
                client=client_profile,
                product=product,
                acquired_from='SUPERPRIZE',
            )

            return inventory_item

    # ------------------------------------------------------------------
    # BIRTHDAY PRIZE — просмотр и выбор подарка
    # ------------------------------------------------------------------

    @staticmethod
    def get_client_birthday_prizes(vk_user_id: int, branch_id: int):
        """
        Возвращает список доступных подарков ДР (catalog.Product, is_birthday_prize=True).
        Только если гость находится в окне ±5 дней ДР.
        """
        client_profile = ClientService.get_client_profile(vk_user_id, branch_id)

        in_window, _ = _is_in_birthday_window(client_profile.birth_date)
        if not in_window:
            raise ValidationError(
                message='День рождения не активен (окно ±5 дней)',
                code='not_birthday_window',
            )

        today = timezone.now().date()
        already_claimed = Inventory.objects.filter(
            client__client=client_profile.client,
            acquired_from='BIRTHDAY_PRIZE',
            created_at__year=today.year,
        ).exists()
        if already_claimed:
            raise ValidationError(
                message='Подарок дня рождения уже получен в одном из филиалов в этом году',
                code='already_claimed',
            )

        return Product.objects.filter(
            branch=client_profile.branch,
            is_birthday_prize=True,
            is_active=True,
        ).order_by('-created_at')

    @staticmethod
    def claim_birthday_prize(vk_user_id: int, branch_id: int, product_id: int):
        """
        Клиент выбирает конкретный приз ДР — сразу создаётся Inventory(acquired_from='BIRTHDAY_PRIZE').
        Активация (показать официанту) только через InventoryActivateView в кафе.
        """
        client_profile = ClientService.get_client_profile(vk_user_id, branch_id)

        in_window, _ = _is_in_birthday_window(client_profile.birth_date)
        if not in_window:
            raise ValidationError(
                message='День рождения не активен (окно ±5 дней)',
                code='not_birthday_window',
            )

        # Проверяем, не получал ли этот человек подарок ДР в ЛЮБОМ другом филиале в этом году
        today = timezone.now().date()
        already_claimed = Inventory.objects.filter(
            client__client=client_profile.client,
            acquired_from='BIRTHDAY_PRIZE',
            created_at__year=today.year,
        ).exists()
        if already_claimed:
            raise ValidationError(
                message='Подарок дня рождения уже получен в одном из филиалов в этом году',
                code='already_claimed',
            )

        product = Product.objects.filter(
            id=product_id,
            is_birthday_prize=True,
            is_active=True,
            branch=client_profile.branch,
        ).first()
        if not product:
            raise ValidationError(
                message='Приз дня рождения не найден',
                code='product_not_found',
            )

        inventory_item = Inventory.objects.create(
            client=client_profile,
            product=product,
            acquired_from='BIRTHDAY_PRIZE',
        )

        return inventory_item

    # ------------------------------------------------------------------
    # ACTIVATE
    # ------------------------------------------------------------------

    @staticmethod
    def activate_inventory_item(vk_user_id: int, branch_id: int, inventory_id: int, code: str = None):
        """
        Активация предмета (показать официанту).
        Для BIRTHDAY_PRIZE — требует ввода code из DailyCode (branch.DailyCode).
        Для остальных — проверяет cooldown.
        """
        from apps.tenant.branch.models import DailyCode as BranchDailyCode  # Локальный импорт

        client_profile = ClientService.get_client_profile(vk_user_id, branch_id)

        with transaction.atomic():
            inventory_item = Inventory.objects.select_for_update().filter(
                id=inventory_id,
                client=client_profile,
            ).first()

            if not inventory_item:
                raise ValidationError(message='Предмет не найден', code='not_found')

            if inventory_item.activated_at is not None:
                raise ValidationError(message='Предмет уже активирован', code='already_used')

            now_time = timezone.now()

            if inventory_item.acquired_from == 'BIRTHDAY_PRIZE':
                # --- Проверка кода дня для подарка ДР ---
                if not code:
                    raise ValidationError(
                        message='Введите код дня для активации подарка дня рождения',
                        code='code_required',
                    )

                today = timezone.localdate()
                daily_code = BranchDailyCode.objects.filter(
                    branch_id=branch_id,
                    date=today,
                ).first()

                if not daily_code:
                    raise ValidationError(
                        message='Код дня ещё не создан. Обратитесь к персоналу.',
                        code='code_not_set',
                    )

                if daily_code.code != code.upper().strip():
                    raise ValidationError(message='Неверный код', code='invalid_code')

                cooldown, created = Cooldown.objects.select_for_update().get_or_create(
                    client=client_profile,
                    defaults={'last_activated_at': None},
                )
                if not created and cooldown.is_active:
                    raise ValidationError(message='Подарки перезаряжаются', code='cooldown')

                cooldown.last_activated_at = now_time
                cooldown.save(update_fields=['last_activated_at'])

            inventory_item.activated_at = now_time
            inventory_item.save(update_fields=['activated_at'])

            return inventory_item



class CooldownService:

    @staticmethod
    def get_cooldown_status(vk_user_id: int, branch_id: int):
        client_profile = ClientService.get_client_profile(vk_user_id, branch_id)

        if hasattr(client_profile, 'inventory_cooldown_client'):
            return client_profile.inventory_cooldown_client

        return Cooldown.objects.filter(client=client_profile).first()

    @staticmethod
    def activate_cooldown_manually(vk_user_id: int, branch_id: int):
        """Ручная установка кулдауна (для тестов или админки)"""
        client_profile = ClientService.get_client_profile(vk_user_id, branch_id)

        cooldown, created = Cooldown.objects.get_or_create(
            client=client_profile,
            defaults={'last_activated_at': timezone.now()},
        )
        if not created:
            cooldown.last_activated_at = timezone.now()
            cooldown.save(update_fields=['last_activated_at'])
        return cooldown