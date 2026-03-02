import docx
import json
import re  # <--- Добавляем регулярки для поиска JSON
from django.conf import settings
from anthropic import Anthropic
from apps.tenant.branch.models import BranchTestimonials
from apps.shared.clients.models import KnowledgeBase
import httpx

class AIService:
    @staticmethod
    def get_classification_prompt(company):
        """Читает инструкции из DOCX файла компании"""
        try:
            kb = KnowledgeBase.objects.get(company=company)
            if not kb.testimonial_file:
                return None
            
            doc = docx.Document(kb.testimonial_file.path)
            full_text = [para.text for para in doc.paragraphs]
            return "\n".join(full_text)
        except Exception as e:
            print(f"Error reading docx: {e}")
            return None
    
    @staticmethod
    def get_marketing_prompt(company):
        """Читает инструкции из DOCX файла компании"""
        try:
            kb = KnowledgeBase.objects.get(company=company)
            if not kb.marketing_file:
                return None
            
            doc = docx.Document(kb.marketing_file.path)
            full_text = [para.text for para in doc.paragraphs]
            return "\n".join(full_text)
        except Exception as e:
            print(f"Error reading docx: {e}")
            return None

    @staticmethod
    def classify_review(testimonial: BranchTestimonials):
        """Отправляет отзыв в Claude Sonnet для анализа"""
        
        from django.db import connection
        from django_tenants.utils import get_tenant_model
        
        TenantModel = get_tenant_model()
        company = None
        
        # Try getting company from current tenant context (by schema name)
        try:
             if connection.schema_name != 'public':
                 company = TenantModel.objects.get(schema_name=connection.schema_name)
        except Exception as e:
             print(f"AI Warning: Could not resolve tenant from schema {connection.schema_name}: {e}")

        # Fallback (e.g. if testing manually without context or if connection.schema_name is public)
        if not company and testimonial.client:
            company = testimonial.client.branch.company
        
        if not company:
            print(f"AI Warning: No company found for review {testimonial.id}")
            return

        instructions = AIService.get_classification_prompt(company)
        if not instructions:
            print(f"AI Warning: No instructions found for company {company.name}")
            return

        PROXY_URL = "http://212.192.220.63:8888"
        client = Anthropic(api_key=settings.ANTHROPIC_API_KEY, http_client=httpx.Client(proxy=PROXY_URL))
        
        user_message = f"Текст отзыва: {testimonial.review}\nОценка: {testimonial.rating}"

        # Улучшаем промпт, требуя только JSON
        system_prompt = (
            f"Ты классификатор отзывов. Твоя задача определить тональность.\n"
            f"Инструкции:\n{instructions}\n\n"
            f"ВАЖНО: Верни ТОЛЬКО чистый JSON без markdown блоков и лишнего текста.\n"
            f"Формат: {{'sentiment': 'POSITIVE'|'NEGATIVE'|'NEUTRAL'|'SPAM'|'PARTIALLY_NEGATIVE', 'reason': '...'}}"
        )

        try:
            # Убедитесь, что имя модели правильное. Обычно это "claude-3-5-sonnet-20240620"
            response = client.messages.create(
                model="claude-sonnet-4-5", 
                max_tokens=300,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}]
            )
            
            content_text = response.content[0].text
            print(f"DEBUG AI RAW RESPONSE: {content_text!r}") # Видим, что ответила сеть

            # --- БЛОК БЕЗОПАСНОГО ПАРСИНГА ---
            # 1. Пытаемся найти JSON объект через регулярку (от первой { до последней })
            json_match = re.search(r'\{.*\}', content_text, re.DOTALL)
            
            if json_match:
                json_str = json_match.group(0)
                try:
                    result = json.loads(json_str)
                except json.JSONDecodeError:
                     # Если регулярка захватила что-то кривое, пробуем почистить стандартные ошибки
                    print("AI Error: Regex found content but JSON failed, trying dirty-json fix...")
                    return
            else:
                print("AI Error: No JSON object found in response")
                return
            # ---------------------------------
            
            testimonial.sentiment = result.get('sentiment', 'NEUTRAL')
            testimonial.ai_comment = result.get('reason', '')
            testimonial.save()
            print(f"Success! Review classified as {testimonial.sentiment}")
            
            # --- Отправка ссылок на карты для позитивных отзывов ---
            if testimonial.sentiment == 'POSITIVE' and testimonial.client:
                AIService._send_map_links(testimonial)
            
        except Exception as e:
            print(f"AI Critical Error: {e}")

    @staticmethod
    def generate_reply(company, review_text, review_rating, draft_text=""):
        """Генерирует ответ на отзыв с учетом Tone of Voice"""
        instructions = AIService.get_classification_prompt(company) or "Будь вежлив и профессионален."

        PROXY_URL = "http://212.192.220.63:8888"
        client = Anthropic(api_key=settings.ANTHROPIC_API_KEY, http_client=httpx.Client(proxy=PROXY_URL))
        
        system_prompt = (
            f"Ты профессиональный менеджер ресторана. Твоя задача - написать ответ на отзыв гостя.\n"
            f"TONE OF VOICE / ИНСТРУКЦИИ:\n{instructions}\n\n"
            f"Проанализируй отзыв и напиши идеальный ответ. Если есть черновик ответа, улучши его, сохраняя смысл.\n"
            f"Ответ должен быть готовым к отправке (без кавычек и вступительных слов 'Вот ответ...')."
        )
        
        user_message = (
            f"ОТЗЫВ:\nТекст: {review_text}\nОценка: {review_rating}\n\n"
            f"ЧЕРНОВИК ОТВЕТА (может быть пустым): {draft_text}"
        )

        try:
            response = client.messages.create(
                model="claude-sonnet-4-5", 
                max_tokens=500,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}]
            )
            return response.content[0].text
        except Exception as e:
            print(f"AI Generation Error: {e}")
            return "Ошибка генерации ответа. Пожалуйста, попробуйте позже."

    @staticmethod
    def generate_mailing_text(company, topic, tone="Профессиональный"):
        """
        Генерирует текст для рассылки на основе темы и тональности.
        """
        instructions = AIService.get_marketing_prompt(company) or "Будь вежлив и профессионален."
        PROXY_URL = "http://212.192.220.63:8888"
        client = Anthropic(api_key=settings.ANTHROPIC_API_KEY, http_client=httpx.Client(proxy=PROXY_URL))
        
        system_prompt = (
             "Ты профессиональный SMM-маркетолог. Твоя задача - написать эффективный текст рассылки для ВКонтакте.\n"
             f"Правила:\n{instructions}\n"
             "1. Текст должен быть вовлекающим, кратким и полезным.\n"
             "2. Используй смайлики (emoji) умеренно.\n"
             "3. Разбивай текст на абзацы для легкости чтения.\n"
             f"4. Тональность: {tone}\n"
             "5. Без вступительных слов типа 'Вот вариант текста:'. Только готовый текст."
        )

        user_message = f"Тема рассылки: {topic}"

        try:
            response = client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=600,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}]
            )
            return response.content[0].text
        except Exception as e:
            print(f"AI Mailing Generation Error: {e}")
            return f"Ошибка генерации: {str(e)}"

    @staticmethod
    def _send_map_links(testimonial: BranchTestimonials):
        """
        Отправляет ссылки на карты (Яндекс, 2GIS) через VK после позитивной классификации отзыва.
        """
        try:
            from apps.tenant.branch.models import BranchConfig
            from apps.tenant.senler.services import VKService
            
            client_branch = testimonial.client
            if not client_branch or not client_branch.branch:
                return
            
            try:
                config = BranchConfig.objects.get(branch=client_branch.branch)
            except BranchConfig.DoesNotExist:
                print(f"No BranchConfig for branch {client_branch.branch.id}")
                return
            
            # Собираем ссылки
            links = []
            if config.yandex_map:
                links.append(f"🗺 Yandex Карты: {config.yandex_map}")
            if config.gis_map:
                links.append(f"📍 2GIS: {config.gis_map}")
            
            if not links:
                return
            
            # Формируем сообщение
            message = (
                "Спасибо за ваш отзыв! ✨\n\n"
                "Мы будем очень признательны, если вы оставите отзыв на картах — это очень помогает нам становиться лучше! \n\n"
                + "\n".join(links)
            )
            
            vk_service = VKService()
            if vk_service.is_configured:
                vk_service.send_message(client_branch, message)
                print(f"Map links sent to client {client_branch.id} after positive review")
                
        except Exception as e:
            print(f"Error sending map links: {e}")