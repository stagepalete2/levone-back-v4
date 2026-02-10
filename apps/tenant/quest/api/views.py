from django.shortcuts import render

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.status import HTTP_200_OK, HTTP_400_BAD_REQUEST


from apps.tenant.quest.core import QuestService
from apps.tenant.quest.api.serializers import (
    QuestSerializer, 
    QuestSubmitSerializer, 
    CooldownSerializer,
    ActivateQuestSerializer,
    SubmitQuestSerializer,
    CooldownActionSerializer,
    BaseQuestActionSerializer
)

class QuestView(APIView):
    def get(self, request):
        """Получить все задания"""
        # Используем валидатор для извлечения branch и client из query_params
        # Мы можем переиспользовать BaseQuestActionSerializer для валидации GET параметров
        validator = BaseQuestActionSerializer(data=request.query_params)
        if not validator.is_valid():
             return Response(validator.errors, status=HTTP_400_BAD_REQUEST)
        
        branch = validator.validated_data['branch_obj']
        client_branch = validator.validated_data['client_branch_obj']

        # Получаем данные через сервис
        data = QuestService.get_list(branch, client_branch)
        
        # Формируем ответ вручную, т.к. QuestService вернул словарь с объектом и флагом
        # Либо можно подать список объектов в QuestSerializer, но нам нужен флаг completed
        response_data = []
        for item in data:
            s_data = QuestSerializer(item['quest']).data
            s_data['completed'] = item['completed']
            response_data.append(s_data)

        return Response(response_data, status=HTTP_200_OK)


class ActiveQuest(APIView):
    def get(self, request):
        """Получить активный квест"""
        validator = BaseQuestActionSerializer(data=request.query_params)
        if not validator.is_valid():
             return Response(validator.errors, status=HTTP_400_BAD_REQUEST)
        
        client_branch = validator.validated_data['client_branch_obj']
        
        quest_submit = QuestService.get_active_submission(client_branch)
        
        if not quest_submit:
            return Response({}, status=HTTP_200_OK)

        serializer = QuestSubmitSerializer(quest_submit)
        return Response(serializer.data, status=HTTP_200_OK)


class ActivateQuest(APIView):
    def post(self, request):
        """Активировать квест"""
        serializer = ActivateQuestSerializer(data=request.data)
        if serializer.is_valid():
            quest_submit = serializer.save() # Вызовет QuestService.activate_quest
            return Response(QuestSubmitSerializer(quest_submit).data, status=HTTP_200_OK)
        
        return Response(serializer.errors, status=HTTP_400_BAD_REQUEST)


class SubmitQuest(APIView):
    def post(self, request):
        """Сдать квест кодом"""
        print(request.data)
        serializer = SubmitQuestSerializer(data=request.data)
        if serializer.is_valid():
            quest_submit = serializer.save()
            return Response(QuestSubmitSerializer(quest_submit).data, status=HTTP_200_OK)
        
        return Response(serializer.errors, status=HTTP_400_BAD_REQUEST)


class QuestCooldown(APIView):
    def get(self, request):
        """Получить статус перезарядки"""
        validator = BaseQuestActionSerializer(data=request.query_params)
        if not validator.is_valid():
             return Response(validator.errors, status=HTTP_400_BAD_REQUEST)
        
        client_branch = validator.validated_data['client_branch_obj']
        
        try:
            cooldown = client_branch.quest_cooldown_client
        except AttributeError:
             return Response({}, status=HTTP_200_OK)

        return Response(CooldownSerializer(cooldown).data, status=HTTP_200_OK)

    def post(self, request):
        """Установить перезарядку вручную"""
        serializer = CooldownActionSerializer(data=request.query_params) # или request.data, зависит от фронта
        if serializer.is_valid():
            cooldown = serializer.save()
            return Response(CooldownSerializer(cooldown).data, status=HTTP_200_OK)
            
        return Response(serializer.errors, status=HTTP_400_BAD_REQUEST)