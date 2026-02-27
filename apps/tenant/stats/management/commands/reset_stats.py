"""
Команда обнуления статистики и RFM для указанных филиалов.

Что обнуляется (статистика):
  - GuestRFScore          — текущие RF-оценки гостей
  - RFMigrationLog        — история переходов между сегментами
  - BranchSegmentSnapshot — снимки состава сегментов по датам
  - RFSettings.stats_reset_date — устанавливается в NOW()

Что НЕ трогается (данные гостей):
  - CoinTransaction       — баланс монет остаётся
  - Inventory / SuperPrize — призы и инвентарь остаются
  - ClientAttempt         — попытки игры остаются, но RFM пересчитается от новой даты
  - Quest / QuestProgress  — задания остаются

После запуска команды:
  - Следующий RFM-расчёт засчитает только события после stats_reset_date.
  - Старые попытки (до reset_date) в RF игнорируются, но монеты за них не пропадают.

Использование:
  python manage.py reset_stats --branch 1
  python manage.py reset_stats --branch 1 --branch 2
  python manage.py reset_stats --all          # все филиалы текущего тенанта
  python manage.py reset_stats --all --confirm
"""

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = 'Обнуляет статистику и RFM данные не затрагивая балансы гостей'

    def add_arguments(self, parser):
        parser.add_argument(
            '--branch',
            type=int,
            action='append',
            dest='branches',
            help='ID филиала (можно передать несколько раз)',
        )
        parser.add_argument(
            '--all',
            action='store_true',
            dest='all_branches',
            help='Обнулить все филиалы текущего тенанта',
        )
        parser.add_argument(
            '--confirm',
            action='store_true',
            dest='confirmed',
            help='Подтвердить выполнение (без этого флага выводится только превью)',
        )

    def handle(self, *args, **options):
        from apps.tenant.branch.models import Branch
        from apps.tenant.stats.models import (
            GuestRFScore, RFMigrationLog, BranchSegmentSnapshot, RFSettings
        )

        branch_ids = options.get('branches') or []
        all_branches = options.get('all_branches', False)
        confirmed = options.get('confirmed', False)

        if not branch_ids and not all_branches:
            self.stderr.write('Укажите --branch ID или --all')
            return

        if all_branches:
            branches = Branch.objects.all()
        else:
            branches = Branch.objects.filter(id__in=branch_ids)

        if not branches.exists():
            self.stderr.write('Филиалы не найдены')
            return

        self.stdout.write('\n' + '='*60)
        self.stdout.write('ПРЕДПРОСМОТР ОБНУЛЕНИЯ СТАТИСТИКИ')
        self.stdout.write('='*60)

        for branch in branches:
            rf_count     = GuestRFScore.objects.filter(client__branch=branch).count()
            log_count    = RFMigrationLog.objects.filter(client__branch=branch).count()
            snap_count   = BranchSegmentSnapshot.objects.filter(branch=branch).count()
            self.stdout.write(
                f'\nФилиал: {branch.name} (ID={branch.id})\n'
                f'  GuestRFScore:          {rf_count} записей\n'
                f'  RFMigrationLog:        {log_count} записей\n'
                f'  BranchSegmentSnapshot: {snap_count} записей\n'
            )

        self.stdout.write('\nЧТО НЕ БУДЕТ ЗАТРОНУТО:')
        self.stdout.write('  ✓ CoinTransaction (балансы монет)')
        self.stdout.write('  ✓ Inventory / SuperPrize (призы)')
        self.stdout.write('  ✓ ClientAttempt (попытки игр)')
        self.stdout.write('  ✓ Quest / QuestProgress (задания)')
        self.stdout.write('  ✓ ClientBranch (профили гостей)')

        if not confirmed:
            self.stdout.write(
                '\n⚠️  Это ПРЕВЬЮ. Для реального обнуления добавьте флаг --confirm\n'
            )
            return

        # Выполняем обнуление
        reset_dt = timezone.now()
        total_rf = total_log = total_snap = 0

        for branch in branches:
            rf_deleted, _    = GuestRFScore.objects.filter(client__branch=branch).delete()
            log_deleted, _   = RFMigrationLog.objects.filter(client__branch=branch).delete()
            snap_deleted, _  = BranchSegmentSnapshot.objects.filter(branch=branch).delete()

            # Устанавливаем дату обнуления — RFM будет считать только с этого момента
            settings, _ = RFSettings.objects.get_or_create(branch=branch)
            settings.stats_reset_date = reset_dt
            settings.save(update_fields=['stats_reset_date'])

            total_rf   += rf_deleted
            total_log  += log_deleted
            total_snap += snap_deleted

            self.stdout.write(self.style.SUCCESS(
                f'✓ {branch.name}: удалено RF={rf_deleted}, log={log_deleted}, snap={snap_deleted}'
            ))

        self.stdout.write(self.style.SUCCESS(
            f'\n✅ Обнуление завершено. Дата сброса: {reset_dt.strftime("%d.%m.%Y %H:%M")}\n'
            f'   Итого: RF={total_rf}, Logs={total_log}, Snapshots={total_snap}\n'
            f'\n   Следующий запуск calculate_rf_all пересчитает данные от {reset_dt.strftime("%d.%m.%Y")}.'
        ))