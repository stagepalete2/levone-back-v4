"""
Диагностический скрипт для проверки статистики.
Запуск: python manage.py shell < debug_stats.py

Период: СЕГОДНЯ
Филиалы: ВСЕ (без фильтра по branch)
Тенант: levone (schema_name='levone')

Для каждой метрики:
  1) Выполняет тот же запрос, что и dashboard (core.py → get_dashboard_stats)
  2) Выполняет тот же запрос, что и detail view (views.py → StatisticsDetailView)
  3) Сравнивает количество и выводит расхождения
  4) Печатает все записи с полями
"""

import django, json
from datetime import timedelta
from django.utils.timezone import now
from django.db.models import Count, F, Q, Min, Max, Sum
from django.db.models.functions import TruncDate, Coalesce
from django.db import connection

# ═══════════════════════════════════════════════════════════════════════
# Переключаемся на schema тенанта levone
# ═══════════════════════════════════════════════════════════════════════
from apps.shared.clients.models import Company

tenant = Company.objects.get(schema_name='levone')
connection.set_tenant(tenant)
print(f"\n  Подключено к тенанту: {tenant.name} (schema={tenant.schema_name})")

# ── Модели (импорт ПОСЛЕ set_tenant) ──
from apps.tenant.branch.models import Branch, ClientBranch, ClientBranchVisit, CoinTransaction, BranchTestimonials
from apps.tenant.game.models import ClientAttempt
from apps.tenant.inventory.models import SuperPrize
from apps.tenant.senler.models import MessageLog
from apps.tenant.quest.models import QuestSubmit

# ═══════════════════════════════════════════════════════════════════════
# Период: СЕГОДНЯ
# ═══════════════════════════════════════════════════════════════════════
date_to = now()
date_from = date_to.replace(hour=0, minute=0, second=0, microsecond=0)
branch_id = None  # все точки

print("=" * 100)
print(f"  ДИАГНОСТИКА СТАТИСТИКИ — тенант: {tenant.name} (schema={tenant.schema_name})")
print(f"  Период: {date_from.strftime('%Y-%m-%d %H:%M:%S')} — {date_to.strftime('%Y-%m-%d %H:%M:%S')}")
print(f"  Филиалы: ВСЕ")
print("=" * 100)

# Список всех филиалов
branches = Branch.objects.all().order_by('name')
print(f"\n  Доступные филиалы ({branches.count()}):")
for b in branches:
    print(f"    ID={b.id}  {b.name}")

# ── Базовые queryset-ы (как в dashboard и detail) ──
# Dashboard base: без реферальных
base_qs = ClientBranch.objects.filter(invited_by__isnull=True)
# Dashboard period
period_qs = base_qs.filter(created_at__gte=date_from, created_at__lte=date_to)
# All (включая реферальных) - для метрики referral
all_qs = ClientBranch.objects.all()
all_period_qs = all_qs.filter(created_at__gte=date_from, created_at__lte=date_to)

# Detail base (идентичен dashboard base)
detail_qs = ClientBranch.objects.filter(invited_by__isnull=True)
detail_period_qs = detail_qs.filter(created_at__gte=date_from, created_at__lte=date_to)


def print_separator(title):
    print("\n" + "─" * 100)
    print(f"  {title}")
    print("─" * 100)


def print_client_branch(cb, prefix="    "):
    """Печатает все поля ClientBranch."""
    client = cb.client if cb.client_id else None
    vk_id = client.vk_user_id if client else "N/A"
    name = client.full_name if client else "N/A"
    print(
        f"{prefix}CB.id={cb.id} | VK={vk_id} | {name} | "
        f"branch={cb.branch_id}({cb.branch.name if cb.branch else '?'}) | "
        f"created={cb.created_at.strftime('%Y-%m-%d %H:%M') if cb.created_at else '?'} | "
        f"invited_by={'Client#' + str(cb.invited_by_id) if cb.invited_by_id else 'None'} | "
        f"story={cb.is_story_uploaded}(at={cb.story_uploaded_at}) | "
        f"community_app={cb.joined_community_via_app}(at={cb.joined_community_via_app_at}) | "
        f"mailing_app={cb.allowed_message_via_app}(at={cb.allowed_message_via_app_at}) | "
        f"is_employee={cb.is_employee}"
    )


def compare_and_print(metric_name, dashboard_count, dashboard_label,
                      detail_qs_result, detail_label, print_records=True):
    """Сравнивает dashboard count и detail queryset, выводит записи."""
    detail_list = list(detail_qs_result.select_related('client', 'branch'))
    detail_count = len(detail_list)

    match_icon = "✅" if dashboard_count == detail_count else "❌ РАСХОЖДЕНИЕ"

    print(f"\n  {match_icon}")
    print(f"  Dashboard ({dashboard_label}): {dashboard_count}")
    print(f"  Detail    ({detail_label}):    {detail_count}")

    if print_records and detail_list:
        print(f"\n  Записи из Detail View ({detail_count}):")
        for cb in detail_list:
            print_client_branch(cb)
    elif not detail_list:
        print("  (нет записей)")

    return dashboard_count, detail_count


# ═══════════════════════════════════════════════════════════════════════
# 1. 📱 Отсканировали QR-код за период (qr_scans)
# ═══════════════════════════════════════════════════════════════════════
print_separator("1. 📱 Отсканировали QR-код за период (qr_scans)")

# -- Dashboard: count через ClientBranchVisit --
# (в get_pos_stats → qr_scans_today)
qr_visits_filter = Q(client__invited_by__isnull=True)
qr_visits_filter &= Q(visited_at__gte=date_from)
qr_visits_filter &= Q(visited_at__lte=date_to)
dashboard_qr_count = ClientBranchVisit.objects.filter(qr_visits_filter).count()

# Покажем сами визиты
qr_visits = ClientBranchVisit.objects.filter(qr_visits_filter).select_related(
    'client__client', 'client__branch'
)
print(f"\n  Все визиты (ClientBranchVisit) за период: {qr_visits.count()}")
for v in qr_visits:
    cb = v.client
    cl = cb.client if cb.client_id else None
    print(
        f"    Visit.id={v.id} | visited_at={v.visited_at.strftime('%Y-%m-%d %H:%M')} | "
        f"CB.id={cb.id} | VK={cl.vk_user_id if cl else '?'} | {cl.full_name if cl else '?'} | "
        f"branch={cb.branch_id}({cb.branch.name})"
    )

# -- Detail View: _get_qr_scan_clients --
visit_filters = Q(client__invited_by__isnull=True)
visit_filters &= Q(visited_at__gte=date_from)
visit_filters &= Q(visited_at__lte=date_to)
scan_ids = ClientBranchVisit.objects.filter(visit_filters).values_list('client_id', flat=True)
detail_qr_qs = detail_qs.filter(id__in=scan_ids).distinct()

compare_and_print(
    "qr_scans",
    dashboard_qr_count, "ClientBranchVisit.count()",
    detail_qr_qs, "ClientBranch с визитами"
)
print("\n  ⚠️  Примечание: Dashboard считает КОЛИЧЕСТВО визитов, Detail — УНИКАЛЬНЫХ клиентов.")


# ═══════════════════════════════════════════════════════════════════════
# 2. 📬 Подписались на рассылку ЧЕРЕЗ приложение (mailing_subscribers) — ВСЁ ВРЕМЯ
# ═══════════════════════════════════════════════════════════════════════
print_separator("2. 📬 Подписались на рассылку ЧЕРЕЗ приложение — ВСЁ ВРЕМЯ (mailing_subscribers)")

# -- Dashboard --
dashboard_mailing_total = base_qs.filter(
    allowed_message_via_app=True
).values("client").distinct().count()

# -- Detail View --
detail_mailing_qs = detail_qs.filter(allowed_message_via_app=True).distinct()

compare_and_print(
    "mailing_subscribers",
    dashboard_mailing_total, "values('client').distinct().count()",
    detail_mailing_qs, "ClientBranch.filter(allowed_message_via_app=True)"
)


# ═══════════════════════════════════════════════════════════════════════
# 3. 🎁 Новые в группе и рассылке, получившие первый подарок (new_clients_received_super_prize)
# ═══════════════════════════════════════════════════════════════════════
print_separator("3. 🎁 Новые в группе и рассылке, получившие первый подарок (new_clients_received_super_prize)")

# -- Dashboard --
first_prize_dates = SuperPrize.objects.filter(
    acquired_from='GAME'
).values('client_id').annotate(
    first_prize_at=Min('created_at')
)
first_in_period = first_prize_dates.filter(
    first_prize_at__gte=date_from, first_prize_at__lte=date_to
)
_sp_ids = first_in_period.values_list('client_id', flat=True)

dashboard_super_prize = base_qs.filter(
    id__in=_sp_ids
).filter(
    Q(joined_community_via_app=True) | Q(allowed_message_via_app=True)
).distinct().count()

# -- Detail View (идентична dashboard) --
detail_super_prize_qs = detail_qs.filter(
    id__in=_sp_ids
).filter(
    Q(joined_community_via_app=True) | Q(allowed_message_via_app=True)
).distinct()

compare_and_print(
    "new_clients_received_super_prize",
    dashboard_super_prize, "base_qs.filter(id__in=sp_ids, community|mailing).distinct().count()",
    detail_super_prize_qs, "Detail _get_new_prize_clients"
)

# Дополнительно: все суперпризы GAME за период
print(f"\n  Дополнительно — все SuperPrize(GAME) за период с первым призом в этом периоде:")
for sp_row in first_in_period:
    cid = sp_row['client_id']
    fp = sp_row['first_prize_at']
    try:
        cb = ClientBranch.objects.select_related('client', 'branch').get(id=cid)
        cl = cb.client
        print(
            f"    CB.id={cid} | VK={cl.vk_user_id} | {cl.full_name} | "
            f"branch={cb.branch.name} | first_prize={fp.strftime('%Y-%m-%d %H:%M')} | "
            f"community_app={cb.joined_community_via_app} | mailing_app={cb.allowed_message_via_app}"
        )
    except ClientBranch.DoesNotExist:
        print(f"    CB.id={cid} — НЕ НАЙДЕН")


# ═══════════════════════════════════════════════════════════════════════
# 4. 🔄 Вернулись и сыграли в игру повторно (clients_returned_second_time)
# ═══════════════════════════════════════════════════════════════════════
print_separator("4. 🔄 Вернулись и сыграли в игру повторно (clients_returned_second_time)")

# -- Dashboard --
attempt_filters = {
    'created_at__gte': date_from,
    'created_at__lte': date_to,
    'client__invited_by__isnull': True,
}
dashboard_returned = ClientAttempt.objects.filter(
    **attempt_filters
).annotate(
    play_date=TruncDate('created_at')
).values("client", "play_date").distinct().values("client").annotate(
    days_cnt=Count("play_date", distinct=True)
).filter(days_cnt__gte=2).count()

# -- Detail View --
repeat_client_ids = ClientAttempt.objects.filter(
    **attempt_filters
).annotate(
    play_date=TruncDate('created_at')
).values('client', 'play_date').distinct().values('client').annotate(
    days_cnt=Count('play_date', distinct=True)
).filter(days_cnt__gte=2).values_list('client', flat=True)

detail_returned_qs = detail_qs.filter(id__in=repeat_client_ids).distinct()

compare_and_print(
    "clients_returned_second_time",
    dashboard_returned, "ClientAttempt ≥2 уникальных дней",
    detail_returned_qs, "Detail _get_returned_clients"
)

# Дополнительно: все попытки за период
all_attempts_today = ClientAttempt.objects.filter(
    created_at__gte=date_from, created_at__lte=date_to
).select_related('client__client', 'client__branch')
print(f"\n  Все ClientAttempt за период: {all_attempts_today.count()}")
for a in all_attempts_today[:50]:
    cb = a.client
    cl = cb.client if cb.client_id else None
    print(
        f"    Attempt.id={a.id} | {a.created_at.strftime('%Y-%m-%d %H:%M')} | "
        f"CB.id={cb.id} | VK={cl.vk_user_id if cl else '?'} | {cl.full_name if cl else '?'} | "
        f"branch={cb.branch.name} | invited_by={cb.invited_by_id}"
    )
if all_attempts_today.count() > 50:
    print(f"    ... и ещё {all_attempts_today.count() - 50} записей")


# ═══════════════════════════════════════════════════════════════════════
# 5. 🛒 Купили подарки за баллы (clients_bought_prizes)
# ═══════════════════════════════════════════════════════════════════════
print_separator("5. 🛒 Купили подарки за баллы (clients_bought_prizes)")

# -- Dashboard --
expense_filter = Q(transactions__type="EXPENSE")
expense_filter &= Q(transactions__created_at__gte=date_from)
expense_filter &= Q(transactions__created_at__lte=date_to)
dashboard_bought = base_qs.filter(expense_filter).values("client").distinct().count()

# -- Detail View --
tx_filters = Q(type='EXPENSE')
tx_filters &= Q(created_at__gte=date_from)
tx_filters &= Q(created_at__lte=date_to)
bought_client_ids = CoinTransaction.objects.filter(tx_filters).values_list('client_id', flat=True)
detail_bought_qs = detail_qs.filter(id__in=bought_client_ids).distinct()

compare_and_print(
    "clients_bought_prizes",
    dashboard_bought, "base_qs.filter(expense).values('client').distinct().count()",
    detail_bought_qs, "Detail _get_bought_prizes_clients"
)

# Дополнительно: все EXPENSE транзакции
expense_txs = CoinTransaction.objects.filter(
    type='EXPENSE', created_at__gte=date_from, created_at__lte=date_to
).select_related('client__client', 'client__branch')
print(f"\n  Все CoinTransaction(EXPENSE) за период: {expense_txs.count()}")
for tx in expense_txs[:30]:
    cb = tx.client
    cl = cb.client if cb.client_id else None
    print(
        f"    TX.id={tx.id} | {tx.created_at.strftime('%Y-%m-%d %H:%M')} | "
        f"amount={tx.amount} | source={tx.source} | "
        f"CB.id={cb.id} | VK={cl.vk_user_id if cl else '?'} | {cl.full_name if cl else '?'} | "
        f"branch={cb.branch.name}"
    )


# ═══════════════════════════════════════════════════════════════════════
# 6. 👥 Подписались в сообщество ВК ЧЕРЕЗ приложение ЗА ПЕРИОД (group_subscribers)
# ═══════════════════════════════════════════════════════════════════════
print_separator("6. 👥 Подписались в сообщество ВК ЧЕРЕЗ приложение ЗА ПЕРИОД (group_subscribers)")

# -- Dashboard: использует Coalesce('joined_community_via_app_at', 'created_at') --
group_sub_qs_dash = base_qs.filter(joined_community_via_app=True).annotate(
    effective_joined_at=Coalesce('joined_community_via_app_at', 'created_at')
)
group_sub_qs_dash = group_sub_qs_dash.filter(
    effective_joined_at__gte=date_from, effective_joined_at__lte=date_to
)
dashboard_group = group_sub_qs_dash.values("client").distinct().count()

# -- Detail View: использует period_qs.filter(joined_community_via_app=True) --
# period_qs фильтрует по created_at, а НЕ по effective_joined_at!
detail_group_qs = detail_period_qs.filter(joined_community_via_app=True).distinct()

compare_and_print(
    "group_subscribers",
    dashboard_group, "Coalesce(joined_at, created_at) в периоде",
    detail_group_qs, "period_qs (created_at) + joined_community_via_app"
)

# Показываем все с joined_community_via_app=True за всё время для контекста
all_community = base_qs.filter(joined_community_via_app=True).select_related('client', 'branch')
print(f"\n  ВСЕ с joined_community_via_app=True (всё время): {all_community.count()}")
for cb in all_community[:30]:
    cl = cb.client
    print(
        f"    CB.id={cb.id} | VK={cl.vk_user_id} | {cl.full_name} | "
        f"branch={cb.branch.name} | created={cb.created_at.strftime('%Y-%m-%d %H:%M')} | "
        f"joined_at={cb.joined_community_via_app_at}"
    )

print("\n  ⚠️  ВАЖНО: Dashboard фильтрует по Coalesce(joined_community_via_app_at, created_at),")
print("     а Detail View — по created_at (через period_qs). Это может давать расхождения!")


# ═══════════════════════════════════════════════════════════════════════
# 7. 📩 Подписались на рассылку ВК ЧЕРЕЗ приложение ЗА ПЕРИОД (mailing_period)
# ═══════════════════════════════════════════════════════════════════════
print_separator("7. 📩 Подписались на рассылку ВК ЧЕРЕЗ приложение ЗА ПЕРИОД (mailing_period)")

# -- Dashboard: Coalesce('allowed_message_via_app_at', 'created_at') --
mailing_sub_qs_dash = base_qs.filter(allowed_message_via_app=True).annotate(
    effective_allowed_at=Coalesce('allowed_message_via_app_at', 'created_at')
)
mailing_sub_qs_dash = mailing_sub_qs_dash.filter(
    effective_allowed_at__gte=date_from, effective_allowed_at__lte=date_to
)
dashboard_mailing_period = mailing_sub_qs_dash.values("client").distinct().count()

# -- Detail View: period_qs.filter(allowed_message_via_app=True) --
detail_mailing_period_qs = detail_period_qs.filter(allowed_message_via_app=True).distinct()

compare_and_print(
    "mailing_period",
    dashboard_mailing_period, "Coalesce(allowed_at, created_at) в периоде",
    detail_mailing_period_qs, "period_qs (created_at) + allowed_message_via_app"
)

print("\n  ⚠️  ВАЖНО: Dashboard фильтрует по Coalesce(allowed_message_via_app_at, created_at),")
print("     а Detail View — по created_at (через period_qs). Это может давать расхождения!")


# ═══════════════════════════════════════════════════════════════════════
# 8. 🎂 Отправлено поздравлений с ДР (sent_greetings)
# ═══════════════════════════════════════════════════════════════════════
print_separator("8. 🎂 Отправлено поздравлений с ДР (sent_greetings)")

# -- Dashboard --
msg_filters = Q(status='sent', client__invited_by__isnull=True)
msg_filters &= Q(sent_at__gte=date_from)
msg_filters &= Q(sent_at__lte=date_to)
dashboard_greetings = MessageLog.objects.filter(
    msg_filters, template_type='birthday_today'
).values('client').distinct().count()

# -- Detail View --
log_filters = Q(
    status='sent',
    client__invited_by__isnull=True,
    template_type='birthday_today',
)
log_filters &= Q(sent_at__gte=date_from)
log_filters &= Q(sent_at__lte=date_to)
greeting_client_ids = MessageLog.objects.filter(log_filters).values_list('client_id', flat=True)
detail_greetings_qs = detail_qs.filter(id__in=greeting_client_ids).distinct()

compare_and_print(
    "sent_greetings",
    dashboard_greetings, "MessageLog(birthday_today, sent).values('client').distinct().count()",
    detail_greetings_qs, "Detail _get_birthday_greeting_clients"
)

# Показываем сами MessageLog
birthday_logs = MessageLog.objects.filter(log_filters).select_related('client__client', 'client__branch')
print(f"\n  Все MessageLog(birthday_today, sent) за период: {birthday_logs.count()}")
for ml in birthday_logs[:30]:
    cb = ml.client
    cl = cb.client if cb.client_id else None
    print(
        f"    ML.id={ml.id} | sent_at={ml.sent_at.strftime('%Y-%m-%d %H:%M')} | "
        f"status={ml.status} | is_read={ml.is_read} | "
        f"CB.id={cb.id} | VK={cl.vk_user_id if cl else '?'} | {cl.full_name if cl else '?'} | "
        f"branch={cb.branch.name}"
    )


# ═══════════════════════════════════════════════════════════════════════
# 9. 🎉 Пришли отметить день рождения (clients_birthday_qr)
# ═══════════════════════════════════════════════════════════════════════
print_separator("9. 🎉 Пришли отметить день рождения (clients_birthday_qr)")

# -- Dashboard --
bp_filters = Q(acquired_from='BIRTHDAY', activated_at__isnull=False, client__invited_by__isnull=True)
bp_filters &= Q(activated_at__gte=date_from)
bp_filters &= Q(activated_at__lte=date_to)
dashboard_birthday = SuperPrize.objects.filter(bp_filters).values('client').distinct().count()

# -- Detail View --
bp_client_ids = SuperPrize.objects.filter(bp_filters).values_list('client_id', flat=True)
detail_birthday_qs = detail_qs.filter(id__in=bp_client_ids).distinct()

compare_and_print(
    "clients_birthday_qr",
    dashboard_birthday, "SuperPrize(BIRTHDAY, activated).values('client').distinct().count()",
    detail_birthday_qs, "Detail _get_birthday_clients"
)

# Показываем SuperPrize(BIRTHDAY)
birthday_prizes = SuperPrize.objects.filter(bp_filters).select_related('client__client', 'client__branch')
print(f"\n  Все SuperPrize(BIRTHDAY, activated) за период: {birthday_prizes.count()}")
for sp in birthday_prizes[:30]:
    cb = sp.client
    cl = cb.client if cb.client_id else None
    print(
        f"    SP.id={sp.id} | activated_at={sp.activated_at.strftime('%Y-%m-%d %H:%M') if sp.activated_at else '?'} | "
        f"CB.id={cb.id} | VK={cl.vk_user_id if cl else '?'} | {cl.full_name if cl else '?'} | "
        f"branch={cb.branch.name}"
    )


# ═══════════════════════════════════════════════════════════════════════
# 10. 📖 % открываемости сообщений в ВК (open_rate)
# ═══════════════════════════════════════════════════════════════════════
print_separator("10. 📖 % открываемости сообщений в ВК (open_rate)")

# -- Dashboard --
msg_base = Q(status='sent', client__invited_by__isnull=True)
msg_base &= Q(sent_at__gte=date_from)
msg_base &= Q(sent_at__lte=date_to)
total_sent = MessageLog.objects.filter(msg_base).count()
total_read = MessageLog.objects.filter(msg_base, is_read=True).count()
dashboard_open_rate = int((total_read / total_sent * 100)) if total_sent > 0 else 0

print(f"\n  Dashboard: отправлено={total_sent}, прочитано={total_read}, open_rate={dashboard_open_rate}%")

# -- Detail View: показывает клиентов с is_read=True --
read_log_filters = Q(status='sent', is_read=True, client__invited_by__isnull=True)
read_log_filters &= Q(sent_at__gte=date_from)
read_log_filters &= Q(sent_at__lte=date_to)
read_client_ids = MessageLog.objects.filter(read_log_filters).values_list('client_id', flat=True)
detail_read_qs = detail_qs.filter(id__in=read_client_ids).distinct()

print(f"  Detail View: клиентов прочитавших: {detail_read_qs.count()}")
for cb in detail_read_qs.select_related('client', 'branch')[:30]:
    print_client_branch(cb)

# Все sent сообщения
all_sent_logs = MessageLog.objects.filter(msg_base).select_related('client__client', 'client__branch')
print(f"\n  Все MessageLog(sent) за период: {all_sent_logs.count()}")
for ml in all_sent_logs[:30]:
    cb = ml.client
    cl = cb.client if cb.client_id else None
    print(
        f"    ML.id={ml.id} | sent_at={ml.sent_at.strftime('%Y-%m-%d %H:%M')} | "
        f"template={ml.template_type} | is_read={ml.is_read} | "
        f"read_at={ml.read_at.strftime('%Y-%m-%d %H:%M') if ml.read_at else 'None'} | "
        f"CB.id={cb.id} | VK={cl.vk_user_id if cl else '?'} | {cl.full_name if cl else '?'}"
    )
if all_sent_logs.count() > 30:
    print(f"    ... и ещё {all_sent_logs.count() - 30} записей")


# ═══════════════════════════════════════════════════════════════════════
# 11. 📸 Опубликовали историй в ВК (clients_posted_story)
# ═══════════════════════════════════════════════════════════════════════
print_separator("11. 📸 Опубликовали историй в ВК (clients_posted_story)")

# -- Dashboard --
story_filter = Q(is_story_uploaded=True, story_uploaded_at__isnull=False)
story_filter &= Q(story_uploaded_at__gte=date_from)
story_filter &= Q(story_uploaded_at__lte=date_to)
dashboard_story = base_qs.filter(story_filter).values("client").distinct().count()

# -- Detail View --
detail_story_qs = detail_qs.filter(story_filter).distinct()

compare_and_print(
    "clients_posted_story",
    dashboard_story, "base_qs.filter(story).values('client').distinct().count()",
    detail_story_qs, "Detail story filter"
)


# ═══════════════════════════════════════════════════════════════════════
# 12. 🔗 Перешли из историй ВК (clients_from_referral)
# ═══════════════════════════════════════════════════════════════════════
print_separator("12. 🔗 Перешли из историй ВК (clients_from_referral)")

# -- Dashboard: all_period_qs (включая реферальных), invited_by не null --
dashboard_referral = all_period_qs.filter(
    invited_by__isnull=False
).values("client").distinct().count()

# -- Detail View: all_period_qs.filter(invited_by__isnull=False) --
detail_referral_qs = all_period_qs.filter(invited_by__isnull=False).distinct()

compare_and_print(
    "clients_from_referral",
    dashboard_referral, "all_period_qs.filter(invited_by__isnull=False).values('client').distinct().count()",
    detail_referral_qs, "Detail referral filter"
)


# ═══════════════════════════════════════════════════════════════════════
# 13. ✅ Задания выполнены (quests_completed)
# ═══════════════════════════════════════════════════════════════════════
print_separator("13. ✅ Задания выполнены / не выполнены (quests)")

qs_filters = Q(created_at__gte=date_from, created_at__lte=date_to)
quest_qs = QuestSubmit.objects.filter(qs_filters)
quests_completed = quest_qs.filter(is_complete=True).values('client').distinct().count()
quests_not_completed = quest_qs.filter(is_complete=False).values('client').distinct().count()

print(f"\n  Dashboard: выполнили={quests_completed}, не выполнили={quests_not_completed}")

quest_submissions = quest_qs.select_related('client__client', 'client__branch', 'quest')
print(f"\n  Все QuestSubmit за период: {quest_submissions.count()}")
for qs_item in quest_submissions[:30]:
    cb = qs_item.client
    cl = cb.client if cb.client_id else None
    print(
        f"    QS.id={qs_item.id} | {qs_item.created_at.strftime('%Y-%m-%d %H:%M')} | "
        f"quest={qs_item.quest.id if qs_item.quest else '?'} | "
        f"is_complete={qs_item.is_complete} | "
        f"CB.id={cb.id} | VK={cl.vk_user_id if cl else '?'} | {cl.full_name if cl else '?'} | "
        f"branch={cb.branch.name}"
    )


# ═══════════════════════════════════════════════════════════════════════
# 14. 💬 Отзывы (testimonials)
# ═══════════════════════════════════════════════════════════════════════
print_separator("14. 💬 Отзывы (testimonials)")

t_filters = Q(created_at__gte=date_from, created_at__lte=date_to)
t_qs = BranchTestimonials.objects.filter(t_filters)

total_reviews = t_qs.count()
positive = t_qs.filter(sentiment='POSITIVE').count()
negative = t_qs.filter(sentiment='NEGATIVE').count()
neutral = t_qs.filter(sentiment='NEUTRAL').count()
spam = t_qs.filter(sentiment='SPAM').count()
clients_left_review = t_qs.filter(client__isnull=False).values('client').distinct().count()

print(f"\n  Dashboard: total={total_reviews}, positive={positive}, negative={negative}, "
      f"neutral={neutral}, spam={spam}, clients_left_review={clients_left_review}")

reviews = t_qs.select_related('client__client', 'client__branch')
print(f"\n  Все отзывы за период: {reviews.count()}")
for r in reviews[:30]:
    cb = r.client
    cl = cb.client if (cb and cb.client_id) else None
    print(
        f"    Review.id={r.id} | {r.created_at.strftime('%Y-%m-%d %H:%M')} | "
        f"sentiment={r.sentiment} | source={r.source} | rating={r.rating} | "
        f"is_replied={r.is_replied} | "
        f"CB={'id=' + str(cb.id) if cb else 'None'} | "
        f"VK={cl.vk_user_id if cl else r.vk_sender_id or '?'} | "
        f"{cl.full_name if cl else '?'} | "
        f"branch={cb.branch.name if cb and cb.branch else '?'}"
    )


# ═══════════════════════════════════════════════════════════════════════
# 15. 👷 Индекс вовлечённости персонала (staff_engagement_index)
# ═══════════════════════════════════════════════════════════════════════
print_separator("15. 👷 Индекс вовлечённости персонала (staff_engagement_index)")

total_attempts_staff = ClientAttempt.objects.filter(
    created_at__gte=date_from, created_at__lte=date_to
).count()
staff_attempts = ClientAttempt.objects.filter(
    served_by__isnull=False,
    created_at__gte=date_from, created_at__lte=date_to
).count()
staff_index = int((staff_attempts / total_attempts_staff) * 100) if total_attempts_staff > 0 else 0

print(f"\n  Всего попыток: {total_attempts_staff}")
print(f"  С сотрудником (served_by): {staff_attempts}")
print(f"  Индекс: {staff_index}%")


# ═══════════════════════════════════════════════════════════════════════
# 16. 📊 Общие итоги
# ═══════════════════════════════════════════════════════════════════════
print_separator("16. 📊 ОБЩИЕ ЧИСЛА (как на Dashboard)")

total_clients_all_time = base_qs.values("client").distinct().count()
total_clients_period = period_qs.values("client").distinct().count()

print(f"""
  Клиенты (всё время, unique Client):       {total_clients_all_time}
  Клиенты за период (unique Client):          {total_clients_period}
  ClientBranch записей (без реферальных):     {base_qs.count()}
  ClientBranch за период (без реферальных):   {period_qs.count()}
  ClientBranch ВСЕ (с реферальными):          {all_qs.count()}
  ClientBranch ВСЕ за период:                 {all_period_qs.count()}
""")

print("=" * 100)
print("  ДИАГНОСТИКА ЗАВЕРШЕНА")
print("=" * 100)
