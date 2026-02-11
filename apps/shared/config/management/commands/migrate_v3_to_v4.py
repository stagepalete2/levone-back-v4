"""
Django Management Command для миграции данных из LevOne v3 в v4

Использование:
    python manage.py migrate_v3_to_v4 --v3-db-name=levone_v3 --v3-db-host=localhost

Требования:
    1. Обе базы данных должны быть доступны
    2. v4 база должна иметь все миграции применены
    3. v3 база должна быть в read-only режиме (рекомендуется)
"""

import logging
from decimal import Decimal
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction, connections
from django.db.models import Q
from django.utils import timezone
from django_tenants.utils import schema_context, tenant_context

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Миграция данных из LevOne v3 в v4'

    def __init__(self):
        super().__init__()
        self.id_mapping = {
            'company': {},
            'domain': {},
            'client': {},
            'branch': {},
            'client_branch': {},
            'telegram_bot': {},
            'product': {},
            'quest': {},
            'rf_segment': {},
        }
        self.stats = {
            'companies': 0,
            'domains': 0,
            'clients': 0,
            'branches': 0,
            'client_branches': 0,
            'coin_transactions': 0,
            'products': 0,
            'quests': 0,
            'errors': [],
        }

    def add_arguments(self, parser):
        parser.add_argument(
            '--v3-db-name',
            type=str,
            required=True,
            help='Название базы данных v3'
        )
        parser.add_argument(
            '--v3-db-host',
            type=str,
            default='localhost',
            help='Хост базы данных v3'
        )
        parser.add_argument(
            '--v3-db-port',
            type=int,
            default=5432,
            help='Порт базы данных v3'
        )
        parser.add_argument(
            '--v3-db-user',
            type=str,
            default='postgres',
            help='Пользователь базы данных v3'
        )
        parser.add_argument(
            '--v3-db-password',
            type=str,
            default='',
            help='Пароль базы данных v3'
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Тестовый запуск без сохранения данных'
        )
        parser.add_argument(
            '--tenant-schema',
            type=str,
            help='Мигрировать только указанную схему tenant'
        )

    def handle(self, *args, **options):
        self.dry_run = options['dry_run']
        self.setup_v3_connection(options)

        self.stdout.write(self.style.WARNING('=' * 80))
        self.stdout.write(self.style.WARNING('МИГРАЦИЯ ДАННЫХ LEVONE V3 → V4'))
        self.stdout.write(self.style.WARNING('=' * 80))
        
        if self.dry_run:
            self.stdout.write(self.style.NOTICE('РЕЖИМ: DRY RUN (без сохранения)'))
        
        try:
            # Этап 1: Миграция PUBLIC schema (shared данные)
            self.stdout.write(self.style.SUCCESS('\n[1/6] Миграция PUBLIC schema...'))
            self.migrate_public_schema()

            # Этап 2: Получение списка tenant schemas
            self.stdout.write(self.style.SUCCESS('\n[2/6] Получение списка tenant schemas...'))
            tenant_schemas = self.get_tenant_schemas(options.get('tenant_schema'))

            # Этап 3-6: Миграция каждого tenant
            for idx, schema in enumerate(tenant_schemas, start=1):
                self.stdout.write(
                    self.style.SUCCESS(f'\n[{idx}/{len(tenant_schemas)}] Миграция schema: {schema}')
                )
                self.migrate_tenant_schema(schema)

            # Отчет
            self.print_migration_report()

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'\n❌ КРИТИЧЕСКАЯ ОШИБКА: {e}'))
            logger.exception("Migration failed")
            raise CommandError(f'Миграция прервана: {e}')
        finally:
            self.close_v3_connection()

    def setup_v3_connection(self, options):
        """Настройка подключения к БД v3"""
        connections.databases['v3'] = {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': options['v3_db_name'],
            'USER': options['v3_db_user'],
            'PASSWORD': options['v3_db_password'],
            'HOST': options['v3_db_host'],
            'PORT': options['v3_db_port'],
            'OPTIONS': {},  # Обязательный параметр для PostgreSQL
            'TIME_ZONE': None,        # <--- Именно из-за этого сейчас ошибка
            'CONN_MAX_AGE': 0,        # Время жизни соединения
            'OPTIONS': {},            # Опции драйвера (мы добавляли в прошлый раз)
            'ATOMIC_REQUESTS': False, # Оборачивать ли запросы в транзакции
            'AUTOCOMMIT': True,
            'CONN_HEALTH_CHECKS': False,
        }
        self.v3_cursor = connections['v3'].cursor()

    def close_v3_connection(self):
        """Закрытие подключения к БД v3"""
        if hasattr(self, 'v3_cursor'):
            self.v3_cursor.close()
        connections['v3'].close()

    def get_tenant_schemas(self, specific_schema: Optional[str] = None) -> list:
        """Получение списка tenant schemas из v3"""
        query = "SELECT schema_name FROM public.company_company WHERE schema_name != 'public'"
        
        if specific_schema:
            query += f" AND schema_name = '{specific_schema}'"
        
        self.v3_cursor.execute(query)
        schemas = [row[0] for row in self.v3_cursor.fetchall()]
        
        self.stdout.write(f'  Найдено schemas: {len(schemas)}')
        return schemas

    # =========================================================================
    # МИГРАЦИЯ PUBLIC SCHEMA
    # =========================================================================

    def migrate_public_schema(self):
        """Миграция данных в public schema"""
        from apps.shared.clients.models import Company, Domain, CompanyConfig
        from apps.shared.guest.models import Client

        # 1. Company
        self.stdout.write('  → Миграция Company...')
        self.v3_cursor.execute("""
            SELECT id, schema_name, name, description, is_active, paid_until, 
                   vk_group_name, vk_group_id, logotype_image, coin_image, card_image,
                   created_on, updated_at
            FROM public.company_company
        """)
        
        for row in self.v3_cursor.fetchall():
            v3_id = row[0]
            
            with transaction.atomic():
                # Создание Company
                company = Company(
                    schema_name=row[1],
                    name=row[2],
                    description=row[3] or '',
                    is_active=row[4],
                    paid_until=row[5],
                    created_at=row[11] or timezone.now(),
                    updated_at=row[12] or timezone.now(),
                )
                
                if not self.dry_run:
                    company.save()
                    self.id_mapping['company'][v3_id] = company.id

                # Создание CompanyConfig
                config = CompanyConfig(
                    company=company,
                    vk_group_name=row[6] or 'Кафе LevOne',
                    vk_group_id=row[7] or '211202938',
                    logotype_image=row[8] or '',
                    coin_image=row[9] or '',
                )
                
                if not self.dry_run:
                    config.save()

                self.stats['companies'] += 1

        self.stdout.write(f'    ✓ Мигрировано компаний: {self.stats["companies"]}')

        # 2. Domain
        self.stdout.write('  → Миграция Domain...')
        self.v3_cursor.execute("""
            SELECT id, domain, tenant_id, is_primary
            FROM public.company_domain
        """)
        
        for row in self.v3_cursor.fetchall():
            v3_id = row[0]
            v3_tenant_id = row[2]
            
            if v3_tenant_id not in self.id_mapping['company']:
                continue

            with transaction.atomic():
                domain = Domain(
                    domain=row[1],
                    tenant_id=self.id_mapping['company'][v3_tenant_id],
                    is_primary=row[3],
                )
                
                if not self.dry_run:
                    domain.save()
                    self.id_mapping['domain'][v3_id] = domain.id

                self.stats['domains'] += 1

        self.stdout.write(f'    ✓ Мигрировано доменов: {self.stats["domains"]}')

        # 3. Client (VK пользователи)
        self.stdout.write('  → Миграция VK Client...')
        self.v3_cursor.execute("""
            SELECT id, vk_user_id, name, lastname, sex, registered_on, modified
            FROM public.clients_client
        """)
        
        for row in self.v3_cursor.fetchall():
            v3_id = row[0]
            
            try:
                vk_user_id = int(row[1]) if row[1] else 0
            except (ValueError, TypeError):
                self.stdout.write(
                    self.style.WARNING(f'    ! Пропущен клиент {v3_id}: некорректный vk_user_id')
                )
                continue

            with transaction.atomic():
                client, created = Client.objects.get_or_create(
                    vk_user_id=vk_user_id,
                    defaults={
                        'name': row[2] or '',
                        'lastname': row[3] or '',
                        'sex': row[4] or 0,
                        'created_at': row[5] or timezone.now(),
                        'updated_at': row[6] or timezone.now(),
                    }
                )
                
                if not self.dry_run and created:
                    self.id_mapping['client'][v3_id] = client.id
                    self.stats['clients'] += 1

        self.stdout.write(f'    ✓ Мигрировано клиентов: {self.stats["clients"]}')

    # =========================================================================
    # МИГРАЦИЯ TENANT SCHEMA
    # =========================================================================

    def migrate_tenant_schema(self, schema_name: str):
        """Миграция данных конкретного tenant schema"""
        from apps.shared.clients.models import Company
        
        try:
            company = Company.objects.get(schema_name=schema_name)
        except Company.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'  ❌ Company для schema {schema_name} не найдена'))
            return

        with tenant_context(company):
            self.migrate_branches(schema_name)
            self.migrate_client_branches(schema_name)
            self.migrate_coin_transactions(schema_name)
            self.migrate_products(schema_name)
            self.migrate_game_data(schema_name)
            self.migrate_quest_data(schema_name)
            self.migrate_inventory_data(schema_name)
            self.migrate_rf_segments(schema_name)
            self.migrate_telegram_bots(schema_name)
            self.migrate_story_images(schema_name)
            self.migrate_delivery_codes(schema_name)

    def migrate_branches(self, schema_name: str):
        """Миграция Branch и BranchConfig"""
        from apps.shared.clients.models import Company
        from apps.tenant.branch.models import Branch, BranchConfig

        self.stdout.write('  → Миграция Branch...')
        
        company = Company.objects.get(schema_name=schema_name)
        
        self.v3_cursor.execute(f"""
            SELECT id, name, description, company_id, yandex_map, gis_map, 
                   created_on, updated_at
            FROM {schema_name}.branch_branch
        """)
        
        migrated = 0
        for row in self.v3_cursor.fetchall():
            v3_id = row[0]
            
            with transaction.atomic():
                # Создание Branch
                branch = Branch(
                    name=row[1],
                    description=row[2] or '',
                    company=company,
                    created_at=row[6] or timezone.now(),
                    updated_at=row[7] or timezone.now(),
                )
                
                if not self.dry_run:
                    branch.save()
                    self.id_mapping['branch'][v3_id] = branch.id

                # Создание BranchConfig
                config = BranchConfig(
                    branch=branch,
                    yandex_map=row[4] or '',
                    gis_map=row[5] or '',
                )
                
                if not self.dry_run:
                    config.save()

                migrated += 1
                self.stats['branches'] += 1

        self.stdout.write(f'    ✓ Мигрировано филиалов: {migrated}')

    def migrate_client_branches(self, schema_name: str):
        """Миграция ClientBranch"""
        from apps.shared.guest.models import Client
        from apps.tenant.branch.models import Branch, ClientBranch

        self.stdout.write('  → Миграция ClientBranch...')
        
        self.v3_cursor.execute(f"""
            SELECT id, client_id, branch_id, birth_date, phone, 
                   "isStoryUploaded", "isJoinedCommunity", "isAllowedMessageFromCommunity",
                   "isSuperPrizeWinned", "isReffered", "invitedBy_id",
                   created_on, updated_at
            FROM {schema_name}.branch_clientbranch
        """)
        
        migrated = 0
        for row in self.v3_cursor.fetchall():
            v3_id = row[0]
            v3_client_id = row[1]
            v3_branch_id = row[2]
            v3_invited_by_id = row[10]
            
            # Получение соответствующих объектов
            if v3_client_id not in self.id_mapping['client']:
                continue
            if v3_branch_id not in self.id_mapping['branch']:
                continue

            client = Client.objects.get(id=self.id_mapping['client'][v3_client_id])
            branch = Branch.objects.get(id=self.id_mapping['branch'][v3_branch_id])
            
            # invited_by обработается во втором проходе
            with transaction.atomic():
                client_branch, created = ClientBranch.objects.get_or_create(
                    client=client,
                    branch=branch,
                    defaults={
                        'birth_date': row[3],
                        'is_story_uploaded': row[5] or False,
                        'is_joined_community': row[6] or False,
                        'is_allowed_message': row[7] or False,
                        'is_super_prize_won': row[8] or False,
                        'created_at': row[11] or timezone.now(),
                        'updated_at': row[12] or timezone.now(),
                    }
                )
                
                if not self.dry_run and created:
                    self.id_mapping['client_branch'][v3_id] = client_branch.id
                    migrated += 1
                    self.stats['client_branches'] += 1

        # Второй проход: обновление invited_by
        self.v3_cursor.execute(f"""
            SELECT id, "invitedBy_id"
            FROM {schema_name}.branch_clientbranch
            WHERE "invitedBy_id" IS NOT NULL
        """)
        
        for row in self.v3_cursor.fetchall():
            v3_id = row[0]
            v3_invited_by_id = row[1]
            
            if v3_id not in self.id_mapping['client_branch']:
                continue
            if v3_invited_by_id not in self.id_mapping['client']:
                continue
                
            try:
                client_branch = ClientBranch.objects.get(id=self.id_mapping['client_branch'][v3_id])
                invited_by_client = Client.objects.get(id=self.id_mapping['client'][v3_invited_by_id])
                
                if not self.dry_run:
                    client_branch.invited_by = invited_by_client
                    client_branch.save(update_fields=['invited_by'])
            except (ClientBranch.DoesNotExist, Client.DoesNotExist):
                pass

        self.stdout.write(f'    ✓ Мигрировано профилей гостей: {migrated}')

    def migrate_coin_transactions(self, schema_name: str):
        """Миграция CoinTransaction с конвертацией типов"""
        from apps.tenant.branch.models import ClientBranch, CoinTransaction

        self.stdout.write('  → Миграция CoinTransaction...')
        
        # Маппинг типов и источников
        type_mapping = {
            'ДОХОД': CoinTransaction.Type.INCOME,
            'ТРАТА': CoinTransaction.Type.EXPENSE,
        }
        
        source_mapping = {
            'GAME': CoinTransaction.Source.GAME,
            'QUEST': CoinTransaction.Source.QUEST,
            'MANUAL': CoinTransaction.Source.MANUAL,
            'SHOP': CoinTransaction.Source.SHOP,
        }
        
        self.v3_cursor.execute(f"""
            SELECT id, client_id, type, source, amount, description, created_on
            FROM {schema_name}.branch_cointransaction
            ORDER BY created_on ASC
        """)
        
        migrated = 0
        for row in self.v3_cursor.fetchall():
            v3_client_id = row[1]
            
            if v3_client_id not in self.id_mapping['client_branch']:
                continue

            client_branch = ClientBranch.objects.get(id=self.id_mapping['client_branch'][v3_client_id])
            
            # Конвертация типа и источника
            transaction_type = type_mapping.get(row[2])
            transaction_source = source_mapping.get(row[3])
            
            if not transaction_type or not transaction_source:
                self.stdout.write(
                    self.style.WARNING(
                        f'    ! Пропущена транзакция: неизвестный тип/источник ({row[2]}/{row[3]})'
                    )
                )
                continue

            with transaction.atomic():
                coin_transaction = CoinTransaction(
                    client=client_branch,
                    type=transaction_type,
                    source=transaction_source,
                    amount=row[4],
                    description=row[5] or '',
                    created_at=row[6] or timezone.now(),
                )
                
                if not self.dry_run:
                    coin_transaction.save()
                    migrated += 1
                    self.stats['coin_transactions'] += 1

        self.stdout.write(f'    ✓ Мигрировано транзакций: {migrated}')

    def migrate_products(self, schema_name: str):
        """Миграция Product"""
        from apps.tenant.branch.models import Branch
        from apps.tenant.catalog.models import Product

        self.stdout.write('  → Миграция Product...')
        
        self.v3_cursor.execute(f"""
            SELECT id, name, description, image, price, branch_id, 
                   publish, super_prize, created_on, updated_at
            FROM {schema_name}.catalog_product
        """)
        
        migrated = 0
        for row in self.v3_cursor.fetchall():
            v3_id = row[0]
            v3_branch_id = row[5]
            
            if v3_branch_id not in self.id_mapping['branch']:
                continue

            branch = Branch.objects.get(id=self.id_mapping['branch'][v3_branch_id])
            
            with transaction.atomic():
                product = Product(
                    name=row[1],
                    description=row[2],
                    image=row[3] or '',
                    price=row[4],
                    branch=branch,
                    is_active=row[6],
                    is_super_prize=row[7],
                    created_at=row[8] or timezone.now(),
                    updated_at=row[9] or timezone.now(),
                )
                
                if not self.dry_run:
                    product.save()
                    self.id_mapping['product'][v3_id] = product.id
                    migrated += 1
                    self.stats['products'] += 1

        self.stdout.write(f'    ✓ Мигрировано продуктов: {migrated}')

    def migrate_game_data(self, schema_name: str):
        """Миграция данных игры"""
        from apps.tenant.branch.models import ClientBranch
        from apps.tenant.branch.models import Branch
        from apps.tenant.game.models import Cooldown, DailyCode, ClientAttempt

        self.stdout.write('  → Миграция Game данных...')
        
        # 1. Cooldown
        self.v3_cursor.execute(f"""
            SELECT client_id, activated_at, duration
            FROM {schema_name}.game_cooldown
        """)
        
        for row in self.v3_cursor.fetchall():
            v3_client_id = row[0]
            
            if v3_client_id not in self.id_mapping['client_branch']:
                continue

            client_branch = ClientBranch.objects.get(id=self.id_mapping['client_branch'][v3_client_id])
            
            cooldown, created = Cooldown.objects.get_or_create(
                client=client_branch,
                defaults={
                    'last_activated_at': row[1],
                    'duration': row[2] or timedelta(hours=18),
                }
            )

        # 2. DailyCode
        self.v3_cursor.execute(f"""
            SELECT date, code, branch_id, created_on, updated_at
            FROM {schema_name}.game_dailycode
        """)
        
        for row in self.v3_cursor.fetchall():
            v3_branch_id = row[2]
            
            if v3_branch_id not in self.id_mapping['branch']:
                continue

            branch = Branch.objects.get(id=self.id_mapping['branch'][v3_branch_id])
            
            DailyCode.objects.get_or_create(
                branch=branch,
                date=row[0],
                defaults={
                    'code': row[1],
                    'created_at': row[3] or timezone.now(),
                    'updated_at': row[4] or timezone.now(),
                }
            )

        # 3. ClientAttempt
        self.v3_cursor.execute(f"""
            SELECT client_id, served_by_id, created_on, updated_at
            FROM {schema_name}.game_clientattempt
        """)
        
        migrated = 0
        for row in self.v3_cursor.fetchall():
            v3_client_id = row[0]
            v3_served_by_id = row[1]
            
            if v3_client_id not in self.id_mapping['client_branch']:
                continue

            client_branch = ClientBranch.objects.get(id=self.id_mapping['client_branch'][v3_client_id])
            
            served_by = None
            if v3_served_by_id and v3_served_by_id in self.id_mapping['client_branch']:
                served_by = ClientBranch.objects.get(id=self.id_mapping['client_branch'][v3_served_by_id])
            
            attempt = ClientAttempt(
                client=client_branch,
                served_by=served_by,
                created_at=row[2] or timezone.now(),
                updated_at=row[3] or timezone.now(),
            )
            
            if not self.dry_run:
                attempt.save()
                migrated += 1

        self.stdout.write(f'    ✓ Мигрировано игр: {migrated}')

    def migrate_quest_data(self, schema_name: str):
        """Миграция квестов"""
        from apps.tenant.branch.models import Branch, ClientBranch
        from apps.tenant.quest.models import Quest, QuestSubmit, Cooldown, DailyCode

        self.stdout.write('  → Миграция Quest данных...')
        
        # 1. Quest
        self.v3_cursor.execute(f"""
            SELECT id, name, description, reward, branch_id, created_on, updated_at
            FROM {schema_name}.quest_quest
        """)
        
        migrated_quests = 0
        for row in self.v3_cursor.fetchall():
            v3_id = row[0]
            v3_branch_id = row[4]
            
            if v3_branch_id not in self.id_mapping['branch']:
                continue

            branch = Branch.objects.get(id=self.id_mapping['branch'][v3_branch_id])
            
            quest = Quest(
                name=row[1],
                description=row[2],
                reward=row[3],
                branch=branch,
                created_at=row[5] or timezone.now(),
                updated_at=row[6] or timezone.now(),
            )
            
            if not self.dry_run:
                quest.save()
                self.id_mapping['quest'][v3_id] = quest.id
                migrated_quests += 1
                self.stats['quests'] += 1

        # 2. QuestSubmit
        self.v3_cursor.execute(f"""
            SELECT client_id, quest_id, is_complete, activated_at, duration, 
                   created_on, updated_at, server_by_id
            FROM {schema_name}.quest_questsubmit
        """)
        
        migrated_submissions = 0
        for row in self.v3_cursor.fetchall():
            v3_client_id = row[0]
            v3_quest_id = row[1]
            v3_served_by_id = row[7]
            
            if v3_client_id not in self.id_mapping['client_branch']:
                continue
            if v3_quest_id not in self.id_mapping['quest']:
                continue

            client_branch = ClientBranch.objects.get(id=self.id_mapping['client_branch'][v3_client_id])
            quest = Quest.objects.get(id=self.id_mapping['quest'][v3_quest_id])
            
            served_by = None
            if v3_served_by_id and v3_served_by_id in self.id_mapping['client_branch']:
                served_by = ClientBranch.objects.get(id=self.id_mapping['client_branch'][v3_served_by_id])
            
            submission = QuestSubmit(
                client=client_branch,
                quest=quest,
                is_complete=row[2],
                activated_at=row[3],
                duration=row[4] or timedelta(minutes=30),
                served_by=served_by,
                created_at=row[5] or timezone.now(),
                updated_at=row[6] or timezone.now(),
            )
            
            if not self.dry_run:
                submission.save()
                migrated_submissions += 1

        # 3. Cooldown
        self.v3_cursor.execute(f"""
            SELECT client_id, activated_at, duration
            FROM {schema_name}.quest_cooldown
        """)
        
        for row in self.v3_cursor.fetchall():
            v3_client_id = row[0]
            
            if v3_client_id not in self.id_mapping['client_branch']:
                continue

            client_branch = ClientBranch.objects.get(id=self.id_mapping['client_branch'][v3_client_id])
            
            Cooldown.objects.get_or_create(
                client=client_branch,
                defaults={
                    'last_activated_at': row[1],
                    'duration': row[2] or timedelta(hours=18),
                }
            )

        # 4. DailyCode
        self.v3_cursor.execute(f"""
            SELECT date, code, branch_id, created_on, updated_at
            FROM {schema_name}.quest_dailycode
        """)
        
        for row in self.v3_cursor.fetchall():
            v3_branch_id = row[2]
            
            if v3_branch_id not in self.id_mapping['branch']:
                continue

            branch = Branch.objects.get(id=self.id_mapping['branch'][v3_branch_id])
            
            DailyCode.objects.get_or_create(
                branch=branch,
                date=row[0],
                defaults={
                    'code': row[1],
                    'created_at': row[3] or timezone.now(),
                    'updated_at': row[4] or timezone.now(),
                }
            )

        self.stdout.write(f'    ✓ Мигрировано квестов: {migrated_quests}, выполнений: {migrated_submissions}')

    def migrate_inventory_data(self, schema_name: str):
        """Миграция инвентаря"""
        from apps.tenant.branch.models import ClientBranch
        from apps.tenant.catalog.models import Product
        from apps.tenant.inventory.models import Inventory, SuperPrize, Cooldown

        self.stdout.write('  → Миграция Inventory данных...')
        
        # 1. InventoryTransaction → Inventory
        self.v3_cursor.execute(f"""
            SELECT client_id, product_id, acquired_from, duration, description, 
                   created_on, updated_at, activated_at
            FROM {schema_name}.inventory_inventorytransaction
        """)
        
        migrated_inventory = 0
        for row in self.v3_cursor.fetchall():
            v3_client_id = row[0]
            v3_product_id = row[1]
            
            if v3_client_id not in self.id_mapping['client_branch']:
                continue
            if v3_product_id not in self.id_mapping['product']:
                continue

            client_branch = ClientBranch.objects.get(id=self.id_mapping['client_branch'][v3_client_id])
            product = Product.objects.get(id=self.id_mapping['product'][v3_product_id])
            
            inventory = Inventory(
                client=client_branch,
                product=product,
                acquired_from=row[2],
                duration=row[3] or timedelta(minutes=40),
                description=row[4] or '',
                activated_at=row[7],
                created_at=row[5] or timezone.now(),
                updated_at=row[6] or timezone.now(),
            )
            
            if not self.dry_run:
                inventory.save()
                migrated_inventory += 1

        # 2. SuperPrizeTransaction → SuperPrize
        self.v3_cursor.execute(f"""
            SELECT client_id, acquired_from, product_id, activated_at, is_activated,
                   created_on, updated_at
            FROM {schema_name}.inventory_superprizetransaction
        """)
        
        migrated_superprize = 0
        for row in self.v3_cursor.fetchall():
            v3_client_id = row[0]
            v3_product_id = row[2]
            
            if v3_client_id not in self.id_mapping['client_branch']:
                continue

            client_branch = ClientBranch.objects.get(id=self.id_mapping['client_branch'][v3_client_id])
            
            product = None
            if v3_product_id and v3_product_id in self.id_mapping['product']:
                product = Product.objects.get(id=self.id_mapping['product'][v3_product_id])
            
            superprize = SuperPrize(
                client=client_branch,
                acquired_from=row[1],
                product=product,
                activated_at=row[3],
                created_at=row[5] or timezone.now(),
                updated_at=row[6] or timezone.now(),
            )
            
            if not self.dry_run:
                superprize.save()
                migrated_superprize += 1

        # 3. Cooldown
        self.v3_cursor.execute(f"""
            SELECT client_id, activated_at, duration
            FROM {schema_name}.inventory_cooldown
        """)
        
        for row in self.v3_cursor.fetchall():
            v3_client_id = row[0]
            
            if v3_client_id not in self.id_mapping['client_branch']:
                continue

            client_branch = ClientBranch.objects.get(id=self.id_mapping['client_branch'][v3_client_id])
            
            Cooldown.objects.get_or_create(
                client=client_branch,
                defaults={
                    'last_activated_at': row[1],
                    'duration': row[2] or timedelta(hours=18),
                }
            )

        self.stdout.write(
            f'    ✓ Мигрировано предметов: {migrated_inventory}, суперпризов: {migrated_superprize}'
        )

    def migrate_rf_segments(self, schema_name: str):
        """Миграция RF сегментации"""
        from apps.tenant.branch.models import Branch, ClientBranch
        from apps.tenant.stats.models import (
            RFSegment, GuestRFScore, RFMigrationLog, RFSettings, BranchSegmentSnapshot
        )

        self.stdout.write('  → Миграция RF Segments...')
        
        # 1. RFSegment
        self.v3_cursor.execute(f"""
            SELECT id, code, name, recency_min, recency_max, frequency_min, frequency_max,
                   emoji, color, strategy
            FROM {schema_name}.stats_rfsegment
        """)
        
        for row in self.v3_cursor.fetchall():
            v3_id = row[0]
            
            segment, created = RFSegment.objects.get_or_create(
                code=row[1],
                defaults={
                    'name': row[2],
                    'recency_min': row[3],
                    'recency_max': row[4],
                    'frequency_min': row[5],
                    'frequency_max': row[6],
                    'emoji': row[7],
                    'color': row[8],
                    'strategy': row[9],
                }
            )
            
            if not self.dry_run:
                self.id_mapping['rf_segment'][v3_id] = segment.id

        # 2. GuestRFScore
        self.v3_cursor.execute(f"""
            SELECT client_id, recency_days, frequency, r_score, f_score, segment_id, calculated_at
            FROM {schema_name}.stats_guestrfscore
        """)
        
        migrated_scores = 0
        for row in self.v3_cursor.fetchall():
            v3_client_id = row[0]
            v3_segment_id = row[5]
            
            if v3_client_id not in self.id_mapping['client_branch']:
                continue

            client_branch = ClientBranch.objects.get(id=self.id_mapping['client_branch'][v3_client_id])
            
            segment = None
            if v3_segment_id and v3_segment_id in self.id_mapping['rf_segment']:
                segment = RFSegment.objects.get(id=self.id_mapping['rf_segment'][v3_segment_id])
            
            score, created = GuestRFScore.objects.get_or_create(
                client=client_branch,
                defaults={
                    'recency_days': row[1],
                    'frequency': row[2],
                    'r_score': row[3],
                    'f_score': row[4],
                    'segment': segment,
                    'calculated_at': row[6] or timezone.now(),
                }
            )
            
            if created:
                migrated_scores += 1

        # 3. RFSettings
        self.v3_cursor.execute(f"""
            SELECT branch_id, analysis_period
            FROM {schema_name}.stats_rfsettings
        """)
        
        for row in self.v3_cursor.fetchall():
            v3_branch_id = row[0]
            
            if v3_branch_id not in self.id_mapping['branch']:
                continue

            branch = Branch.objects.get(id=self.id_mapping['branch'][v3_branch_id])
            
            RFSettings.objects.get_or_create(
                branch=branch,
                defaults={
                    'analysis_period': row[1] or 365,
                }
            )

        self.stdout.write(f'    ✓ Мигрировано RF scores: {migrated_scores}')

    def migrate_telegram_bots(self, schema_name: str):
        """Миграция телеграм ботов"""
        from apps.tenant.branch.models import Branch, TelegramBot, BotAdmin

        self.stdout.write('  → Миграция Telegram Bots...')
        
        # 1. TelegramBot
        self.v3_cursor.execute(f"""
            SELECT id, bot_api, bot_name, branch_id
            FROM {schema_name}.branch_telegrambot
        """)
        
        migrated_bots = 0
        for row in self.v3_cursor.fetchall():
            v3_id = row[0]
            v3_branch_id = row[3]
            
            if v3_branch_id not in self.id_mapping['branch']:
                continue

            branch = Branch.objects.get(id=self.id_mapping['branch'][v3_branch_id])
            
            bot = TelegramBot(
                name=row[2],
                bot_username=row[2].replace(' ', '_').lower(),  # Генерация username
                api=row[1],
                branch=branch,
            )
            
            if not self.dry_run:
                bot.save()
                self.id_mapping['telegram_bot'][v3_id] = bot.id
                migrated_bots += 1

        # 2. BotAdmins
        self.v3_cursor.execute(f"""
            SELECT bot_id, telegram_chat_id, name, is_active, created_on, updated_at
            FROM {schema_name}.branch_botadmins
        """)
        
        migrated_admins = 0
        for row in self.v3_cursor.fetchall():
            v3_bot_id = row[0]
            
            if v3_bot_id not in self.id_mapping['telegram_bot']:
                continue

            bot = TelegramBot.objects.get(id=self.id_mapping['telegram_bot'][v3_bot_id])
            
            admin = BotAdmin(
                bot=bot,
                chat_id=row[1],
                name=row[2],
                is_active=row[3],
                created_at=row[4] or timezone.now(),
                updated_at=row[5] or timezone.now(),
            )
            
            if not self.dry_run:
                admin.save()
                migrated_admins += 1

        self.stdout.write(f'    ✓ Мигрировано ботов: {migrated_bots}, админов: {migrated_admins}')

    def migrate_story_images(self, schema_name: str):
        """Миграция фото для сториса"""
        from apps.tenant.branch.models import Branch, StoryImage

        self.stdout.write('  → Миграция StoryImage...')
        
        self.v3_cursor.execute(f"""
            SELECT image, branch_id, created_on, updated_at
            FROM {schema_name}.branch_storyimage
        """)
        
        migrated = 0
        for row in self.v3_cursor.fetchall():
            v3_branch_id = row[1]
            
            if v3_branch_id not in self.id_mapping['branch']:
                continue

            branch = Branch.objects.get(id=self.id_mapping['branch'][v3_branch_id])
            
            story_image = StoryImage(
                image=row[0],
                branch=branch,
                created_at=row[2] or timezone.now(),
                updated_at=row[3] or timezone.now(),
            )
            
            if not self.dry_run:
                story_image.save()
                migrated += 1

        self.stdout.write(f'    ✓ Мигрировано фото: {migrated}')

    def migrate_delivery_codes(self, schema_name: str):
        """Миграция кодов доставки с пропуском дубликатов"""
        from apps.tenant.branch.models import Branch
        from apps.tenant.delivery.models import Delivery
        from django.db.utils import IntegrityError  # Обязательно импортируйте ошибку
        from datetime import timedelta

        self.stdout.write('  → Миграция Delivery Codes...')
        
        self.v3_cursor.execute(f"""
            SELECT code, duration, created_on, updated_at
            FROM {schema_name}.branch_deliverycodes
        """)
        
        migrated = 0
        skipped = 0
        
        # Получаем первый branch для привязки
        try:
            first_branch = Branch.objects.first()
            if not first_branch:
                self.stdout.write('    ! Нет доступных филиалов для привязки кодов доставки')
                return
        except Branch.DoesNotExist:
            return
        
        rows = self.v3_cursor.fetchall()
        for row in rows:
            # --- ВАЖНО: Определяем переменную code в самом начале цикла ---
            code = row[0] 
            # -------------------------------------------------------------

            # 1. ПРОВЕРКА: Если такой код уже есть в базе — пропускаем
            if Delivery.objects.filter(code=code).exists():
                skipped += 1
                # Можно вывести в консоль, если нужно видеть каждый пропуск:
                # self.stdout.write(f'    ! Пропущен дубликат: {code}') 
                continue

            delivery = Delivery(
                code=code,
                branch=first_branch,
                duration=row[1] or timedelta(hours=3),
                created_at=row[2] or timezone.now(),
                updated_at=row[3] or timezone.now(),
            )
            
            # Сохраняем только если не Dry Run
            if not self.dry_run:
                try:
                    delivery.save()
                    migrated += 1
                except IntegrityError:
                    # Ловим дубликаты, если они проскочили проверку выше
                    skipped += 1
                    self.stdout.write(self.style.WARNING(f'    ! Ошибка IntegrityError при сохранении: {code}'))

        self.stdout.write(f'    ✓ Мигрировано кодов: {migrated}, Пропущено дубликатов: {skipped}')

    # =========================================================================
    # ОТЧЕТ
    # =========================================================================

    def print_migration_report(self):
        """Вывод отчета о миграции"""
        self.stdout.write('\n' + '=' * 80)
        self.stdout.write(self.style.SUCCESS('ОТЧЕТ О МИГРАЦИИ'))
        self.stdout.write('=' * 80)
        
        self.stdout.write(f'\n✓ Компании: {self.stats["companies"]}')
        self.stdout.write(f'✓ Домены: {self.stats["domains"]}')
        self.stdout.write(f'✓ VK Клиенты: {self.stats["clients"]}')
        self.stdout.write(f'✓ Филиалы: {self.stats["branches"]}')
        self.stdout.write(f'✓ Профили гостей: {self.stats["client_branches"]}')
        self.stdout.write(f'✓ Транзакции монет: {self.stats["coin_transactions"]}')
        self.stdout.write(f'✓ Продукты: {self.stats["products"]}')
        self.stdout.write(f'✓ Квесты: {self.stats["quests"]}')
        
        if self.stats['errors']:
            self.stdout.write(f'\n⚠ Ошибки: {len(self.stats["errors"])}')
            for error in self.stats['errors'][:10]:  # Показываем первые 10
                self.stdout.write(f'  - {error}')
        
        self.stdout.write('\n' + '=' * 80)
        
        if self.dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN: Данные НЕ были сохранены'))
        else:
            self.stdout.write(self.style.SUCCESS('✓ МИГРАЦИЯ ЗАВЕРШЕНА УСПЕШНО'))
        
        self.stdout.write('=' * 80)