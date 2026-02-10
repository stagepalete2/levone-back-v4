"""
Management command для популяции базы данных тестовыми данными.

Использование:
    python manage.py populate_test_data --tenant=<schema_name>

Создаёт тестовые данные для:
- Shared: MessageTemplate (шаблоны рассылок)
- Tenant: Branch, Products, Quests, Clients, Transactions, etc.
"""
import random
from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django_tenants.utils import schema_context, get_tenant_model


class Command(BaseCommand):
    help = 'Заполняет базу тестовыми данными для существующего тенанта'

    def add_arguments(self, parser):
        parser.add_argument(
            '--tenant',
            type=str,
            required=True,
            help='Schema name тенанта (например: levone)'
        )
        parser.add_argument(
            '--clients',
            type=int,
            default=20,
            help='Количество тестовых клиентов (по умолчанию: 20)'
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Очистить существующие тестовые данные перед созданием'
        )

    def handle(self, *args, **options):
        schema_name = options['tenant']
        num_clients = options['clients']
        clear_data = options['clear']
        
        # Проверяем существование тенанта
        TenantModel = get_tenant_model()
        try:
            tenant = TenantModel.objects.get(schema_name=schema_name)
        except TenantModel.DoesNotExist:
            raise CommandError(f'Тенант "{schema_name}" не найден')
        
        self.stdout.write(f'Заполняю тестовыми данными тенант: {schema_name}')
        
        with schema_context(schema_name):
            if clear_data:
                self._clear_test_data()
            
            # Создаём данные
            self._create_message_templates()
            branch = self._get_or_create_branch()
            self._create_products(branch)
            self._create_quests(branch)
            self._create_daily_codes(branch)
            clients = self._create_clients(branch, num_clients)
            self._create_transactions(clients)
            self._create_visits(clients)
            
        self.stdout.write(self.style.SUCCESS(f'✅ Готово! Создано {num_clients} клиентов'))

    def _clear_test_data(self):
        """Очищает тестовые данные (с префиксом TEST_)"""
        from apps.tenant.branch.models import ClientBranch, CoinTransaction
        from apps.shared.guest.models import Client
        
        # Удаляем тестовых клиентов
        test_clients = Client.objects.filter(first_name__startswith='Test_')
        count = test_clients.count()
        test_clients.delete()
        self.stdout.write(f'  Удалено {count} тестовых клиентов')

    def _create_message_templates(self):
        """Создаёт шаблоны рассылок с дефолтными текстами"""
        from apps.tenant.senler.models import MessageTemplate
        
        defaults = MessageTemplate.get_defaults()
        created = 0
        
        for template_type, default_text in defaults.items():
            _, was_created = MessageTemplate.objects.get_or_create(
                template_type=template_type,
                defaults={'text': default_text, 'is_active': True}
            )
            if was_created:
                created += 1
        
        self.stdout.write(f'  MessageTemplate: создано {created}, всего {len(defaults)}')

    def _get_or_create_branch(self):
        """Получает первый филиал или создаёт тестовый"""
        from apps.tenant.branch.models import Branch, BranchConfig
        
        branch = Branch.objects.first()
        if not branch:
            branch = Branch.objects.create(
                name='Тестовый Ресторан',
                description='Автоматически созданный тестовый ресторан'
            )
            BranchConfig.objects.create(branch=branch)
            self.stdout.write('  Branch: создан новый')
        else:
            self.stdout.write(f'  Branch: использую существующий "{branch.name}"')
        
        return branch

    def _create_products(self, branch):
        """Создаёт тестовые товары"""
        from apps.tenant.catalog.models import Product
        
        products_data = [
            {'name': 'Бесплатный кофе', 'price': 500, 'is_super_prize': False},
            {'name': 'Десерт в подарок', 'price': 800, 'is_super_prize': False},
            {'name': 'Скидка 20%', 'price': 1500, 'is_super_prize': False},
            {'name': 'Бутылка вина', 'price': 3000, 'is_super_prize': True},
            {'name': 'Ужин на двоих', 'price': 5000, 'is_super_prize': True},
        ]
        
        created = 0
        for data in products_data:
            _, was_created = Product.objects.get_or_create(
                name=data['name'],
                branch=branch,
                defaults={
                    'description': f'Тестовый приз: {data["name"]}',
                    'price': data['price'],
                    'is_super_prize': data['is_super_prize'],
                    'is_active': True,
                }
            )
            if was_created:
                created += 1
        
        self.stdout.write(f'  Products: создано {created}, всего {len(products_data)}')

    def _create_quests(self, branch):
        """Создаёт тестовые квесты"""
        from apps.tenant.quest.models import Quest
        
        quests_data = [
            {'name': 'Сделай фото блюда', 'reward': 100},
            {'name': 'Оставь отзыв', 'reward': 200},
            {'name': 'Пригласи друга', 'reward': 300},
            {'name': 'Закажи новинку', 'reward': 150},
        ]
        
        created = 0
        for data in quests_data:
            _, was_created = Quest.objects.get_or_create(
                name=data['name'],
                branch=branch,
                defaults={
                    'description': f'Тестовое задание: {data["name"]}',
                    'reward': data['reward'],
                    'is_active': True,
                }
            )
            if was_created:
                created += 1
        
        self.stdout.write(f'  Quests: создано {created}, всего {len(quests_data)}')

    def _create_daily_codes(self, branch):
        """Создаёт коды дня на неделю вперёд"""
        from apps.tenant.game.models import DailyCode
        
        today = date.today()
        created = 0
        
        for i in range(7):
            code_date = today + timedelta(days=i)
            code = f'TEST{code_date.strftime("%d%m")}'
            _, was_created = DailyCode.objects.get_or_create(
                date=code_date,
                branch=branch,
                defaults={'code': code}
            )
            if was_created:
                created += 1
        
        self.stdout.write(f'  DailyCode: создано {created} на 7 дней')

    def _create_clients(self, branch, count):
        """Создаёт тестовых клиентов"""
        from apps.shared.guest.models import Client
        from apps.tenant.branch.models import ClientBranch
        
        first_names = ['Алексей', 'Мария', 'Дмитрий', 'Анна', 'Иван', 'Екатерина', 'Сергей', 'Ольга']
        last_names = ['Иванов', 'Петров', 'Сидоров', 'Козлов', 'Новиков', 'Морозов', 'Волков', 'Соколов']
        
        created_clients = []
        
        for i in range(count):
            vk_user_id = 100000000 + i  # Тестовые VK ID
            
            # Создаём Client (shared)
            client, _ = Client.objects.get_or_create(
                vk_user_id=vk_user_id,
                defaults={
                    'name': f'Test_{random.choice(first_names)}',
                    'lastname': random.choice(last_names),
                }
            )
            
            # Создаём ClientBranch (tenant)
            # Генерируем случайную дату рождения (18-60 лет назад)
            birth_date = date.today() - timedelta(days=random.randint(18*365, 60*365))
            
            client_branch, _ = ClientBranch.objects.get_or_create(
                client=client,
                branch=branch,
                defaults={
                    'birth_date': birth_date,
                    'is_allowed_message': random.choice([True, False]),
                }
            )
            created_clients.append(client_branch)
        
        self.stdout.write(f'  Clients: обработано {count}')
        return created_clients

    def _create_transactions(self, clients):
        """Создаёт тестовые транзакции монет"""
        from apps.tenant.branch.models import CoinTransaction
        
        # Реальные источники из CoinTransaction.Source
        sources = [
            CoinTransaction.Source.GAME,
            CoinTransaction.Source.QUEST,
            CoinTransaction.Source.MANUAL,
        ]
        
        created = 0
        for client in clients:
            # 3-10 транзакций на клиента
            for _ in range(random.randint(3, 10)):
                amount = random.choice([50, 100, 150, 200, 300])
                CoinTransaction.objects.create(
                    client=client,
                    amount=amount,
                    type=CoinTransaction.Type.INCOME,
                    source=random.choice(sources),
                    description='Тестовая транзакция'
                )
                created += 1
        
        self.stdout.write(f'  CoinTransaction: создано {created}')

    def _create_visits(self, clients):
        """Создаёт тестовые визиты (QR сканы)"""
        from apps.tenant.branch.models import ClientBranchVisit
        
        created = 0
        for client in clients:
            # 1-5 визитов на клиента за последние 30 дней
            for _ in range(random.randint(1, 5)):
                days_ago = random.randint(0, 30)
                visit_time = timezone.now() - timedelta(days=days_ago, hours=random.randint(0, 12))
                
                ClientBranchVisit.objects.create(
                    client=client,
                    visited_at=visit_time
                )
                created += 1
        
        self.stdout.write(f'  ClientBranchVisit: создано {created}')
