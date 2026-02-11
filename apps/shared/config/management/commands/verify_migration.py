"""
Django Management Command для проверки целостности данных после миграции

Использование:
    python manage.py verify_migration
    python manage.py verify_migration --tenant-schema=schema_name
"""

from django.core.management.base import BaseCommand
from django.db import connections
from django.db.models import Sum, Count
from django_tenants.utils import tenant_context

from apps.shared.clients.models import Company
from apps.shared.guest.models import Client
from apps.tenant.branch.models import Branch, ClientBranch, CoinTransaction


class Command(BaseCommand):
    help = 'Проверка целостности данных после миграции v3 → v4'

    def __init__(self):
        super().__init__()
        self.errors = []
        self.warnings = []
        self.checks_passed = 0
        self.checks_total = 0

    def add_arguments(self, parser):
        parser.add_argument(
            '--tenant-schema',
            type=str,
            help='Проверить только указанную схему tenant'
        )
        parser.add_argument(
            '--v3-db-name',
            type=str,
            help='Название базы v3 для сравнения'
        )
        parser.add_argument(
            '--v3-db-host',
            type=str,
            default='localhost',
        )
        parser.add_argument(
            '--v3-db-user',
            type=str,
            default='postgres',
        )
        parser.add_argument(
            '--v3-db-password',
            type=str,
            default='',
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING('=' * 80))
        self.stdout.write(self.style.WARNING('ПРОВЕРКА ЦЕЛОСТНОСТИ ДАННЫХ ПОСЛЕ МИГРАЦИИ'))
        self.stdout.write(self.style.WARNING('=' * 80))

        # Настройка подключения к v3 если указано
        if options.get('v3_db_name'):
            self.setup_v3_connection(options)
            self.compare_with_v3 = True
        else:
            self.compare_with_v3 = False

        # Проверка public schema
        self.stdout.write(self.style.SUCCESS('\n[1/3] Проверка PUBLIC schema...'))
        self.verify_public_schema()

        # Проверка tenant schemas
        self.stdout.write(self.style.SUCCESS('\n[2/3] Проверка TENANT schemas...'))
        
        if options.get('tenant_schema'):
            self.verify_tenant_schema(options['tenant_schema'])
        else:
            for company in Company.objects.all():
                self.verify_tenant_schema(company.schema_name)

        # Проверка бизнес-логики
        self.stdout.write(self.style.SUCCESS('\n[3/3] Проверка бизнес-логики...'))
        self.verify_business_logic()

        # Отчет
        self.print_verification_report()

        if options.get('v3_db_name'):
            connections['v3'].close()

    def setup_v3_connection(self, options):
        """Настройка подключения к БД v3 для сравнения"""
        connections.databases['v3'] = {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': options['v3_db_name'],
            'USER': options['v3_db_user'],
            'PASSWORD': options['v3_db_password'],
            'HOST': options['v3_db_host'],
            'PORT': 5432,
            'OPTIONS': {},  # Обязательный параметр для PostgreSQL
        }

    def check(self, name, condition, error_msg=None, warning=False):
        """Универсальная проверка"""
        self.checks_total += 1
        
        if condition:
            self.checks_passed += 1
            self.stdout.write(f'  ✓ {name}')
            return True
        else:
            msg = error_msg or f'{name} failed'
            if warning:
                self.warnings.append(msg)
                self.stdout.write(self.style.WARNING(f'  ⚠ {name}: {msg}'))
            else:
                self.errors.append(msg)
                self.stdout.write(self.style.ERROR(f'  ✗ {name}: {msg}'))
            return False

    def verify_public_schema(self):
        """Проверка данных в public schema"""
        from apps.shared.clients.models import Company, CompanyConfig, Domain
        
        # Проверка Company
        company_count = Company.objects.count()
        self.check(
            'Company записи существуют',
            company_count > 0,
            'Не найдено ни одной компании'
        )

        # Проверка CompanyConfig для каждой Company
        for company in Company.objects.all():
            has_config = hasattr(company, 'config')
            self.check(
                f'CompanyConfig для {company.name}',
                has_config,
                f'Отсутствует конфиг для компании {company.name}'
            )

        # Проверка Domain
        domain_count = Domain.objects.count()
        self.check(
            'Domain записи существуют',
            domain_count > 0,
            'Не найдено ни одного домена',
            warning=True
        )

        # Проверка Client
        client_count = Client.objects.count()
        self.check(
            'Client записи существуют',
            client_count > 0,
            'Не найдено ни одного VK клиента'
        )

        # Проверка уникальности vk_user_id
        duplicate_vk_ids = Client.objects.values('vk_user_id').annotate(
            count=Count('id')
        ).filter(count__gt=1)
        
        self.check(
            'Уникальность vk_user_id',
            not duplicate_vk_ids.exists(),
            f'Найдено {duplicate_vk_ids.count()} дублирующихся vk_user_id'
        )

        # Сравнение с v3
        if self.compare_with_v3:
            with connections['v3'].cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM public.company_company")
                v3_count = cursor.fetchone()[0]
                
                self.check(
                    f'Соответствие количества Company (v4: {company_count}, v3: {v3_count})',
                    company_count == v3_count,
                    f'Количество не совпадает: v4={company_count}, v3={v3_count}'
                )

    def verify_tenant_schema(self, schema_name):
        """Проверка данных конкретного tenant schema"""
        try:
            company = Company.objects.get(schema_name=schema_name)
        except Company.DoesNotExist:
            self.errors.append(f'Компания для schema {schema_name} не найдена')
            return

        self.stdout.write(f'\n  Проверка schema: {schema_name}')

        with tenant_context(company):
            self.verify_branches()
            self.verify_client_branches()
            self.verify_coin_transactions()
            self.verify_products()
            self.verify_relationships()

    def verify_branches(self):
        """Проверка филиалов"""
        branch_count = Branch.objects.count()
        self.check(
            '  Branch записи',
            branch_count > 0,
            'Нет филиалов',
            warning=True
        )

        # Проверка BranchConfig
        for branch in Branch.objects.all():
            has_config = hasattr(branch, 'config')
            self.check(
                f'  BranchConfig для {branch.name}',
                has_config,
                f'Отсутствует конфиг для филиала {branch.name}',
                warning=True
            )

    def verify_client_branches(self):
        """Проверка профилей гостей"""
        cb_count = ClientBranch.objects.count()
        self.check(
            '  ClientBranch записи',
            cb_count > 0,
            'Нет профилей гостей',
            warning=True
        )

        # Проверка уникальности client + branch
        duplicates = ClientBranch.objects.values('client', 'branch').annotate(
            count=Count('id')
        ).filter(count__gt=1)
        
        self.check(
            '  Уникальность client+branch',
            not duplicates.exists(),
            f'Найдено {duplicates.count()} дублей'
        )

        # Проверка ссылочной целостности invited_by
        invalid_invites = ClientBranch.objects.filter(
            invited_by__isnull=False
        ).exclude(
            invited_by__in=Client.objects.all()
        ).count()
        
        self.check(
            '  Целостность invited_by',
            invalid_invites == 0,
            f'Найдено {invalid_invites} некорректных ссылок на invited_by'
        )

    def verify_coin_transactions(self):
        """Проверка транзакций монет"""
        tx_count = CoinTransaction.objects.count()
        self.check(
            '  CoinTransaction записи',
            tx_count > 0,
            'Нет транзакций монет',
            warning=True
        )

        # Проверка типов транзакций
        valid_types = [CoinTransaction.Type.INCOME, CoinTransaction.Type.EXPENSE]
        invalid_types = CoinTransaction.objects.exclude(
            type__in=valid_types
        ).count()
        
        self.check(
            '  Корректность типов транзакций',
            invalid_types == 0,
            f'Найдено {invalid_types} транзакций с некорректным типом'
        )

        # Проверка источников
        valid_sources = [s[0] for s in CoinTransaction.Source.choices]
        invalid_sources = CoinTransaction.objects.exclude(
            source__in=valid_sources
        ).count()
        
        self.check(
            '  Корректность источников транзакций',
            invalid_sources == 0,
            f'Найдено {invalid_sources} транзакций с некорректным источником'
        )

        # Проверка балансов
        for cb in ClientBranch.objects.all()[:100]:  # Проверяем первые 100
            balance = cb.coins_balance
            self.check(
                f'  Баланс {cb.client.full_name}',
                balance >= 0,
                f'Отрицательный баланс: {balance}',
                warning=True
            )

    def verify_products(self):
        """Проверка продуктов"""
        from apps.tenant.catalog.models import Product
        
        product_count = Product.objects.count()
        self.check(
            '  Product записи',
            product_count > 0,
            'Нет продуктов',
            warning=True
        )

        # Проверка цен
        invalid_prices = Product.objects.filter(price__lt=0).count()
        self.check(
            '  Корректность цен',
            invalid_prices == 0,
            f'Найдено {invalid_prices} продуктов с некорректной ценой'
        )

    def verify_relationships(self):
        """Проверка связей между моделями"""
        # Проверка orphaned ClientBranch
        orphaned_cb = ClientBranch.objects.filter(
            client__isnull=True
        ) | ClientBranch.objects.filter(
            branch__isnull=True
        )
        
        self.check(
            '  Orphaned ClientBranch',
            not orphaned_cb.exists(),
            f'Найдено {orphaned_cb.count()} ClientBranch без client или branch'
        )

        # Проверка orphaned CoinTransaction
        orphaned_tx = CoinTransaction.objects.filter(
            client__isnull=True
        )
        
        self.check(
            '  Orphaned CoinTransaction',
            not orphaned_tx.exists(),
            f'Найдено {orphaned_tx.count()} CoinTransaction без client'
        )

    def verify_business_logic(self):
        """Проверка бизнес-логики"""
        
        # Проверка: у каждого активного ClientBranch должен быть хотя бы 1 визит или транзакция
        for company in Company.objects.all():
            with tenant_context(company):
                active_clients = ClientBranch.objects.annotate(
                    tx_count=Count('transactions')
                ).filter(tx_count=0)
                
                self.check(
                    f'  Активность клиентов ({company.name})',
                    active_clients.count() < ClientBranch.objects.count() * 0.5,
                    f'{active_clients.count()} клиентов без транзакций',
                    warning=True
                )

        # Проверка: сумма всех INCOME должна быть >= сумме всех EXPENSE
        for company in Company.objects.all():
            with tenant_context(company):
                total_income = CoinTransaction.objects.filter(
                    type=CoinTransaction.Type.INCOME
                ).aggregate(total=Sum('amount'))['total'] or 0
                
                total_expense = CoinTransaction.objects.filter(
                    type=CoinTransaction.Type.EXPENSE
                ).aggregate(total=Sum('amount'))['total'] or 0
                
                self.check(
                    f'  Баланс системы ({company.name})',
                    total_income >= total_expense,
                    f'Траты превышают доходы: {total_expense} > {total_income}'
                )

    def print_verification_report(self):
        """Вывод отчета о проверке"""
        self.stdout.write('\n' + '=' * 80)
        self.stdout.write(self.style.SUCCESS('ОТЧЕТ О ПРОВЕРКЕ'))
        self.stdout.write('=' * 80)
        
        self.stdout.write(f'\nПроверок выполнено: {self.checks_total}')
        self.stdout.write(f'Успешно: {self.checks_passed}')
        
        if self.warnings:
            self.stdout.write(f'\n⚠ Предупреждения: {len(self.warnings)}')
            for warning in self.warnings[:10]:
                self.stdout.write(f'  - {warning}')
        
        if self.errors:
            self.stdout.write(f'\n❌ Ошибки: {len(self.errors)}')
            for error in self.errors[:10]:
                self.stdout.write(self.style.ERROR(f'  - {error}'))
        
        self.stdout.write('\n' + '=' * 80)
        
        if not self.errors:
            self.stdout.write(self.style.SUCCESS('✓ ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ'))
        else:
            self.stdout.write(self.style.ERROR('✗ ОБНАРУЖЕНЫ ОШИБКИ'))
        
        self.stdout.write('=' * 80)