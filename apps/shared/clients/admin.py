from django.contrib import admin

from apps.shared.config.sites import public_admin

from apps.shared.clients.models import Company, CompanyConfig, Domain, KnowledgeBase

public_admin.register(Company)
public_admin.register(Domain)
public_admin.register(CompanyConfig)
public_admin.register(KnowledgeBase)