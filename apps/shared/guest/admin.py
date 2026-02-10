from django.contrib import admin

from apps.shared.config.sites import public_admin

from apps.shared.guest.models import Client

public_admin.register(Client)