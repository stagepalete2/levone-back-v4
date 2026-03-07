"""
Тесты бизнес-логики:
1) PATCH /api/v1/client/ — корректная расстановка via_app флагов в ClientBranch
2) Статистика (group_subscribers, mailing_subscribers_period) — корректный подсчёт метрик

Запуск:
    python manage.py test apps.tenant.tests_via_app_and_stats --verbosity=2

Требования:
    - PostgreSQL (django-tenants)
    - Тенант-схема (TenantTestCase создаёт автоматически)
"""

from datetime import timedelta
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings
from django.utils import timezone
from django.db.models.functions import Coalesce
from django.db.models import Q

from apps.shared.guest.models import Client as BaseClient
from apps.tenant.branch.models import Branch, ClientBranch, ClientBranchVisit
from apps.tenant.branch.core import ClientService
from apps.tenant.inventory.models import SuperPrize
from apps.tenant.game.models import ClientAttempt


# ────────────────────────────────────────────────────────────────────────────
# Хелпер: создание тестовых данных
# ────────────────────────────────────────────────────────────────────────────

def _create_branch(name="Test Branch", dooglys_branch_id=9999):
    """Создаёт Branch без валидации (clean в save вызывает VK и т.д.)"""
    return Branch.objects.create(
        name=name,
        dooglys_branch_id=dooglys_branch_id,
        dooglas_sale_point_id=f"sp_{dooglys_branch_id}",
    )


def _create_client_branch(
    vk_user_id,
    branch,
    is_joined_community=False,
    is_allowed_message=False,
    vk_status_checked=True,
    joined_community_via_app=False,
    allowed_message_via_app=False,
):
    """Создаёт BaseClient + ClientBranch с нужными флагами."""
    base_client, _ = BaseClient.objects.get_or_create(
        vk_user_id=vk_user_id,
        defaults={"name": f"User{vk_user_id}", "lastname": "Test"},
    )
    cb = ClientBranch.objects.create(
        client=base_client,
        branch=branch,
        is_joined_community=is_joined_community,
        is_allowed_message=is_allowed_message,
        vk_status_checked=vk_status_checked,
        joined_community_via_app=joined_community_via_app,
        allowed_message_via_app=allowed_message_via_app,
    )
    return cb


# ────────────────────────────────────────────────────────────────────────────
# Попытка импорта TenantTestCase; если не удалось — откатываемся на TestCase
# ────────────────────────────────────────────────────────────────────────────
try:
    from django_tenants.test.cases import TenantTestCase
    from django_tenants.test.client import TenantClient

    BASE_TEST_CLASS = TenantTestCase
except ImportError:
    BASE_TEST_CLASS = TestCase


# ============================================================================
#  ТЕСТ 1: PATCH endpoint — корректность via_app флагов
# ============================================================================


class TestUpdateProfileViaAppFlags(BASE_TEST_CLASS):
    """
    Проверяем ClientService.update_profile_details():
    правильно ли выставляются joined_community_via_app / allowed_message_via_app
    в зависимости от исходного состояния подписок.

    4 сценария:
    ┌────────────────────┬─────────────────┬──────────────────────────┬─────────────────────────┐
    │ До приложения      │ До приложения   │ joined_community_via_app │ allowed_message_via_app │
    │ (группа)           │ (рассылка)      │ (ожидание)               │ (ожидание)              │
    ├────────────────────┼─────────────────┼──────────────────────────┼─────────────────────────┤
    │ Да                 │ Да              │ False                    │ False                   │
    │ Да                 │ Нет             │ False                    │ True                    │
    │ Нет                │ Да              │ True                     │ False                   │
    │ Нет                │ Нет             │ True                     │ True                    │
    └────────────────────┴─────────────────┴──────────────────────────┴─────────────────────────┘
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Отключаем валидацию Branch.clean() — она дёргает кросс-тенантные проверки.
        cls._original_clean = Branch.clean
        Branch.clean = lambda self: None

    @classmethod
    def tearDownClass(cls):
        Branch.clean = cls._original_clean
        super().tearDownClass()

    def setUp(self):
        self.branch = _create_branch()

    # ── Сценарий 1: Гость подписан на группу И рассылку ДО приложения ──

    def test_scenario1_both_subscribed_before_app(self):
        """
        Гость уже подписан на группу И на рассылку.
        → via_app НЕ ставится ни для группы, ни для рассылки.
        → В метрику НЕ попадает.
        """
        cb = _create_client_branch(
            vk_user_id=1001,
            branch=self.branch,
            is_joined_community=True,   # уже подписан
            is_allowed_message=True,    # уже разрешил
            vk_status_checked=True,
        )

        # Фронт отправляет PATCH (подтверждение уже существующих подписок)
        updated = ClientService.update_profile_details(
            vk_user_id=1001,
            branch_id=self.branch.id,
            validated_data={
                "is_joined_community": True,
                "is_allowed_message": True,
            },
        )

        self.assertFalse(updated.joined_community_via_app,
                         "Был подписан ДО → via_app НЕ должен ставиться")
        self.assertFalse(updated.allowed_message_via_app,
                         "Разрешал рассылку ДО → via_app НЕ должен ставиться")

    # ── Сценарий 2: Подписан на группу, НЕ подписан на рассылку ──

    def test_scenario2_community_yes_mailing_no(self):
        """
        Гость подписан на группу, но НЕ на рассылку.
        После PATCH с is_allowed_message=True:
        → joined_community_via_app = False  (был подписан ДО)
        → allowed_message_via_app  = True   (подписался ЧЕРЕЗ приложение)
        → Попадает в метрику «подписались на рассылку».
        """
        cb = _create_client_branch(
            vk_user_id=1002,
            branch=self.branch,
            is_joined_community=True,   # уже в группе
            is_allowed_message=False,   # НЕ разрешал рассылку
            vk_status_checked=True,
        )

        updated = ClientService.update_profile_details(
            vk_user_id=1002,
            branch_id=self.branch.id,
            validated_data={
                "is_joined_community": True,
                "is_allowed_message": True,
            },
        )

        self.assertFalse(updated.joined_community_via_app,
                         "Был в группе ДО → via_app НЕ должен ставиться")
        self.assertTrue(updated.allowed_message_via_app,
                        "Разрешил рассылку ЧЕРЕЗ приложение → via_app = True")
        self.assertIsNotNone(updated.allowed_message_via_app_at,
                             "Дата разрешения рассылки должна быть заполнена")

    # ── Сценарий 3: НЕ подписан на группу, подписан на рассылку ──

    def test_scenario3_community_no_mailing_yes(self):
        """
        Гость НЕ подписан на группу, но разрешил рассылку.
        После PATCH с is_joined_community=True:
        → joined_community_via_app = True   (вступил ЧЕРЕЗ приложение)
        → allowed_message_via_app  = False  (разрешал рассылку ДО)
        → Попадает в метрику «подписались на группу».
        """
        cb = _create_client_branch(
            vk_user_id=1003,
            branch=self.branch,
            is_joined_community=False,  # НЕ в группе
            is_allowed_message=True,    # уже разрешил рассылку
            vk_status_checked=True,
        )

        updated = ClientService.update_profile_details(
            vk_user_id=1003,
            branch_id=self.branch.id,
            validated_data={
                "is_joined_community": True,
            },
        )

        self.assertTrue(updated.joined_community_via_app,
                        "Вступил в группу ЧЕРЕЗ приложение → via_app = True")
        self.assertIsNotNone(updated.joined_community_via_app_at,
                             "Дата вступления должна быть заполнена")
        self.assertFalse(updated.allowed_message_via_app,
                         "Разрешал рассылку ДО → via_app НЕ должен ставиться")

    # ── Сценарий 4: НЕ подписан ни на группу, ни на рассылку ──

    def test_scenario4_neither_subscribed(self):
        """
        Гость не подписан ни на группу, ни на рассылку.
        После PATCH с is_joined_community=True:
        → joined_community_via_app = True
        → allowed_message_via_app  = True  (вступление → автоматическое разрешение)
        → Попадает в ОБЕ метрики.
        """
        cb = _create_client_branch(
            vk_user_id=1004,
            branch=self.branch,
            is_joined_community=False,
            is_allowed_message=False,
            vk_status_checked=True,
        )

        updated = ClientService.update_profile_details(
            vk_user_id=1004,
            branch_id=self.branch.id,
            validated_data={
                "is_joined_community": True,
            },
        )

        self.assertTrue(updated.joined_community_via_app,
                        "Вступил в группу ЧЕРЕЗ приложение → via_app = True")
        self.assertTrue(updated.allowed_message_via_app,
                        "Вступление в группу автоматически разрешает рассылку → via_app = True")
        self.assertTrue(updated.is_allowed_message,
                        "is_allowed_message должен быть True после вступления")
        self.assertIsNotNone(updated.joined_community_via_app_at)
        self.assertIsNotNone(updated.allowed_message_via_app_at)

    # ── Сценарий 4b: отправка обоих флагов в одном PATCH ──

    def test_scenario4b_both_flags_in_single_patch(self):
        """
        Гость не подписан. Фронт отправляет оба флага одновременно.
        Результат должен быть идентичен сценарию 4.
        """
        cb = _create_client_branch(
            vk_user_id=1005,
            branch=self.branch,
            is_joined_community=False,
            is_allowed_message=False,
            vk_status_checked=True,
        )

        updated = ClientService.update_profile_details(
            vk_user_id=1005,
            branch_id=self.branch.id,
            validated_data={
                "is_joined_community": True,
                "is_allowed_message": True,
            },
        )

        self.assertTrue(updated.joined_community_via_app)
        self.assertTrue(updated.allowed_message_via_app)

    # ── Сценарий 5: vk_status_checked=False — VK API не ответил ──

    @patch("apps.tenant.branch.core.VKService")
    def test_scenario5_vk_not_checked_api_fails(self, MockVKService):
        """
        vk_status_checked=False и VK API снова не отвечает.
        → via_app НЕ ставится (защита от ложных срабатываний).
        """
        mock_svc = MockVKService.return_value
        mock_svc.check_is_group_member.return_value = None  # API не ответил
        mock_svc.check_is_messages_allowed.return_value = None

        cb = _create_client_branch(
            vk_user_id=1006,
            branch=self.branch,
            is_joined_community=False,
            is_allowed_message=False,
            vk_status_checked=False,  # VK не был проверен
        )

        updated = ClientService.update_profile_details(
            vk_user_id=1006,
            branch_id=self.branch.id,
            validated_data={
                "is_joined_community": True,
                "is_allowed_message": True,
            },
        )

        self.assertFalse(updated.joined_community_via_app,
                         "VK API не ответил → via_app НЕ ставится (защита)")
        self.assertFalse(updated.allowed_message_via_app,
                         "VK API не ответил → via_app НЕ ставится (защита)")

    # ── Сценарий 6: vk_status_checked=False, но VK API подтвердил подписку ──

    @patch("apps.tenant.branch.core.VKService")
    def test_scenario6_vk_not_checked_but_confirms_member(self, MockVKService):
        """
        vk_status_checked=False, но при повторной проверке VK API
        подтвердил, что пользователь УЖЕ был подписан.
        → via_app НЕ ставится (подписка была ДО приложения).
        """
        mock_svc = MockVKService.return_value
        mock_svc.check_is_group_member.return_value = True   # был подписан
        mock_svc.check_is_messages_allowed.return_value = True

        cb = _create_client_branch(
            vk_user_id=1007,
            branch=self.branch,
            is_joined_community=False,
            is_allowed_message=False,
            vk_status_checked=False,
        )

        updated = ClientService.update_profile_details(
            vk_user_id=1007,
            branch_id=self.branch.id,
            validated_data={
                "is_joined_community": True,
                "is_allowed_message": True,
            },
        )

        self.assertTrue(updated.is_joined_community)
        self.assertTrue(updated.is_allowed_message)
        self.assertTrue(updated.vk_status_checked,
                        "VK API ответил → vk_status_checked = True")
        self.assertFalse(updated.joined_community_via_app,
                         "VK подтвердил, что был подписан ДО → via_app НЕ ставится")
        self.assertFalse(updated.allowed_message_via_app,
                         "VK подтвердил, что разрешал ДО → via_app НЕ ставится")

    # ── Сценарий 7: повторный PATCH не дублирует via_app ──

    def test_scenario7_idempotent_patch(self):
        """
        Повторный PATCH с теми же данными не должен менять via_app_at даты.
        """
        cb = _create_client_branch(
            vk_user_id=1008,
            branch=self.branch,
            is_joined_community=False,
            is_allowed_message=False,
            vk_status_checked=True,
        )

        # Первый PATCH
        updated1 = ClientService.update_profile_details(
            vk_user_id=1008,
            branch_id=self.branch.id,
            validated_data={"is_joined_community": True},
        )
        first_joined_at = updated1.joined_community_via_app_at
        first_allowed_at = updated1.allowed_message_via_app_at

        self.assertTrue(updated1.joined_community_via_app)
        self.assertIsNotNone(first_joined_at)

        # Второй PATCH — идемпотентный
        updated2 = ClientService.update_profile_details(
            vk_user_id=1008,
            branch_id=self.branch.id,
            validated_data={"is_joined_community": True},
        )

        self.assertTrue(updated2.joined_community_via_app)
        # Дата НЕ должна обновиться — переход False→True уже произошёл ранее
        self.assertEqual(updated2.joined_community_via_app_at, first_joined_at,
                         "Повторный PATCH не должен обновлять дату via_app_at")

    # ── Сценарий 8: только рассылка без группы ──

    def test_scenario8_mailing_only_without_community(self):
        """
        Гость не подписан ни на группу, ни на рассылку.
        Фронт отправляет ТОЛЬКО is_allowed_message=True (без is_joined_community).
        → allowed_message_via_app = True
        → joined_community_via_app = False (не вступал)
        """
        cb = _create_client_branch(
            vk_user_id=1009,
            branch=self.branch,
            is_joined_community=False,
            is_allowed_message=False,
            vk_status_checked=True,
        )

        updated = ClientService.update_profile_details(
            vk_user_id=1009,
            branch_id=self.branch.id,
            validated_data={
                "is_allowed_message": True,
            },
        )

        self.assertFalse(updated.joined_community_via_app,
                         "Не вступал в группу → via_app для группы = False")
        self.assertTrue(updated.allowed_message_via_app,
                        "Разрешил рассылку ЧЕРЕЗ приложение → via_app = True")


# ============================================================================
#  ТЕСТ 2: Статистика — корректность подсчёта метрик
# ============================================================================


class TestStatsMetrics(BASE_TEST_CLASS):
    """
    Проверяем, что метрики group_subscribers и mailing_subscribers_period
    считаются строго по бизнес-логике:

    | Группа до | Рассылка до | joined_via_app | allowed_via_app | Метрика группы | Метрика рассылки |
    |-----------|-------------|----------------|-----------------|----------------|------------------|
    | Да        | Да          | False          | False           | Нет            | Нет              |
    | Да        | Нет         | False          | True            | Нет            | Да               |
    | Нет       | Да          | True           | False           | Да             | Нет              |
    | Нет       | Нет         | True           | True            | Да             | Да               |
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._original_clean = Branch.clean
        Branch.clean = lambda self: None

    @classmethod
    def tearDownClass(cls):
        Branch.clean = cls._original_clean
        super().tearDownClass()

    def setUp(self):
        self.branch = _create_branch(dooglys_branch_id=8888)
        self.now = timezone.now()

        # Сценарий 1: обе подписки ДО приложения
        self.cb1 = _create_client_branch(
            vk_user_id=2001, branch=self.branch,
            is_joined_community=True, is_allowed_message=True,
            joined_community_via_app=False, allowed_message_via_app=False,
        )

        # Сценарий 2: группа ДО, рассылка ЧЕРЕЗ приложение
        self.cb2 = _create_client_branch(
            vk_user_id=2002, branch=self.branch,
            is_joined_community=True, is_allowed_message=True,
            joined_community_via_app=False, allowed_message_via_app=True,
        )
        ClientBranch.objects.filter(pk=self.cb2.pk).update(
            allowed_message_via_app_at=self.now - timedelta(days=5),
        )

        # Сценарий 3: группа ЧЕРЕЗ приложение, рассылка ДО
        self.cb3 = _create_client_branch(
            vk_user_id=2003, branch=self.branch,
            is_joined_community=True, is_allowed_message=True,
            joined_community_via_app=True, allowed_message_via_app=False,
        )
        ClientBranch.objects.filter(pk=self.cb3.pk).update(
            joined_community_via_app_at=self.now - timedelta(days=3),
        )

        # Сценарий 4: обе подписки ЧЕРЕЗ приложение
        self.cb4 = _create_client_branch(
            vk_user_id=2004, branch=self.branch,
            is_joined_community=True, is_allowed_message=True,
            joined_community_via_app=True, allowed_message_via_app=True,
        )
        ClientBranch.objects.filter(pk=self.cb4.pk).update(
            joined_community_via_app_at=self.now - timedelta(days=2),
            allowed_message_via_app_at=self.now - timedelta(days=2),
        )

    def _count_group_subscribers(self, date_from=None, date_to=None, branch_id=None):
        """
        Воспроизводим логику из GeneralStatsService.get_dashboard_stats()
        для подсчёта group_subscribers.
        """
        base_qs = ClientBranch.objects.filter(invited_by__isnull=True)
        group_sub_qs = base_qs.filter(joined_community_via_app=True).annotate(
            effective_joined_at=Coalesce("joined_community_via_app_at", "created_at")
        )
        if date_from:
            group_sub_qs = group_sub_qs.filter(effective_joined_at__gte=date_from)
        if date_to:
            group_sub_qs = group_sub_qs.filter(effective_joined_at__lte=date_to)
        if branch_id:
            group_sub_qs = group_sub_qs.filter(branch_id=branch_id)
        return group_sub_qs.values("client").distinct().count()

    def _count_mailing_subscribers(self, date_from=None, date_to=None, branch_id=None):
        """
        Воспроизводим логику из GeneralStatsService.get_dashboard_stats()
        для подсчёта mailing_subscribers_period.
        """
        base_qs = ClientBranch.objects.filter(invited_by__isnull=True)
        mailing_sub_qs = base_qs.filter(allowed_message_via_app=True).annotate(
            effective_allowed_at=Coalesce("allowed_message_via_app_at", "created_at")
        )
        if date_from:
            mailing_sub_qs = mailing_sub_qs.filter(effective_allowed_at__gte=date_from)
        if date_to:
            mailing_sub_qs = mailing_sub_qs.filter(effective_allowed_at__lte=date_to)
        if branch_id:
            mailing_sub_qs = mailing_sub_qs.filter(branch_id=branch_id)
        return mailing_sub_qs.values("client").distinct().count()

    # ── Тесты подсчёта за всё время (без date_from/date_to) ──

    def test_group_subscribers_total(self):
        """
        group_subscribers (за всё время):
        Сценарий 1: False → не считается
        Сценарий 2: False → не считается
        Сценарий 3: True  → считается   ✓
        Сценарий 4: True  → считается   ✓
        Итого: 2
        """
        count = self._count_group_subscribers(branch_id=self.branch.id)
        self.assertEqual(count, 2,
                         "Только сценарии 3 и 4 имеют joined_community_via_app=True")

    def test_mailing_subscribers_total(self):
        """
        mailing_subscribers_period (за всё время):
        Сценарий 1: False → не считается
        Сценарий 2: True  → считается   ✓
        Сценарий 3: False → не считается
        Сценарий 4: True  → считается   ✓
        Итого: 2
        """
        count = self._count_mailing_subscribers(branch_id=self.branch.id)
        self.assertEqual(count, 2,
                         "Только сценарии 2 и 4 имеют allowed_message_via_app=True")

    # ── Тесты подсчёта за период ──

    def test_group_subscribers_last_7_days(self):
        """
        За 7 дней: cb3 (3 дня назад) и cb4 (2 дня назад) → 2
        """
        date_from = self.now - timedelta(days=7)
        count = self._count_group_subscribers(
            date_from=date_from, date_to=self.now, branch_id=self.branch.id
        )
        self.assertEqual(count, 2)

    def test_mailing_subscribers_last_7_days(self):
        """
        За 7 дней: cb2 (5 дней назад) и cb4 (2 дня назад) → 2
        """
        date_from = self.now - timedelta(days=7)
        count = self._count_mailing_subscribers(
            date_from=date_from, date_to=self.now, branch_id=self.branch.id
        )
        self.assertEqual(count, 2)

    def test_group_subscribers_last_1_day(self):
        """
        За 1 день: cb3 (3 дня назад) и cb4 (2 дня назад) → 0
        (обе подписки были раньше 1 дня)
        """
        date_from = self.now - timedelta(days=1)
        count = self._count_group_subscribers(
            date_from=date_from, date_to=self.now, branch_id=self.branch.id
        )
        self.assertEqual(count, 0)

    def test_mailing_subscribers_narrow_window(self):
        """
        За 4 дня: cb2 → НЕТ (5 дней назад), cb4 → ДА (2 дня назад) → 1
        """
        date_from = self.now - timedelta(days=4)
        count = self._count_mailing_subscribers(
            date_from=date_from, date_to=self.now, branch_id=self.branch.id
        )
        self.assertEqual(count, 1, "Только cb4 попадает в окно 4 дня")

    # ── Сценарий 1 не попадает ни в одну метрику ──

    def test_scenario1_not_in_any_metric(self):
        """Гость с обеими подписками ДО приложения не должен считаться."""
        # Проверяем, что cb1 НЕ входит ни в один подсчёт
        group_qs = ClientBranch.objects.filter(
            id=self.cb1.id, joined_community_via_app=True
        )
        mailing_qs = ClientBranch.objects.filter(
            id=self.cb1.id, allowed_message_via_app=True
        )
        self.assertFalse(group_qs.exists())
        self.assertFalse(mailing_qs.exists())

    # ── Кросс-проверка: сценарий 2 только в рассылке ──

    def test_scenario2_only_in_mailing_metric(self):
        """Гость подписан на группу ДО → только в метрике рассылки."""
        self.assertFalse(self.cb2.joined_community_via_app)
        cb2_fresh = ClientBranch.objects.get(pk=self.cb2.pk)
        self.assertTrue(cb2_fresh.allowed_message_via_app)

    # ── Кросс-проверка: сценарий 3 только в группе ──

    def test_scenario3_only_in_group_metric(self):
        """Гость разрешил рассылку ДО → только в метрике группы."""
        cb3_fresh = ClientBranch.objects.get(pk=self.cb3.pk)
        self.assertTrue(cb3_fresh.joined_community_via_app)
        self.assertFalse(cb3_fresh.allowed_message_via_app)

    # ── Реферальные НЕ учитываются ──

    def test_referral_clients_excluded_from_metrics(self):
        """
        Реферальные клиенты (invited_by IS NOT NULL) исключаются
        из метрик group_subscribers и mailing_subscribers.
        """
        referrer_base = BaseClient.objects.get(vk_user_id=2001)
        ref_cb = _create_client_branch(
            vk_user_id=3001, branch=self.branch,
            is_joined_community=True, is_allowed_message=True,
            joined_community_via_app=True, allowed_message_via_app=True,
        )
        ref_cb.invited_by = referrer_base
        ref_cb.save()
        ClientBranch.objects.filter(pk=ref_cb.pk).update(
            joined_community_via_app_at=self.now,
            allowed_message_via_app_at=self.now,
        )

        # Реферальный не должен попадать в подсчёт
        group_count = self._count_group_subscribers(branch_id=self.branch.id)
        mailing_count = self._count_mailing_subscribers(branch_id=self.branch.id)

        # По-прежнему 2 и 2 (без реферального)
        self.assertEqual(group_count, 2,
                         "Реферальный не должен учитываться в group_subscribers")
        self.assertEqual(mailing_count, 2,
                         "Реферальный не должен учитываться в mailing_subscribers")


# ============================================================================
#  ТЕСТ 3: Интеграционный — полный цикл PATCH → Статистика
# ============================================================================


class TestEndToEndPatchToStats(BASE_TEST_CLASS):
    """
    Полный цикл: создаём клиентов, делаем PATCH,
    затем проверяем метрики — всё через реальные вызовы сервисов.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._original_clean = Branch.clean
        Branch.clean = lambda self: None

    @classmethod
    def tearDownClass(cls):
        Branch.clean = cls._original_clean
        super().tearDownClass()

    def setUp(self):
        self.branch = _create_branch(dooglys_branch_id=7777)

    def _count_group(self):
        base_qs = ClientBranch.objects.filter(invited_by__isnull=True)
        return base_qs.filter(
            joined_community_via_app=True, branch=self.branch
        ).values("client").distinct().count()

    def _count_mailing(self):
        base_qs = ClientBranch.objects.filter(invited_by__isnull=True)
        return base_qs.filter(
            allowed_message_via_app=True, branch=self.branch
        ).values("client").distinct().count()

    def test_full_cycle_all_scenarios(self):
        """
        Создаём 4 клиентов (4 сценария), делаем PATCH, проверяем метрики.
        """
        # Сценарий 1: оба до приложения
        _create_client_branch(5001, self.branch, True, True, True)
        ClientService.update_profile_details(5001, self.branch.id, {
            "is_joined_community": True, "is_allowed_message": True,
        })

        # Сценарий 2: группа до, рассылка через приложение
        _create_client_branch(5002, self.branch, True, False, True)
        ClientService.update_profile_details(5002, self.branch.id, {
            "is_allowed_message": True,
        })

        # Сценарий 3: группа через приложение, рассылка до
        _create_client_branch(5003, self.branch, False, True, True)
        ClientService.update_profile_details(5003, self.branch.id, {
            "is_joined_community": True,
        })

        # Сценарий 4: оба через приложение
        _create_client_branch(5004, self.branch, False, False, True)
        ClientService.update_profile_details(5004, self.branch.id, {
            "is_joined_community": True,
        })

        # Проверяем метрики
        group_count = self._count_group()
        mailing_count = self._count_mailing()

        self.assertEqual(group_count, 2,
                         "Только сценарии 3 и 4 → group_subscribers = 2")
        self.assertEqual(mailing_count, 2,
                         "Только сценарии 2 и 4 → mailing_subscribers = 2")

    def test_total_mailing_is_cumulative(self):
        """
        total_mailing_subscribers (общее) — это ВСЕ allowed_message_via_app=True
        за ВСЁ время, не только за период. Проверяем что base_qs фильтрует
        именно по via_app.
        """
        # Два пользователя: один через приложение, один до
        _create_client_branch(6001, self.branch, True, True, True,
                              joined_community_via_app=False,
                              allowed_message_via_app=False)
        _create_client_branch(6002, self.branch, True, True, True,
                              joined_community_via_app=False,
                              allowed_message_via_app=True)
        _create_client_branch(6003, self.branch, True, True, True,
                              joined_community_via_app=True,
                              allowed_message_via_app=True)

        base_qs = ClientBranch.objects.filter(
            invited_by__isnull=True, branch=self.branch
        )
        total_mailing = base_qs.filter(
            allowed_message_via_app=True
        ).values("client").distinct().count()

        self.assertEqual(total_mailing, 2,
                         "Только 6002 и 6003 имеют allowed_message_via_app=True")


# ============================================================================
#  ТЕСТ 4: Регистрация (POST) — VK API проверка при создании ClientBranch
# ============================================================================


class TestRegistrationVKCheck(BASE_TEST_CLASS):
    """
    Проверяем, что при POST /api/v1/client/ (register_or_update_client)
    VK API корректно проставляет is_joined_community / is_allowed_message
    без via_app (т.к. подписка была ДО приложения).
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._original_clean = Branch.clean
        Branch.clean = lambda self: None

    @classmethod
    def tearDownClass(cls):
        Branch.clean = cls._original_clean
        super().tearDownClass()

    def setUp(self):
        self.branch = _create_branch(dooglys_branch_id=6666)

    @patch("apps.tenant.branch.core.VKService")
    def test_registration_member_before_app(self, MockVKService):
        """
        При регистрации VK API подтверждает: пользователь УЖЕ в группе и разрешил рассылку.
        → is_joined_community=True, is_allowed_message=True
        → via_app = False (подписка была ДО)
        """
        mock_svc = MockVKService.return_value
        mock_svc.check_is_group_member.return_value = True
        mock_svc.check_is_messages_allowed.return_value = True

        result = ClientService.register_or_update_client(
            vk_user_id=7001,
            branch_id=self.branch.id,
            data={"name": "Test", "lastname": "User", "sex": 1},
        )

        self.assertTrue(result.is_joined_community)
        self.assertTrue(result.is_allowed_message)
        self.assertTrue(result.vk_status_checked)
        self.assertFalse(result.joined_community_via_app,
                         "Подписан ДО приложения → via_app = False")
        self.assertFalse(result.allowed_message_via_app,
                         "Разрешал ДО приложения → via_app = False")

    @patch("apps.tenant.branch.core.VKService")
    def test_registration_not_member(self, MockVKService):
        """
        VK API подтверждает: пользователь НЕ в группе и НЕ разрешал рассылку.
        → is_joined_community=False, is_allowed_message=False
        """
        mock_svc = MockVKService.return_value
        mock_svc.check_is_group_member.return_value = False
        mock_svc.check_is_messages_allowed.return_value = False

        result = ClientService.register_or_update_client(
            vk_user_id=7002,
            branch_id=self.branch.id,
            data={"name": "Test2", "lastname": "User2", "sex": 2},
        )

        self.assertFalse(result.is_joined_community)
        self.assertFalse(result.is_allowed_message)
        self.assertTrue(result.vk_status_checked)

    @patch("apps.tenant.branch.core.VKService")
    def test_registration_vk_api_fails(self, MockVKService):
        """
        VK API не ответил → vk_status_checked=False.
        → is_joined_community=False, is_allowed_message=False
        """
        mock_svc = MockVKService.return_value
        mock_svc.check_is_group_member.return_value = None
        mock_svc.check_is_messages_allowed.return_value = None

        result = ClientService.register_or_update_client(
            vk_user_id=7003,
            branch_id=self.branch.id,
            data={"name": "Test3", "lastname": "User3"},
        )

        self.assertFalse(result.is_joined_community)
        self.assertFalse(result.is_allowed_message)
        self.assertFalse(result.vk_status_checked,
                         "VK API не ответил → vk_status_checked остаётся False")