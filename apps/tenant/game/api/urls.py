from django.urls import path

from apps.tenant.game.api.views import GamePlayView, GameCooldownView

urlpatterns = [
	path('game/play/', GamePlayView.as_view(), name='Play'),
	path('game/cooldown/', GameCooldownView.as_view(), name='Перезарядка игры'),
]

