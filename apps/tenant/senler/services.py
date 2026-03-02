# apps/tenant/senler/services.py
import vk_api
import json
from vk_api.utils import get_random_id
from django.conf import settings
import logging
import requests  # <--- NEW IMPORT
from apps.tenant.senler.models import VKConnection, MessageLog

logger = logging.getLogger(__name__)

class VKService:
    def __init__(self):
        self.config = VKConnection.objects.first()
        self.is_configured = bool(self.config and self.config.access_token)
        
        if self.is_configured:
            self.vk_session = vk_api.VkApi(token=self.config.raw_token, api_version='5.131')
            self.vk = self.vk_session.get_api()

    def send_batch_messages(self, client_branches, text, attachment=None, campaign=None):
        """
        Автоматически выбирает стратегию отправки:
        1. Если в тексте есть {name} — использует метод execute (лимит 20).
        2. Если текста нет — использует метод user_ids (лимит 100).
        """
        if not self.is_configured or not client_branches:
            return

        valid_clients = [cb for cb in client_branches if cb.client and cb.client.vk_user_id]
        if not valid_clients:
            return

        # Проверяем, нужна ли персонализация
        need_personalization = "{name}" in text if text else False

        # ИСПРАВЛЕНИЕ:
        # Снижаем лимит execute с 25 до 20, чтобы избежать ошибки [13] Too many API calls.
        # Для обычной (standard) оставляем 100.
        chunk_size = 20 if need_personalization else 100

        # Разбиваем входящий список
        for i in range(0, len(valid_clients), chunk_size):
            chunk = valid_clients[i:i + chunk_size]
            if need_personalization:
                self._process_chunk_personalized(chunk, text, attachment, campaign)
            else:
                self._process_chunk_standard(chunk, text, attachment, campaign)

    def _process_chunk_standard(self, chunk, text, attachment, campaign):
        """Старый быстрый метод: одинаковый текст для всех (до 100 чел)"""
        user_map = {str(cb.client.vk_user_id): cb for cb in chunk}
        user_ids_str = ",".join(user_map.keys())

        try:
            results = self.vk.messages.send(
                user_ids=user_ids_str,
                message=text,
                attachment=attachment,
                random_id=get_random_id()
            )
            # Приводим ответ к списку, если VK вернул int
            if isinstance(results, int):
                results = [{'peer_id': int(uid), 'message_id': results} for uid in user_map.keys()]
            
            self._save_logs(results, user_map, campaign)

        except Exception as e:
            self._handle_global_error(chunk, campaign, e)

    def _process_chunk_personalized(self, chunk, text_template, attachment, campaign):
        """Новый метод: использует VK Script для отправки разных текстов"""
        
        # ИСПРАВЛЕНИЕ: Режем список до 20 (безопасный лимит) вместо 25
        safe_chunk = chunk[:20]
        
        user_map = {str(cb.client.vk_user_id): cb for cb in safe_chunk}
        
        requests_data = []
        for cb in safe_chunk:
            client_name = cb.client.name if cb.client.name else "Гость"
            personal_text = text_template.replace("{name}", client_name)
            
            requests_data.append({
                "peer_id": cb.client.vk_user_id,
                "message": personal_text,
                "random_id": get_random_id()
            })

        # VK Script
        code = """
        var data = Args.data;
        var attachment = Args.attachment;
        var results = [];
        var i = 0;
        
        // Цикл выполняется не более 20 раз
        while (i < data.length) {
            var item = data[i];
            var params = {
                "peer_id": item.peer_id,
                "message": item.message,
                "random_id": item.random_id
            };
            if (attachment) {
                params.attachment = attachment;
            }
            
            var res = API.messages.send(params);
            
            if (res) {
                results.push({"peer_id": item.peer_id, "message_id": res});
            } else {
                results.push({"peer_id": item.peer_id, "error": "Execute Error"});
            }
            i = i + 1;
        }
        return results;
        """

        try:
            print(requests_data)
            results = self.vk.execute(
                code=code,
                data=json.dumps(requests_data, ensure_ascii=False),
                attachment=attachment
            )
            self._save_logs(results, user_map, campaign)

        except Exception as e:
            self._handle_global_error(safe_chunk, campaign, e)

    def _save_logs(self, results, user_map, campaign):
        """Сохранение логов в БД"""
        logs_to_create = []
        
        if not isinstance(results, list):
            return

        for res in results:
            if not isinstance(res, dict):
                continue

            vk_id = str(res.get('peer_id'))
            client_obj = user_map.get(vk_id)

            if not client_obj:
                continue

            status = 'sent'
            error_msg = None

            if 'error' in res:
                error_data = res['error']
                if isinstance(error_data, dict):
                    err_code = error_data.get('error_code', error_data.get('code'))
                    error_msg = error_data.get('error_msg', error_data.get('message'))
                else:
                    err_code = 0
                    error_msg = str(error_data)

                # 900: Blacklist, 901: Not allowed, 902: Privacy
                if err_code in [900, 901, 902]:
                    status = 'blocked'
                else:
                    status = 'failed'
            
            vk_msg_id = res.get('message_id') if status == 'sent' else None
            logs_to_create.append(MessageLog(
                campaign=campaign,
                client=client_obj,
                status=status,
                error_message=error_msg,
                vk_message_id=vk_msg_id
            ))
        
        if logs_to_create:
            MessageLog.objects.bulk_create(logs_to_create)

    def _handle_global_error(self, chunk, campaign, error):
        logger.error(f"Global VK Error: {error}")
        logs = [
            MessageLog(
                campaign=campaign, 
                client=cb, 
                status='failed', 
                error_message=f"Global Exception: {str(error)}"
            )
            for cb in chunk
        ]
        MessageLog.objects.bulk_create(logs)

    def send_message(self, client_branch, text, attachment=None, campaign=None):
        self.send_batch_messages([client_branch], text, attachment, campaign)

    def upload_image_to_vk(self, file_path, peer_id=0):
        """
        Загружает изображение на сервера ВК для отправки в сообщениях.
        Возвращает строку attachment: photo{owner_id}_{id}
        """
        if not self.is_configured:
            return None

        try:
            # 1. Получаем URL для загрузки
            # Для сообщества важно передать peer_id (кому отправляем).
            # Если peer_id=0, может не работать для сообществ.
            upload_server = self.vk.photos.getMessagesUploadServer(peer_id=peer_id)
            upload_url = upload_server['upload_url']
            
            # 2. Отправляем файл
            with open(file_path, 'rb') as f:
                response = requests.post(upload_url, files={'photo': f})
            
            result = response.json()
            
            # 3. Сохраняем фото
            saved_photo = self.vk.photos.saveMessagesPhoto(
                photo=result['photo'],
                server=result['server'],
                hash=result['hash']
            )
            
            # 4. Формируем attachment string
            if saved_photo:
                photo_data = saved_photo[0]
                owner_id = photo_data['owner_id']
                media_id = photo_data['id']
                return f"photo{owner_id}_{media_id}"
                
        except Exception as e:
            logger.error(f"Error uploading image to VK: {e}")
            return None

    def get_group_members_count(self) -> int:
        """
        Получает количество подписчиков группы ВК.
        Использует метод groups.getMembers с count=0.
        """
        if not self.is_configured:
            return 0

        try:
            # group_id в VKConnection хранится без минуса
            group_id = self.config.group_id
            
            # VK API: groups.getMembers возвращает {count: N, items: [...]}
            result = self.vk.groups.getMembers(
                group_id=group_id,
                count=0  # Запрашиваем только count, без items
            )
            return result.get('count', 0)
        except Exception as e:
            logger.error(f"Error getting group members count: {e}")
            return 0

    def check_is_group_member(self, vk_user_id: int) -> bool:
        """
        Проверяет, является ли пользователь участником группы ВК.
        Возвращает True если уже подписан, False если нет.
        """
        if not self.is_configured:
            return False

        try:
            group_id = self.config.group_id
            result = self.vk.groups.isMember(
                group_id=group_id,
                user_id=vk_user_id
            )
            # VK API возвращает 1 если участник, 0 если нет
            return bool(result)
        except Exception as e:
            logger.error(f"Error checking group membership for {vk_user_id}: {e}")
            return False

    def check_is_messages_allowed(self, vk_user_id: int) -> bool:
        """
        Проверяет, разрешил ли пользователь сообщения от группы.
        Возвращает True если уже разрешил, False если нет.
        """
        if not self.is_configured:
            return False

        try:
            group_id = self.config.group_id
            result = self.vk.messages.isMessagesFromGroupAllowed(
                group_id=group_id,
                user_id=vk_user_id
            )
            return bool(result.get('is_allowed', 0))
        except Exception as e:
            logger.error(f"Error checking messages allowed for {vk_user_id}: {e}")
            return False

    def get_mailing_subscribers_count(self) -> int:
        """
        Получает количество пользователей, разрешивших рассылку.
        Использует messages.getConversations для подсчёта диалогов.
        
        Более точный метод: подсчитываем ClientBranch с валидным vk_user_id,
        у которых нет статуса 'blocked' в MessageLog.
        """
        if not self.is_configured:
            return 0

        try:
            # Подсчитываем уникальных клиентов с vk_user_id
            from apps.tenant.branch.models import ClientBranch
            
            total_with_vk = ClientBranch.objects.filter(
                client__vk_user_id__isnull=False,
                is_allowed_message=True

            ).count()
            
            return max(0, total_with_vk)
        except Exception as e:
            logger.error(f"Error getting mailing subscribers count: {e}")
            return 0

    def sync_messages_read_status(self, limit=200):
        """
        Синхронизация статуса прочтения сообщений.
        Проверяет recent-сообщения через VK API и обновляет is_read в MessageLog.
        
        Использует messages.getConversations -> conversation.out_read
        """
        if not self.is_configured:
            return 0
        
        from django.utils import timezone
        import datetime
        
        # Берём только отправленные сообщения с vk_message_id за последние 7 дней
        seven_days_ago = timezone.now() - datetime.timedelta(days=7)
        unread_logs = MessageLog.objects.filter(
            status='sent',
            vk_message_id__isnull=False,
            is_read=False,
            sent_at__gte=seven_days_ago
        ).select_related('client__client')[:limit]
        
        if not unread_logs:
            return 0
        
        updated_count = 0
        
        try:
            # Получаем все диалоги (conversations) от VK
            conversations = self.vk.messages.getConversations(
                count=200,
                filter='all',
                extended=0
            )
            
            # Создаем индекс peer_id -> out_read
            read_status_map = {}
            for item in conversations.get('items', []):
                peer_id = item['conversation']['peer']['id']
                # out_read - ID последнего прочитанного исходящего сообщения
                out_read = item['conversation'].get('out_read', 0)
                read_status_map[peer_id] = out_read
            
            # Обновляем записи
            now = timezone.now()
            for log in unread_logs:
                if not log.client or not log.client.client:
                    continue
                    
                peer_id = log.client.client.vk_user_id
                out_read = read_status_map.get(peer_id, 0)
                
                # Если vk_message_id <= out_read, значит сообщение прочитано
                if log.vk_message_id and log.vk_message_id <= out_read:
                    log.is_read = True
                    log.read_at = now
                    log.save(update_fields=['is_read', 'read_at'])
                    updated_count += 1
                    
        except Exception as e:
            logger.error(f"Error syncing message read status: {e}")
        
        return updated_count