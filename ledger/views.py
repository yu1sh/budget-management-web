from datetime import date
from pathlib import Path
from urllib.parse import urlencode
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db import transaction
from django.db.models import Count, Prefetch, Q, Sum
from django.db.models.functions import Coalesce
from django.http import FileResponse, HttpResponseForbidden
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST
from .forms import (
    BankForm,
    HouseholdEntryForm,
    HouseholdBatchForm,
    HouseholdBreakdownFormSet,
    HospitalNameForm,
    JapanesePasswordChangeForm,
    MedicalBatchForm,
    MedicalHospitalVisitForm,
    MedicalEntryForm,
    PaymentLinkForm,
    PaymentSourceForm,
    PersonForm,
)
from .models import HouseholdEntry, MedicalEntry, MedicalVisit, PaymentSource, Person, resolve_settlement
from .services import (export_household_month, export_medical_all, export_medical_person,
                       credit_card_statement_entries, export_credit_card_statement,
                       household_csv_path, medical_csv_path,
                       delete_medical_visit, refresh_medical_exports, save_medical_visit)


def _month(request):
    raw = request.GET.get("month", "")
    try:
        y, m = map(int, raw.split("-")) if raw else (timezone.localdate().year, timezone.localdate().month)
        if not 2000 <= y <= 2100 or not 1 <= m <= 12:
            raise ValueError
        return y, m
    except (ValueError, TypeError):
        return timezone.localdate().year, timezone.localdate().month


def _payment_month(request):
    """Read the credit-card page's payment month while accepting old links."""
    raw = request.GET.get("payment_month") or request.GET.get("month") or ""
    try:
        y, m = map(int, raw.split("-")) if raw else (timezone.localdate().year, timezone.localdate().month)
        if not 2000 <= y <= 2100 or not 1 <= m <= 12:
            raise ValueError
        return y, m
    except (ValueError, TypeError):
        return timezone.localdate().year, timezone.localdate().month


def _year(request):
    try:
        year = int(request.GET.get("year", timezone.localdate().year))
        return year if 2000 <= year <= 2100 else timezone.localdate().year
    except ValueError:
        return timezone.localdate().year


def _previous_next(year, month):
    prev = date(year - 1, 12, 1) if month == 1 else date(year, month - 1, 1)
    nxt = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return prev, nxt


def login_view(request):
    if request.user.is_authenticated:
        return redirect("chooser")
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        key = f"login-lock:{request.META.get('REMOTE_ADDR', '')}:{username.lower()}"
        if cache.get(key) == "locked":
            messages.error(request, "ログイン試行が多すぎます。15分後にもう一度お試しください。")
        else:
            user = authenticate(request, username=username, password=request.POST.get("password", ""))
            if user:
                cache.delete(key)
                login(request, user)
                return redirect("chooser")
            failures = cache.get(key, 0) + 1
            cache.set(key, "locked" if failures >= 5 else failures, 900)
            messages.error(request, "ユーザー名またはパスワードが違います。")
    return render(request, "ledger/login.html")


@require_POST
def logout_view(request):
    logout(request)
    return redirect("login")


@login_required
def chooser(request):
    return render(request, "ledger/chooser.html")


@login_required
@require_http_methods(["GET", "POST"])
def household(request):
    year, month = _month(request)
    if request.method == "POST":
        data = request.POST.copy()
        # Preserve the old one-row POST shape for integrations while the UI uses
        # a formset. It also makes upgrading an existing installation harmless.
        if "lines-TOTAL_FORMS" not in data:
            data.update({
                "lines-TOTAL_FORMS": "1", "lines-INITIAL_FORMS": "0",
                "lines-MIN_NUM_FORMS": "0", "lines-MAX_NUM_FORMS": "50",
                "lines-0-description": data.get("description", ""),
                "lines-0-amount_yen": data.get("amount_yen", ""),
            })
        form = HouseholdBatchForm(data)
        line_formset = HouseholdBreakdownFormSet(data, prefix="lines")
        if form.is_valid() and line_formset.is_valid():
            source = form.cleaned_data["payment_source"]
            linked_source, settlement_source, settlement_path = resolve_settlement(source)
            with transaction.atomic():
                for line in line_formset.active_rows:
                    HouseholdEntry.objects.create(
                        spent_on=form.cleaned_data["spent_on"],
                        shop_name=form.cleaned_data["shop_name"],
                        description=line["description"],
                        amount_yen=line["amount_yen"],
                        payment_source=source,
                        payment_source_name_snapshot=source.name,
                        payment_source_kind_snapshot=source.kind,
                        linked_source=linked_source,
                        linked_source_name_snapshot=linked_source.name if linked_source else "",
                        settlement_source=settlement_source,
                        settlement_source_name_snapshot=settlement_source.name if settlement_source else "",
                        settlement_path_snapshot=settlement_path,
                        entry_type=form.cleaned_data["entry_type"] or HouseholdEntry.EntryType.EXPENSE,
                        note=form.cleaned_data["note"],
                    )
            export_household_month(form.cleaned_data["spent_on"].year, form.cleaned_data["spent_on"].month)
            messages.success(request, f"家計簿の明細を{len(line_formset.active_rows)}行保存しました。")
            return redirect(f"{request.path}?month={form.cleaned_data['spent_on']:%Y-%m}")
    else:
        form = HouseholdBatchForm()
        line_formset = HouseholdBreakdownFormSet(prefix="lines")
    entries = HouseholdEntry.objects.filter(spent_on__year=year, spent_on__month=month, deleted_at__isnull=True).select_related("payment_source")
    total = entries.filter(entry_type=HouseholdEntry.EntryType.EXPENSE).aggregate(total=Sum("amount_yen"))["total"] or 0
    shop_names = (
        HouseholdEntry.objects.filter(deleted_at__isnull=True)
        .order_by("shop_name")
        .values_list("shop_name", flat=True)
        .distinct()[:100]
    )
    prev, nxt = _previous_next(year, month)
    flea_source_ids = list(PaymentSource.objects.filter(
        is_active=True, deleted_at__isnull=True, kind=PaymentSource.Kind.FLEA_MARKET,
    ).values_list("id", flat=True))
    # Render the type control only when the submitted source is a flea-market
    # source. This prevents a first-paint flash before JavaScript starts.
    selected_source_id = str(form["payment_source"].value() or "")
    show_flea_entry_type = selected_source_id in {str(source_id) for source_id in flea_source_ids}
    return render(request, "ledger/household.html", {
        "form": form, "line_formset": line_formset, "entries": entries, "total": total,
        "year": year, "month": month, "prev": prev, "next": nxt, "shop_names": shop_names,
        "has_payment_sources": PaymentSource.objects.filter(is_active=True, deleted_at__isnull=True).exists(),
        "flea_source_ids": flea_source_ids,
        "show_flea_entry_type": show_flea_entry_type,
        "flea_entry_type_error": "entry_type" in form.errors,
    })


@login_required
@require_http_methods(["GET", "POST"])
def household_edit(request, pk):
    entry = get_object_or_404(HouseholdEntry, pk=pk, deleted_at__isnull=True)
    original_month = (entry.spent_on.year, entry.spent_on.month)
    if request.method == "POST":
        form = HouseholdEntryForm(request.POST, instance=entry)
        if form.is_valid():
            entry = form.save()
            export_household_month(*original_month)
            export_household_month(entry.spent_on.year, entry.spent_on.month)
            messages.success(request, "明細を更新しました。")
            return redirect(f"/household/?month={entry.spent_on:%Y-%m}")
    else:
        form = HouseholdEntryForm(instance=entry)
    return render(request, "ledger/edit.html", {"form": form, "title": "家計簿の明細を編集", "cancel": f"/household/?month={entry.spent_on:%Y-%m}"})


@login_required
@require_POST
def household_delete(request, pk):
    entry = get_object_or_404(HouseholdEntry, pk=pk, deleted_at__isnull=True)
    entry.deleted_at = timezone.now()
    entry.save(update_fields=["deleted_at"])
    export_household_month(entry.spent_on.year, entry.spent_on.month)
    messages.success(request, "明細を削除しました。")
    return redirect(f"/household/?month={entry.spent_on:%Y-%m}")


@login_required
def sources(request):
    year, month = _month(request)
    # Deleted sources are intentionally absent from new/list views.  Their
    # detail URL remains valid for historical rows and snapshots.
    sources_qs = list(PaymentSource.objects.filter(deleted_at__isnull=True))
    base = HouseholdEntry.objects.filter(spent_on__year=year, spent_on__month=month, deleted_at__isnull=True)
    for source in sources_qs:
        direct_entries = base.filter(payment_source=source)
        if source.kind == PaymentSource.Kind.FLEA_MARKET:
            profit = direct_entries.filter(entry_type=HouseholdEntry.EntryType.FLEA_PROFIT).aggregate(total=Sum("amount_yen"))["total"] or 0
            withdrawal = direct_entries.filter(entry_type=HouseholdEntry.EntryType.FLEA_WITHDRAWAL).aggregate(total=Sum("amount_yen"))["total"] or 0
            source.direct_total = profit - withdrawal
            source.flea_profit_total = profit
            source.flea_withdrawal_total = withdrawal
        else:
            source.direct_total = direct_entries.filter(entry_type=HouseholdEntry.EntryType.EXPENSE).aggregate(total=Sum("amount_yen"))["total"] or 0
        source.funded_total = base.filter(linked_source=source).exclude(payment_source=source).aggregate(total=Sum("amount_yen"))["total"] or 0
        source.month_total = source.direct_total + source.funded_total if source.kind in (PaymentSource.Kind.CREDIT, PaymentSource.Kind.BANK) else source.direct_total
    return render(request, "ledger/sources.html", {"sources": sources_qs, "year": year, "month": month})


@login_required
def source_detail(request, pk):
    source = get_object_or_404(PaymentSource, pk=pk)
    year, month = _month(request)
    base = HouseholdEntry.objects.filter(spent_on__year=year, spent_on__month=month, deleted_at__isnull=True)
    direct = base.filter(payment_source=source).select_related("payment_source", "linked_source", "settlement_source")
    if source.kind != PaymentSource.Kind.FLEA_MARKET:
        direct = direct.filter(entry_type=HouseholdEntry.EntryType.EXPENSE)
    funded = base.filter(linked_source=source).exclude(payment_source=source).select_related("payment_source", "linked_source", "settlement_source")
    direct_total = direct.aggregate(total=Sum("amount_yen"))["total"] or 0
    funded_total = funded.aggregate(total=Sum("amount_yen"))["total"] or 0
    breakdown = direct.values("description").annotate(total=Sum("amount_yen")).order_by("-total", "description")
    flea_profit_total = flea_withdrawal_total = flea_balance = 0
    if source.kind == PaymentSource.Kind.FLEA_MARKET:
        flea_profit_total = direct.filter(entry_type=HouseholdEntry.EntryType.FLEA_PROFIT).aggregate(total=Sum("amount_yen"))["total"] or 0
        flea_withdrawal_total = direct.filter(entry_type=HouseholdEntry.EntryType.FLEA_WITHDRAWAL).aggregate(total=Sum("amount_yen"))["total"] or 0
        all_flea = HouseholdEntry.objects.filter(payment_source=source, deleted_at__isnull=True)
        all_profit = all_flea.filter(entry_type=HouseholdEntry.EntryType.FLEA_PROFIT).aggregate(total=Sum("amount_yen"))["total"] or 0
        all_withdrawal = all_flea.filter(entry_type=HouseholdEntry.EntryType.FLEA_WITHDRAWAL).aggregate(total=Sum("amount_yen"))["total"] or 0
        flea_balance = all_profit - all_withdrawal
    return render(request, "ledger/source_detail.html", {
        "source": source, "year": year, "month": month, "direct": direct, "funded": funded,
        "direct_total": direct_total, "funded_total": funded_total, "breakdown": breakdown,
        "flea_profit_total": flea_profit_total, "flea_withdrawal_total": flea_withdrawal_total,
        "flea_balance": flea_balance,
    })


def _credit_card_statement(card, payment_year, payment_month):
    period = card.statement_period(payment_year, payment_month)
    entries = HouseholdEntry.objects.none()
    if period:
        period_start, period_end, payment_date = period
        entries = credit_card_statement_entries(card, period_start, period_end).order_by(
            "spent_on", "created_at", "id",
        )
    else:
        period_start = period_end = payment_date = None
    total = entries.aggregate(total=Sum("amount_yen"))["total"] or 0
    return {
        "source": card,
        "card": card,
        "period": period,
        "period_start": period_start,
        "period_end": period_end,
        "payment_date": payment_date,
        "entries": entries,
        "total": total,
        "entry_count": entries.count(),
        "configured": bool(period),
        "schedule_configured": bool(period),
    }


@login_required
def credit_card_billing(request):
    """Show each credit card's statement for the selected payment month."""
    payment_year, payment_month = _payment_month(request)
    cards = PaymentSource.objects.filter(
        kind=PaymentSource.Kind.CREDIT,
        deleted_at__isnull=True,
    ).order_by("name")
    statements = [_credit_card_statement(card, payment_year, payment_month) for card in cards]
    previous, following = _previous_next(payment_year, payment_month)
    return render(request, "ledger/credit_card_billing.html", {
        "statements": statements,
        "card_statements": statements,
        "cards": cards,
        "sources": cards,
        "periods": statements,
        "payment_year": payment_year,
        "payment_month": payment_month,
        # These aliases keep the page easy to consume alongside sources.
        "year": payment_year,
        "month": payment_month,
        "prev": previous,
        "next": following,
    })


@login_required
def credit_card_billing_detail(request, pk):
    card = get_object_or_404(PaymentSource, pk=pk, kind=PaymentSource.Kind.CREDIT)
    payment_year, payment_month = _payment_month(request)
    statement = _credit_card_statement(card, payment_year, payment_month)
    return render(request, "ledger/credit_card_billing_detail.html", {
        "source": card,
        "card": card,
        "statement": statement,
        "entries": statement["entries"],
        "total": statement["total"],
        "payment_year": payment_year,
        "payment_month": payment_month,
        "year": payment_year,
        "month": payment_month,
        "period": statement["period"],
        "period_start": statement["period_start"],
        "period_end": statement["period_end"],
        "payment_date": statement["payment_date"],
        "schedule_configured": statement["schedule_configured"],
    })


@login_required
def download_credit_card_billing_csv(request, pk):
    card = get_object_or_404(PaymentSource, pk=pk, kind=PaymentSource.Kind.CREDIT)
    payment_year, payment_month = _payment_month(request)
    period = card.statement_period(payment_year, payment_month)
    path = export_credit_card_statement(card, payment_year, payment_month, period=period)
    return FileResponse(
        open(path, "rb"), as_attachment=True,
        filename=f"credit-card-{card.id}-{payment_year}-{payment_month:02d}.csv",
    )


@login_required
def settlements(request):
    """Aggregate each ordinary expense exactly once by its final settlement source."""
    year, month = _month(request)
    base = HouseholdEntry.objects.filter(
        spent_on__year=year, spent_on__month=month, deleted_at__isnull=True,
        entry_type=HouseholdEntry.EntryType.EXPENSE,
    )
    grouped = base.filter(settlement_source__isnull=False).values("settlement_source_id").annotate(
        total=Sum("amount_yen"), entry_count=Count("id"),
    )
    totals = {row["settlement_source_id"]: row for row in grouped}
    settlement_sources = list(PaymentSource.objects.filter(pk__in=totals).order_by("kind", "name"))
    for source in settlement_sources:
        source.month_total = totals[source.id]["total"]
        source.entry_count = totals[source.id]["entry_count"]
    unset_total = base.filter(settlement_source__isnull=True).aggregate(total=Sum("amount_yen"))["total"] or 0
    unset_count = base.filter(settlement_source__isnull=True).count()
    return render(request, "ledger/settlements.html", {
        "sources": settlement_sources, "year": year, "month": month,
        "unset_total": unset_total, "unset_count": unset_count,
    })


@login_required
def settlement_detail(request, pk):
    source = get_object_or_404(PaymentSource, pk=pk)
    year, month = _month(request)
    entries = HouseholdEntry.objects.filter(
        settlement_source=source, spent_on__year=year, spent_on__month=month,
        deleted_at__isnull=True, entry_type=HouseholdEntry.EntryType.EXPENSE,
    ).select_related("payment_source", "linked_source", "settlement_source")
    total = entries.aggregate(total=Sum("amount_yen"))["total"] or 0
    return render(request, "ledger/settlement_detail.html", {
        "source": source, "year": year, "month": month, "entries": entries, "total": total,
    })


@login_required
def flea_market_edit(request, source_id, pk):
    source = get_object_or_404(PaymentSource, pk=source_id)
    return redirect(f"/sources/{source.id}/?month={_month(request)[0]}-{_month(request)[1]:02d}")


@login_required
def flea_market_delete(request, source_id, pk):
    source = get_object_or_404(PaymentSource, pk=source_id)
    return redirect(f"/sources/{source.id}/?month={_month(request)[0]}-{_month(request)[1]:02d}")


@login_required
@require_http_methods(["GET", "POST"])
def source_settings(request, pk=None):
    instance = get_object_or_404(PaymentSource, pk=pk, deleted_at__isnull=True) if pk else None
    if request.method == "POST":
        form = PaymentSourceForm(request.POST, instance=instance)
        if form.is_valid():
            form.save()
            messages.success(request, "支払い元を保存しました。")
            return redirect("source_settings")
    else:
        form = PaymentSourceForm(instance=instance)
    selected_kind = form["kind"].value() or ""
    # Include current deleted/inactive links in the JS kind map so an active
    # source whose historical setting points at one can still be edited safely.
    source_js_sources = PaymentSource.objects.all()
    return render(request, "ledger/settings_sources.html", {
        "form": form,
        "sources": PaymentSource.objects.filter(deleted_at__isnull=True),
        "source_js_sources": source_js_sources,
        "editing": instance,
        "show_linked_source": selected_kind in (PaymentSource.Kind.CODE, PaymentSource.Kind.CREDIT),
        "show_credit_schedule": selected_kind == PaymentSource.Kind.CREDIT,
        "linked_source_error": "linked_source" in form.errors,
    })


@login_required
@require_POST
def source_delete(request, pk):
    """Delete an unused source or hide it while retaining dependent history."""
    source = get_object_or_404(PaymentSource, pk=pk, deleted_at__isnull=True)
    has_history = HouseholdEntry.objects.filter(
        Q(payment_source=source) | Q(linked_source=source) | Q(settlement_source=source),
    ).exists()
    has_current_links = PaymentSource.objects.filter(linked_source=source).exists()
    if has_history or has_current_links:
        source.is_active = False
        source.deleted_at = timezone.now()
        source.save(update_fields=["is_active", "deleted_at", "updated_at"])
        messages.success(request, f"{source.name}を削除済みとして非表示にしました。過去の明細と引き落とし設定は保持されています。")
    else:
        try:
            source.delete()
            messages.success(request, f"{source.name}を削除しました。")
        except ProtectedError:
            # A dependent may have appeared between the check and DELETE.
            # Preserve it rather than leaving a broken link or losing history.
            source.is_active = False
            source.deleted_at = timezone.now()
            source.save(update_fields=["is_active", "deleted_at", "updated_at"])
            messages.success(request, f"{source.name}を削除済みとして非表示にしました。過去の明細と引き落とし設定は保持されています。")
    return redirect("source_settings")


@login_required
@require_http_methods(["GET", "POST"])
def bank_settings(request, pk=None):
    banks = PaymentSource.objects.filter(kind=PaymentSource.Kind.BANK, deleted_at__isnull=True).order_by("name")
    instance = get_object_or_404(banks, pk=pk) if pk else None
    if request.method == "POST":
        form = BankForm(request.POST, instance=instance)
        if form.is_valid():
            form.save()
            messages.success(request, "銀行を保存しました。")
            return redirect("bank_settings")
    else:
        form = BankForm(instance=instance)
    return render(request, "ledger/settings_banks.html", {"form": form, "banks": banks, "editing": instance})


@login_required
@require_http_methods(["GET", "POST"])
def payment_link_settings(request):
    if request.method == "POST":
        form = PaymentLinkForm(request.POST)
        if form.is_valid():
            payment_source = form.cleaned_data["code_payment"]
            payment_source.linked_source = form.cleaned_data["linked_source"]
            payment_source.save(update_fields=["linked_source", "updated_at"])
            messages.success(
                request,
                f"{payment_source.name}の引き落とし元を{payment_source.linked_source.name}に設定しました。",
            )
            return redirect("payment_link_settings")
    else:
        form = PaymentLinkForm()
    linkable_payments = PaymentSource.objects.filter(
        kind__in=(PaymentSource.Kind.CODE, PaymentSource.Kind.CREDIT),
        deleted_at__isnull=True,
    ).select_related("linked_source").order_by("name")
    available_sources = PaymentSource.objects.filter(
        is_active=True, deleted_at__isnull=True,
        kind__in=(PaymentSource.Kind.CREDIT, PaymentSource.Kind.BANK, PaymentSource.Kind.CASH),
    ).exists() or linkable_payments.filter(linked_source__isnull=False).exists()
    current_link_ids = list(linkable_payments.exclude(linked_source__isnull=True).values_list("linked_source_id", flat=True))
    all_sources = PaymentSource.objects.filter(
        Q(deleted_at__isnull=True) | Q(pk__in=current_link_ids),
    )
    return render(
        request,
        "ledger/settings_payment_links.html",
        {
            "form": form,
            "linkable_payments": linkable_payments,
            "all_sources": all_sources,
            "current_links": {source.id: source.linked_source_id for source in linkable_payments},
            "available_sources": available_sources,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def medical(request):
    year = _year(request)
    people = Person.objects.all()
    people = people.annotate(year_total=Sum("medical_entries__paid_amount_yen", filter=Q(medical_entries__record_year=year, medical_entries__deleted_at__isnull=True)))
    total = sum(p.year_total or 0 for p in people)
    return render(request, "ledger/medical.html", {"people": people, "year": year, "total": total})


@login_required
def medical_hospitals(request):
    """Compatibility endpoint for bookmarks from the former hospital tab."""
    return redirect(f"/medical/?year={_year(request)}")


@login_required
def medical_person_hospitals(request, person_id):
    """Compatibility endpoint; hospital selection now lives on the person page."""
    person = get_object_or_404(Person, pk=person_id)
    year = _year(request)
    return redirect(f"/medical/{person.id}/?year={year}")


def _medical_post_data(request, year):
    """Keep the previous POST contract working while requiring a visible date field."""
    data = request.POST.copy()
    if not data.get("visited_on"):
        data["visited_on"] = date(year, 1, 1).isoformat()
    return data


def _person_hospital_rollup(person, year):
    return (
        MedicalVisit.objects.filter(
            person=person, record_year=year, deleted_at__isnull=True,
            hospital_name__gt="", entries__deleted_at__isnull=True,
        )
        .values("hospital_name")
        .annotate(total=Sum("entries__paid_amount_yen"), visit_count=Count("id", distinct=True))
        .order_by("hospital_name")
    )


@login_required
@require_POST
def medical_hospital_add(request, person_id):
    person = get_object_or_404(Person, pk=person_id)
    year = _year(request)
    if not person.is_active:
        return HttpResponseForbidden("利用停止中の対象者には新しい医療費を追加できません。")
    form = HospitalNameForm(request.POST)
    if not form.is_valid():
        messages.error(request, "病院名を1〜150文字で入力してください。")
        return redirect(f"/medical/{person.id}/?year={year}")
    hospital_name = form.cleaned_data["hospital_name"]
    # New names intentionally only navigate.  A MedicalVisit is created after a
    # valid amount/detail submission on the hospital-specific page.
    return redirect(f"/medical/{person.id}/hospital/?{urlencode({'year': year, 'name': hospital_name})}")


@login_required
@require_http_methods(["GET", "POST"])
def medical_person(request, person_id):
    person = get_object_or_404(Person, pk=person_id)
    year = _year(request)
    if request.method == "POST" and not person.is_active:
        return HttpResponseForbidden("利用停止中の対象者には新しい医療費を追加できません。")
    if request.method == "POST":
        messages.error(request, "病院を選択してから受診記録を入力してください。")
        return redirect(f"{request.path}?year={year}")
    visits = (
        MedicalVisit.objects.filter(person=person, record_year=year, deleted_at__isnull=True)
        .prefetch_related(Prefetch(
            "entries",
            queryset=MedicalEntry.objects.filter(deleted_at__isnull=True).order_by("created_at", "id"),
        ))
        .annotate(visit_total=Coalesce(Sum("entries__paid_amount_yen", filter=Q(entries__deleted_at__isnull=True)), 0))
        .filter(visit_total__gt=0)
        .order_by("-visited_on", "-created_at", "-id")
    )
    total = MedicalEntry.objects.filter(person=person, record_year=year, deleted_at__isnull=True).aggregate(total=Sum("paid_amount_yen"))["total"] or 0
    hospitals = _person_hospital_rollup(person, year)
    standalone_count = MedicalVisit.objects.filter(
        person=person, record_year=year, deleted_at__isnull=True,
        hospital_name="", entries__deleted_at__isnull=True,
    ).distinct().count()
    return render(request, "ledger/medical_person.html", {
        "person": person, "year": year, "visits": visits, "total": total,
        "hospitals": hospitals, "standalone_count": standalone_count,
        "hospital_add_form": HospitalNameForm() if person.is_active else None,
    })


@login_required
@require_http_methods(["GET", "POST"])
def medical_visit_edit(request, pk):
    visit = get_object_or_404(MedicalVisit, pk=pk, deleted_at__isnull=True)
    if request.method == "POST":
        form = MedicalBatchForm(_medical_post_data(request, visit.record_year))
        if form.is_valid():
            if form.cleaned_data["visited_on"].year != visit.record_year:
                form.add_error("visited_on", f"{visit.record_year}年の日付を入力してください。")
            else:
                save_medical_visit(
                    visit.person, visit.record_year,
                    visited_on=form.cleaned_data["visited_on"],
                    hospital_name=form.cleaned_data["hospital_name"],
                    entries=form.entries, visit=visit,
                )
                messages.success(request, "受診記録を更新しました。")
                return redirect(f"/medical/{visit.person_id}/?year={visit.record_year}")
    else:
        details = {
            entry.category: entry
            for entry in visit.entries.filter(deleted_at__isnull=True).order_by("created_at", "id")
        }
        form = MedicalBatchForm(initial={
            "visited_on": visit.visited_on,
            "hospital_name": details.get(MedicalEntry.Category.HOSPITAL).provider_name if details.get(MedicalEntry.Category.HOSPITAL) else visit.hospital_name,
            "hospital_amount": details.get(MedicalEntry.Category.HOSPITAL).paid_amount_yen if details.get(MedicalEntry.Category.HOSPITAL) else None,
            "pharmacy_name": details.get(MedicalEntry.Category.PHARMACY).provider_name if details.get(MedicalEntry.Category.PHARMACY) else "",
            "pharmacy_amount": details.get(MedicalEntry.Category.PHARMACY).paid_amount_yen if details.get(MedicalEntry.Category.PHARMACY) else None,
            "transport_method": details.get(MedicalEntry.Category.TRANSPORT).provider_name if details.get(MedicalEntry.Category.TRANSPORT) else "",
            "transport_amount": details.get(MedicalEntry.Category.TRANSPORT).paid_amount_yen if details.get(MedicalEntry.Category.TRANSPORT) else None,
        })
    return render(request, "ledger/medical_visit_edit.html", {"form": form, "visit": visit})


@login_required
@require_POST
def medical_visit_delete(request, pk):
    visit = get_object_or_404(MedicalVisit, pk=pk, deleted_at__isnull=True)
    delete_medical_visit(visit)
    messages.success(request, "受診記録を削除しました。")
    return redirect(f"/medical/{visit.person_id}/?year={visit.record_year}")


@login_required
@require_http_methods(["GET", "POST"])
def medical_hospital_detail(request, person_id):
    person = get_object_or_404(Person, pk=person_id)
    year = _year(request)
    hospital_name = request.GET.get("name", "").strip()
    if not hospital_name or len(hospital_name) > 150:
        return redirect(f"/medical/{person.id}/?year={year}")
    if request.method == "POST" and not person.is_active:
        return HttpResponseForbidden("利用停止中の対象者には新しい医療費を追加できません。")
    if request.method == "POST":
        form = MedicalHospitalVisitForm(_medical_post_data(request, year), hospital_name=hospital_name)
        if form.is_valid():
            if form.cleaned_data["visited_on"].year != year:
                form.add_error("visited_on", f"{year}年のページでは{year}年の日付を入力してください。")
            else:
                save_medical_visit(
                    person, year, visited_on=form.cleaned_data["visited_on"],
                    hospital_name=hospital_name, entries=form.entries,
                )
                messages.success(request, "受診記録と付随する明細を保存しました。")
                return redirect(f"{request.path}?{urlencode({'year': year, 'name': hospital_name})}")
    else:
        form = MedicalHospitalVisitForm(hospital_name=hospital_name) if person.is_active else None
    visits = (
        MedicalVisit.objects.filter(person=person, record_year=year, hospital_name=hospital_name, deleted_at__isnull=True)
        .prefetch_related(Prefetch(
            "entries",
            queryset=MedicalEntry.objects.filter(deleted_at__isnull=True).order_by("created_at", "id"),
        ))
        .annotate(visit_total=Coalesce(Sum("entries__paid_amount_yen", filter=Q(entries__deleted_at__isnull=True)), 0))
        .filter(visit_total__gt=0)
        .order_by("-visited_on", "-created_at", "-id")
    )
    total = sum(visit.visit_total for visit in visits)
    return render(request, "ledger/medical_hospital_detail.html", {
        "person": person, "year": year, "hospital_name": hospital_name, "visits": visits, "total": total, "form": form,
    })


@login_required
@require_http_methods(["GET", "POST"])
def medical_edit(request, pk):
    entry = get_object_or_404(MedicalEntry, pk=pk, deleted_at__isnull=True)
    original_category = entry.category
    if request.method == "POST":
        form = MedicalEntryForm(request.POST, instance=entry)
        if form.is_valid():
            entry = form.save()
            if entry.visit_id and (original_category == MedicalEntry.Category.HOSPITAL or entry.category == MedicalEntry.Category.HOSPITAL):
                entry.visit.hospital_name = entry.provider_name if entry.category == MedicalEntry.Category.HOSPITAL else ""
                entry.visit.save(update_fields=["hospital_name", "updated_at"])
            refresh_medical_exports(entry.person_id, entry.record_year)
            messages.success(request, "医療費の明細を更新しました。")
            return redirect(f"/medical/{entry.person_id}/?year={entry.record_year}")
    else:
        form = MedicalEntryForm(instance=entry)
    return render(request, "ledger/edit.html", {"form": form, "title": "医療費の明細を編集", "cancel": f"/medical/{entry.person_id}/?year={entry.record_year}"})


@login_required
@require_POST
def medical_delete(request, pk):
    entry = get_object_or_404(MedicalEntry, pk=pk, deleted_at__isnull=True)
    entry.deleted_at = timezone.now()
    entry.save(update_fields=["deleted_at"])
    if entry.visit_id:
        if entry.category == MedicalEntry.Category.HOSPITAL:
            entry.visit.hospital_name = ""
            entry.visit.save(update_fields=["hospital_name", "updated_at"])
        if not entry.visit.entries.filter(deleted_at__isnull=True).exclude(pk=entry.pk).exists():
            entry.visit.deleted_at = entry.deleted_at
            entry.visit.save(update_fields=["deleted_at"])
    refresh_medical_exports(entry.person_id, entry.record_year)
    messages.success(request, "医療費の明細を削除しました。")
    return redirect(f"/medical/{entry.person_id}/?year={entry.record_year}")


@login_required
@require_http_methods(["GET", "POST"])
def people_settings(request, pk=None):
    instance = get_object_or_404(Person, pk=pk) if pk else None
    if request.method == "POST":
        form = PersonForm(request.POST, instance=instance)
        if form.is_valid():
            form.save()
            messages.success(request, "対象者を保存しました。")
            return redirect("people_settings")
    else:
        form = PersonForm(instance=instance)
    return render(request, "ledger/settings_people.html", {"form": form, "people": Person.objects.all(), "editing": instance})


@login_required
def download_household_csv(request):
    year, month = _month(request)
    export_household_month(year, month)
    return FileResponse(open(household_csv_path(year, month), "rb"), as_attachment=True, filename=f"household-{year}-{month:02d}.csv")


@login_required
def download_flea_market_csv(request, source_id):
    source = get_object_or_404(PaymentSource, pk=source_id)
    year, month = _month(request)
    return redirect(f"/sources/{source.id}/?month={year}-{month:02d}")


@login_required
def download_medical_csv(request, person_id=None):
    year = _year(request)
    if person_id:
        get_object_or_404(Person, pk=person_id)
        export_medical_person(year, person_id)
        path = medical_csv_path(year, person_id)
        name = f"medical-{year}-person-{person_id}.csv"
    else:
        export_medical_all(year)
        path = Path(settings.RUNTIME_DIR) / "csv" / "medical" / str(year) / "all.csv"
        name = f"medical-{year}-all.csv"
    return FileResponse(open(path, "rb"), as_attachment=True, filename=name)


@login_required
@require_http_methods(["GET", "POST"])
def password_change(request):
    if request.method == "POST":
        form = JapanesePasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            messages.success(request, "パスワードを変更しました。")
            return redirect("chooser")
    else:
        form = JapanesePasswordChangeForm(request.user)
    return render(request, "ledger/edit.html", {"form": form, "title": "パスワード変更", "cancel": "/"})
