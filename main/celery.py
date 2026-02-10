# main/celery.py
import os
from celery import Celery
from celery.schedules import crontab
from dotenv import load_dotenv

load_dotenv()

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "main.settings")

app = Celery("main")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# timezone-safe
app.conf.enable_utc = False
app.conf.timezone = os.getenv('TZ')

app.conf.beat_schedule = {
	'daily-birthday-campaign-check': {
        'task': 'apps.tenant.senler.tasks.check_birthdays_daily',
        # Запускаем каждое утро в 09:00 (можно изменить время)
        'schedule': crontab(hour=9, minute=0),
    },

    # --- ТЗ Пункт 7, 10 и Дополнения (Пункт 2, 6): Работа с сообщениями и отзывами ---
    # Задача: sync_vk_messages_task
    # Описание: Эта задача должна регулярно "опрашивать" ВК на наличие новых сообщений,
    # чтобы работали чат-боты, ответы из админки и сбор статистики.
    'sync-vk-messages-frequently': {
        'task': 'apps.tenant.branch.tasks.sync_vk_messages_task',
        # Запускаем часто (например, каждые 2 минуты), чтобы создать эффект реального времени
        'schedule': crontab(minute='*/2'),
    },
    
    # Задача: RFM Analysis Recalculation
    'rf-daily-recalculate': {
        'task': 'apps.tenant.stats.tasks.recalculate_rf_matrix_task',
        # Запускаем ночью, например в 04:00, чтобы не нагружать базу днем
        'schedule': crontab(hour=4, minute=0),
    },
}
