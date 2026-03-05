"""
Скрипт для немедленной отправки post_game сообщения (без задержки в 3 часа).
Использование: python test_post_game_message.py <client_branch_id> <schema_name>
"""
import sys
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from apps.tenant.senler.tasks import send_single_message


def main():
    if len(sys.argv) != 3:
        print("Использование: python test_post_game_message.py <client_branch_id> <schema_name>")
        sys.exit(1)

    client_branch_id = int(sys.argv[1])
    schema_name = sys.argv[2]

    print(f"Отправляю post_game сообщение для client_branch_id={client_branch_id}, schema={schema_name}...")
    send_single_message(client_branch_id, None, schema_name=schema_name, template_type='post_game')
    print("Готово.")


if __name__ == '__main__':
    main()
