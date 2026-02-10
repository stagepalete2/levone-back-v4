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
        'schedule': crontab(hour=9, minute=0),
    },

    'sync-vk-messages-frequently': {
        'task': 'apps.tenant.branch.tasks.sync_vk_messages_task',
        'schedule': crontab(minute='*/2'),
    },
    
    'rf-daily-recalculate': {
        'task': 'apps.tenant.stats.tasks.recalculate_rf_matrix_task',
        'schedule': crontab(hour=4, minute=0),
    },
	
    "generate-daily-code": {
        "task": "apps.shared.config.tasks.generate_daily_code_for_all_tenants",
        "schedule": crontab(hour=0, minute=0),
    },
    "dayly-rfm-analysis": {
        "task": "apps.shared.config.tasks.daily_rfm_update",
        "schedule": crontab(minute=0, hour=4),
    },
}
