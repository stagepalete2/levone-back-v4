from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib.admin.views.decorators import staff_member_required
from django.db import connection
from django_tenants.utils import get_tenant_model
import json

from apps.tenant.branch.ai import AIService

@staff_member_required
@require_POST
def generate_review_reply(request):
    try:
        data = json.loads(request.body)
        review_text = data.get('review_text', '')
        review_rating = data.get('review_rating', 5)
        draft_text = data.get('draft_text', '')

        print(review_text, review_rating)
        
        # Get Company from current tenant context
        TenantModel = get_tenant_model()
        company = None
        if connection.schema_name != 'public':
             company = TenantModel.objects.get(schema_name=connection.schema_name)
        
        if not company:
            return JsonResponse({'error': 'Company context not found'}, status=400)
            
        generated_reply = AIService.generate_reply(company, review_text, review_rating, draft_text)
        
        return JsonResponse({'reply': generated_reply})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@staff_member_required
@require_POST
def generate_mailing_content(request):
    try:
        data = json.loads(request.body)
        topic = data.get('topic', '')
        
        TenantModel = get_tenant_model()
        company = None
        if connection.schema_name != 'public':
             company = TenantModel.objects.get(schema_name=connection.schema_name)
        
        if not company:
             return JsonResponse({'error': 'Company context not found'}, status=400)
             
        text = AIService.generate_mailing_text(company, topic)
        return JsonResponse({'text': text})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
