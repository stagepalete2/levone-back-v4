from django.contrib import admin
from django.shortcuts import redirect, render
from django.contrib import messages
from django.urls import path
from django.core.files.base import ContentFile

from apps.shared.config.sites import tenant_admin
from apps.shared.config.mixins import BranchRestrictedAdminMixin
from apps.tenant.catalog.models import Product, Cooldown


def _copy_product_to_branch(original, branch):
    """Копирует продукт в указанный Branch. Возвращает 'created' или 'skipped'."""
    if Product.objects.filter(name=original.name, branch=branch).exists():
        return 'skipped'

    new_product = Product(
        name=original.name,
        description=original.description,
        price=original.price,
        is_active=original.is_active,
        is_super_prize=original.is_super_prize,
        is_birthday_prize=original.is_birthday_prize,
        branch=branch,
    )

    if original.image:
        try:
            original.image.open('rb')
            image_content = ContentFile(original.image.read())
            original.image.close()
            new_product.image.save(
                original.image.name.split('/')[-1],
                image_content,
                save=False,
            )
        except Exception:
            pass

    new_product.save()
    return 'created'


class ProductAdmin(BranchRestrictedAdminMixin, admin.ModelAdmin):
    list_display = ('name', 'branch', 'price', 'is_active', 'is_super_prize', 'is_birthday_prize', 'created_at')
    list_filter = ('branch', 'is_active', 'is_super_prize', 'is_birthday_prize')
    search_fields = ('name', 'description')
    list_editable = ('is_active', 'is_super_prize', 'is_birthday_prize', 'price')
    actions = ['action_duplicate_to_branches']

    # ── Кастомный URL для страницы выбора ресторанов ─────────────────────────

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                '<int:product_id>/duplicate-to-branches/',
                self.admin_site.admin_view(self.duplicate_select_branches_view),
                name='catalog_product_duplicate_select',
            ),
        ]
        return custom_urls + urls

    # ── Кнопка «Дублировать» на форме редактирования продукта ────────────────

    def change_view(self, request, object_id, form_url='', extra_context=None):
        extra_context = extra_context or {}
        extra_context['show_duplicate_btn'] = True
        extra_context['duplicate_url'] = 'duplicate-to-branches/'
        return super().change_view(request, object_id, form_url, extra_context=extra_context)

    # ── Страница выбора ресторанов ────────────────────────────────────────────

    def duplicate_select_branches_view(self, request, product_id):
        from apps.tenant.branch.models import Branch

        try:
            original = Product.objects.select_related('branch').get(pk=product_id)
        except Product.DoesNotExist:
            self.message_user(request, 'Продукт не найден.', level=messages.ERROR)
            return redirect('../../')

        all_other_branches = Branch.objects.exclude(pk=original.branch_id)

        # Уже существующие копии в других ресторанах
        existing_ids = set(
            Product.objects.filter(name=original.name)
            .exclude(pk=original.pk)
            .values_list('branch_id', flat=True)
        )

        # POST — выполняем дублирование
        if request.method == 'POST':
            selected_ids = request.POST.getlist('branch_ids')
            if not selected_ids:
                self.message_user(request, 'Вы не отметили ни одного ресторана.', level=messages.WARNING)
            else:
                created, skipped = 0, 0
                for branch in all_other_branches.filter(pk__in=selected_ids):
                    if _copy_product_to_branch(original, branch) == 'created':
                        created += 1
                    else:
                        skipped += 1

                msg = f'«{original.name}» скопирован в {created} ресторан(ов).'
                if skipped:
                    msg += f' Пропущено (уже есть): {skipped}.'
                lvl = messages.SUCCESS if created else messages.WARNING
                self.message_user(request, msg, level=lvl)
                return redirect('../../')

        # GET — рендерим страницу выбора
        branches_info = [
            {'branch': b, 'already_exists': b.pk in existing_ids}
            for b in all_other_branches
        ]

        context = {
            **self.admin_site.each_context(request),
            'title': f'Дублировать «{original.name}» в рестораны',
            'original': original,
            'branches_info': branches_info,
            'opts': self.model._meta,
        }
        return render(request, 'admin/catalog/product/duplicate_select.html', context)

    # ── Action из списка продуктов (тоже ведёт на страницу выбора) ───────────

    @admin.action(description='📋 Дублировать в рестораны...')
    def action_duplicate_to_branches(self, request, queryset):
        from apps.tenant.branch.models import Branch

        all_branches = Branch.objects.all()
        product_ids = list(queryset.values_list('pk', flat=True))

        # Уже существующие (name × branch)
        existing_pairs = set(
            Product.objects.filter(name__in=queryset.values('name'))
            .values_list('name', 'branch_id')
        )

        if request.method == 'POST':
            selected_ids = request.POST.getlist('branch_ids')
            if not selected_ids:
                self.message_user(request, 'Вы не отметили ни одного ресторана.', level=messages.WARNING)
            else:
                created, skipped = 0, 0
                for original in queryset:
                    for branch in Branch.objects.filter(pk__in=selected_ids).exclude(pk=original.branch_id):
                        if _copy_product_to_branch(original, branch) == 'created':
                            created += 1
                        else:
                            skipped += 1

                msg = f'Создано копий: {created}.'
                if skipped:
                    msg += f' Пропущено (уже существуют): {skipped}.'
                self.message_user(request, msg, level=messages.SUCCESS if created else messages.WARNING)
                return redirect('.')

        # GET — страница выбора
        branches_info = [
            {
                'branch': b,
                'already_exists': any((p.name, b.pk) in existing_pairs for p in queryset),
            }
            for b in all_branches
        ]

        context = {
            **self.admin_site.each_context(request),
            'title': f'Дублировать {queryset.count()} приз(а/ов) в рестораны',
            'products': queryset,
            'branches_info': branches_info,
            'action_checkbox_name': admin.helpers.ACTION_CHECKBOX_NAME,
            'product_ids': product_ids,
            'opts': self.model._meta,
            'is_bulk': True,
        }
        return render(request, 'admin/catalog/product/duplicate_select.html', context)


class CooldownAdmin(BranchRestrictedAdminMixin, admin.ModelAdmin):
    client_branch_field_name = 'client'
    branch_field_name = None

    list_display = ('client', 'last_activated_at', 'duration', 'is_active')
    search_fields = ('client__client__name', 'client__client__lastname')

    def is_active(self, obj):
        return obj.is_active
    is_active.boolean = True
    is_active.short_description = 'Активен'

    def get_queryset(self, request):
        qs = super(admin.ModelAdmin, self).get_queryset(request)
        user = request.user
        if user.is_superuser:
            return qs
        if hasattr(user, 'tenant_profile'):
            user_branches = user.tenant_profile.branches.all()
            if user_branches.exists():
                return qs.filter(client__branch__in=user_branches)
        return qs


tenant_admin.register(Product, ProductAdmin)
tenant_admin.register(Cooldown, CooldownAdmin)
