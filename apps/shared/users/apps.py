from django.apps import AppConfig


class UsersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.shared.users'
    verbose_name = 'Пользователи'

    def ready(self):
        import apps.shared.users.signals