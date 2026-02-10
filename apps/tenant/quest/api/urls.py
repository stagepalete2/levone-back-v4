from django.urls import path

from apps.tenant.quest.api.views import QuestView, ActiveQuest, ActivateQuest, SubmitQuest, QuestCooldown

urlpatterns = [
    path('quest/', QuestView.as_view(), name='Квесты'),
    path('quest/active/', ActiveQuest.as_view(), name='Активный Квест'),
    path('quest/activate/', ActivateQuest.as_view(), name='Активировать Квест'),
	path('quest/submit/', SubmitQuest.as_view(), name='Сдать Квест'),
	path('quest/cooldown/', QuestCooldown.as_view(), name='Перезарядка Квестов')
]