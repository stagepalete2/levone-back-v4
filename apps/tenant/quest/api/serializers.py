from rest_framework import serializers
from django.utils.timezone import now
from django.core.exceptions import ValidationError as DjangoValidationError

from apps.tenant.quest.core import QuestService
from apps.tenant.quest.models import Quest, QuestSubmit, Cooldown, DailyCode

# Импорты из других приложений (предполагаем их наличие по контексту)
from apps.tenant.branch.models import Branch, ClientBranch
from apps.shared.guest.models import Client as BaseClient

# --- Output Serializers (для чтения) ---

class QuestSerializer(serializers.ModelSerializer):
    completed = serializers.BooleanField(read_only=True)

    class Meta:
        model = Quest
        fields = ['id', 'name', 'description', 'reward', 'completed']

class QuestSubmitSerializer(serializers.ModelSerializer):
    quest = QuestSerializer(read_only=True)
    time_left_seconds = serializers.SerializerMethodField()

    class Meta:
        model = QuestSubmit
        fields = ['id', 'quest', 'is_complete', 'activated_at', 'duration', 'time_left', 'time_left_seconds']

    def get_time_left_seconds(self, obj):
        return obj.time_left.total_seconds()

class CooldownSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cooldown
        fields = ['client', 'last_activated_at', 'duration', 'time_left', 'is_active']


# --- Input / Action Serializers (для записи и действий) ---

class BaseQuestActionSerializer(serializers.Serializer):
    """Базовый класс для валидации vk_user_id и branch"""
    vk_user_id = serializers.IntegerField(write_only=True)
    branch = serializers.IntegerField(write_only=True)

    def validate(self, attrs):
        vk_user_id = attrs.get('vk_user_id')
        branch_id = attrs.get('branch')

        # 1. Валидация Branch
        try:
            branch = Branch.objects.get(id=branch_id)
        except Branch.DoesNotExist:
            raise serializers.ValidationError({"branch": "Ресторан с таким id отсутствует"})

        # 2. Валидация Client
        client = BaseClient.objects.filter(vk_user_id=vk_user_id).first()
        if not client:
            raise serializers.ValidationError({"vk_user_id": "Клиент с таким vk_user_id отсутствует"})

        # 3. Валидация связи
        branch_client = ClientBranch.objects.filter(client=client, branch=branch).first()
        if not branch_client:
            raise serializers.ValidationError("Клиент не связан с этим рестораном")

        # Сохраняем объекты в context или attrs для использования в create
        attrs['branch_obj'] = branch
        attrs['client_branch_obj'] = branch_client
        return attrs


class ActivateQuestSerializer(BaseQuestActionSerializer):
    quest_id = serializers.IntegerField(write_only=True)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        
        # Валидация квеста
        try:
            quest = Quest.objects.get(id=attrs['quest_id'], branch=attrs['branch_obj'])
        except Quest.DoesNotExist:
            raise serializers.ValidationError({"quest_id": "Задание не найдено или не принадлежит этому ресторану"})
        
        attrs['quest_obj'] = quest
        return attrs

    def create(self, validated_data):
        client_branch = validated_data['client_branch_obj']
        quest = validated_data['quest_obj']

        try:
            # Вызов бизнес-логики
            instance = QuestService.activate_quest(client_branch, quest)
            return instance
        except DjangoValidationError as e:
            raise serializers.ValidationError({"code": "cooldown", "message": str(e)})


class SubmitQuestSerializer(BaseQuestActionSerializer):
    quest_id = serializers.IntegerField(write_only=True)
    code = serializers.CharField(write_only=True)
    employee_id = serializers.IntegerField(write_only=True, required=False, allow_null=True) # vk_id сотрудника

    def validate(self, attrs):
        attrs = super().validate(attrs)
        branch = attrs['branch_obj']
        client_branch = attrs['client_branch_obj']
        code_input = attrs['code']

        # 1. Проверяем наличие активного сабмита
        try:
            quest_submit = QuestSubmit.objects.get(
                client=client_branch,
                quest_id=attrs['quest_id'],
                is_complete=False
            )
        except QuestSubmit.DoesNotExist:
             raise serializers.ValidationError("Активное задание не найдено")

        # 2. Проверяем время (логика модели)
        if quest_submit.time_left.total_seconds() <= 0:
            raise serializers.ValidationError("Время на выполнение задания истекло")

        # 3. Проверяем Код дня
        from django.utils.timezone import now as _now
        today = _now().date()
        latest_code = DailyCode.objects.filter(branch=branch, date=today).first()
        if not latest_code:
            # Автогенерация кода если celery не создал его
            from apps.shared.config.utils import generate_code
            latest_code = DailyCode.objects.create(
                branch=branch,
                date=today,
                code=generate_code()
            )
        
        if latest_code.date < today:
             raise serializers.ValidationError("Код дня просрочен")

        if code_input != latest_code.code:
             raise serializers.ValidationError({"code": "Код дня не действителен"})

        # 4. Проверяем сотрудника (если передан)
        employee_client_branch = None
        if 'employee_id' in attrs:
            # Ищем сотрудника среди ClientBranch, у которых есть привязка к Employees (или роль)
            # В вашей старой модели было employee -> client -> client -> vk_user_id
            # В новой модели served_by ссылается на ClientBranch.
            # Предположим, что employee_id это vk_user_id сотрудника.
            emp_client = BaseClient.objects.filter(vk_user_id=attrs['employee_id']).first()
            if emp_client:
                employee_client_branch = ClientBranch.objects.filter(client=emp_client, branch=branch).first()
        
        attrs['quest_submit_obj'] = quest_submit
        attrs['employee_cb_obj'] = employee_client_branch
        return attrs

    def create(self, validated_data):
        quest_submit = validated_data['quest_submit_obj']
        employee = validated_data['employee_cb_obj']

        # Вызов бизнес-логики
        return QuestService.submit_quest(
            client_branch=quest_submit.client,
            quest_submit=quest_submit,
            employee_client_branch=employee
        )

class CooldownActionSerializer(BaseQuestActionSerializer):
    """Для ручной установки кулдауна через POST"""
    def create(self, validated_data):
        return QuestService.set_cooldown(validated_data['client_branch_obj'])