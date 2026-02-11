from django.apps import AppConfig


class GuestConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.shared.guest'
    verbose_name = 'Гости'