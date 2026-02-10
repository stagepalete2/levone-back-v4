from django.db import transaction
from django.utils.timezone import now
from django.core.exceptions import ValidationError
from datetime import timedelta

# Импортируем модели
from apps.tenant.quest.models import Quest, QuestSubmit, Cooldown, DailyCode
from apps.tenant.branch.models import CoinTransaction

class QuestService:
    
    @staticmethod
    def get_list(branch, client_branch):
        """
        Возвращает список квестов с флагом завершения для конкретного клиента.
        """
        quests = Quest.objects.filter(branch=branch, is_active=True)
        
        # Получаем ID завершенных квестов
        completed_ids = set(
            QuestSubmit.objects.filter(
                client=client_branch, 
                is_complete=True
            ).values_list("quest_id", flat=True)
        )

        # Формируем структуру данных (можно делать и в сериализаторе, 
        # но сервис подготавливает "чистые" данные)
        results = []
        for q in quests:
            results.append({
                "quest": q,
                "completed": q.id in completed_ids
            })
        return results

    @staticmethod
    def get_active_submission(client_branch):
        """Возвращает активную попытку выполнения квеста или None."""
        submission = QuestSubmit.objects.filter(
            client=client_branch,
            is_complete=False,
        ).first()

        # Если квест просрочен
        if submission and submission.time_left <= timedelta(0):
            return None
            
        return submission

    @staticmethod
    def activate_quest(client_branch, quest):
        """
        Логика старта квеста.
        Проверяет кулдаун, создает запись QuestSubmit, обновляет Cooldown.
        
        Race condition fix: вся логика внутри transaction.atomic() с select_for_update()
        """
        with transaction.atomic():
            # 1. Получаем и блокируем кулдаун
            cooldown, _ = Cooldown.objects.select_for_update().get_or_create(
                client=client_branch,
                defaults={'last_activated_at': None}
            )
            
            if cooldown.is_active:
                raise ValidationError("Магазин квестов на перезарядке.")

            # 2. Создаем или получаем (на случай повторных кликов)
            quest_submit, created = QuestSubmit.objects.get_or_create(
                client=client_branch,
                quest=quest,
                is_complete=False
            )
            
            # 3. Обновляем время
            current_time = now()
            quest_submit.activated_at = current_time
            quest_submit.save(update_fields=['activated_at'])

            # 4. Обновляем кулдаун
            cooldown.last_activated_at = current_time
            cooldown.save(update_fields=['last_activated_at'])
            
            return quest_submit

    @staticmethod
    def submit_quest(client_branch, quest_submit, employee_client_branch=None):
        """
        Логика завершения квеста.
        Начисляет монеты, закрывает квест, обновляет кулдаун.
        Валидация кода происходит ДО этого метода в сериализаторе.
        """
        with transaction.atomic():
            # 1. Блокируем запись для обновления
            # Важно: делаем повторную проверку is_complete после блокировки!
            quest_submit = QuestSubmit.objects.select_for_update().get(id=quest_submit.id)
            
            if quest_submit.is_complete:
                # Если параллельный запрос уже закрыл квест
                return quest_submit 

            # 2. Обновляем статус
            quest_submit.is_complete = True
            quest_submit.served_by = employee_client_branch
            quest_submit.save(update_fields=['is_complete', 'served_by'])

            # 3. Начисляем монеты (через create_transfer, как описано в п.1)
            CoinTransaction.objects.create_transfer(
                client_branch=client_branch,
                amount=quest_submit.quest.reward,
                transaction_type=CoinTransaction.Type.INCOME,
                source=CoinTransaction.Source.QUEST,
                description=f'Задание: {quest_submit.quest.name}'
            )

            # 4. Обновляем кулдаун
            cooldown, _ = Cooldown.objects.select_for_update().get_or_create(client=client_branch)
            cooldown.last_activated_at = now()
            cooldown.save()

        return quest_submit

    @staticmethod
    def set_cooldown(client_branch):
        """Ручная установка кулдауна (если требуется отдельным запросом)"""
        cooldown, _ = Cooldown.objects.get_or_create(client=client_branch)
        cooldown.last_activated_at = now()
        cooldown.save()
        return cooldown