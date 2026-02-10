from django.urls import path
from apps.tenant.branch.views import generate_review_reply, generate_mailing_content

urlpatterns = [
    path('generate-reply/', generate_review_reply, name='generate_review_reply'),
    path('generate-mailing/', generate_mailing_content, name='generate_mailing_content'),
]
