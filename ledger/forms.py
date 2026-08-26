from django import forms
from django.contrib.auth.forms import PasswordChangeForm
from django.db import models
from django.forms import BaseFormSet, formset_factory
from django.core.exceptions import ValidationError
from django.utils import timezone
from .models import HouseholdEntry, MedicalEntry, PaymentSource, Person


class DateInput(forms.DateInput):
    input_type = "date"


class HouseholdEntryForm(forms.ModelForm):
    class Meta:
        model = HouseholdEntry
        fields = ["spent_on", "shop_name", "description", "amount_yen", "payment_source", "entry_type", "note"]
        widgets = {
            "spent_on": DateInput(),
            "shop_name": forms.TextInput(attrs={"list": "shop-name-suggestions"}),
            "note": forms.Textarea(attrs={"rows": 2}),
        }
        labels = {"spent_on": "日付", "shop_name": "店名", "description": "内訳", "amount_yen": "金額（円）", "payment_source": "支払い元", "entry_type": "種別", "note": "備考"}
        help_texts = {
            "shop_name": "同じ店名を、異なる内訳で複数行登録できます。",
            "description": "同じ店で複数の用途がある場合は、内訳ごとに1行ずつ登録してください。",
        }

    def __init__(self, *args, **kwargs):
        self._original_payment_source_id = kwargs.get("instance").payment_source_id if kwargs.get("instance") else None
        super().__init__(*args, **kwargs)
        sources = PaymentSource.objects.filter(is_active=True)
        if self.instance.pk and self.instance.payment_source_id:
            sources = PaymentSource.objects.filter(models.Q(is_active=True) | models.Q(pk=self.instance.payment_source_id))
        self.fields["payment_source"].queryset = sources
        # The field is required only when a flea-market source is selected.
        # Keeping it optional here lets ordinary existing entries be edited
        # without submitting an irrelevant value.
        self.fields["entry_type"].required = False
        if not self.instance.pk:
            self.fields["spent_on"].initial = timezone.localdate()

    def clean(self):
        cleaned = super().clean()
        source = cleaned.get("payment_source")
        entry_type = cleaned.get("entry_type")
        if not source:
            return cleaned
        if source.kind == PaymentSource.Kind.FLEA_MARKET:
            if entry_type not in (HouseholdEntry.EntryType.FLEA_PROFIT, HouseholdEntry.EntryType.FLEA_WITHDRAWAL):
                self.add_error("entry_type", "フリマでは利益または出金を選択してください。")
        else:
            cleaned["entry_type"] = HouseholdEntry.EntryType.EXPENSE
        return cleaned

    def save(self, commit=True):
        entry = super().save(commit=False)
        if not entry.pk or entry.payment_source_id != self._original_payment_source_id:
            source = entry.payment_source
            entry.payment_source_name_snapshot = source.name
            entry.payment_source_kind_snapshot = source.kind
            entry.linked_source = source.linked_source if source.kind == PaymentSource.Kind.CODE else None
            entry.linked_source_name_snapshot = entry.linked_source.name if entry.linked_source else ""
        if commit:
            entry.save()
        return entry


class HouseholdBatchForm(forms.Form):
    """Fields shared by all breakdown rows submitted in one household action."""
    spent_on = forms.DateField(label="日付", widget=DateInput())
    shop_name = forms.CharField(
        label="店名",
        max_length=150,
        widget=forms.TextInput(attrs={"list": "shop-name-suggestions"}),
    )
    payment_source = forms.ModelChoiceField(label="支払い元", queryset=PaymentSource.objects.none())
    note = forms.CharField(label="備考", required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["payment_source"].queryset = PaymentSource.objects.filter(is_active=True).order_by("kind", "name")
        self.fields["entry_type"] = forms.ChoiceField(
            label="フリマ種別",
            required=False,
            choices=[("", "選択してください"), (HouseholdEntry.EntryType.FLEA_PROFIT, "利益"), (HouseholdEntry.EntryType.FLEA_WITHDRAWAL, "出金")],
        )
        if not self.is_bound:
            self.fields["spent_on"].initial = timezone.localdate()

    def clean(self):
        cleaned = super().clean()
        source = cleaned.get("payment_source")
        entry_type = cleaned.get("entry_type")
        if not source:
            return cleaned
        if source.kind == PaymentSource.Kind.FLEA_MARKET:
            if entry_type not in (HouseholdEntry.EntryType.FLEA_PROFIT, HouseholdEntry.EntryType.FLEA_WITHDRAWAL):
                self.add_error("entry_type", "フリマでは利益または出金を選択してください。")
        elif entry_type:
            self.add_error("entry_type", "フリマ以外の支払い元に利益・出金は指定できません。")
        else:
            cleaned["entry_type"] = HouseholdEntry.EntryType.EXPENSE
        return cleaned


class HouseholdBreakdownForm(forms.Form):
    description = forms.CharField(label="内訳", max_length=200, required=False)
    amount_yen = forms.IntegerField(label="金額（円）", min_value=1, required=False)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("DELETE"):
            return cleaned
        description = (cleaned.get("description") or "").strip()
        amount = cleaned.get("amount_yen")
        if not description and amount is None:
            return cleaned
        if not description:
            self.add_error("description", "内訳を入力してください。")
        if amount is None:
            self.add_error("amount_yen", "金額を入力してください。")
        cleaned["description"] = description
        return cleaned


class BaseHouseholdBreakdownFormSet(BaseFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        active_rows = [
            form.cleaned_data
            for form in self.forms
            if form.cleaned_data and not form.cleaned_data.get("DELETE")
            and form.cleaned_data.get("description") and form.cleaned_data.get("amount_yen") is not None
        ]
        if not active_rows:
            raise ValidationError("内訳を1行以上入力してください。")

    @property
    def active_rows(self):
        return [
            form.cleaned_data
            for form in self.forms
            if form.cleaned_data and not form.cleaned_data.get("DELETE")
            and form.cleaned_data.get("description") and form.cleaned_data.get("amount_yen") is not None
        ]


HouseholdBreakdownFormSet = formset_factory(
    HouseholdBreakdownForm,
    formset=BaseHouseholdBreakdownFormSet,
    extra=1,
    can_delete=True,
    max_num=50,
    validate_max=True,
)


class PaymentSourceForm(forms.ModelForm):
    class Meta:
        model = PaymentSource
        fields = ["kind", "name", "linked_source", "note", "is_active"]
        widgets = {
            "note": forms.Textarea(attrs={"rows": 2}),
            "is_active": forms.CheckboxInput(attrs={"class": "checkbox-input"}),
        }
        labels = {"kind": "種類", "name": "名称", "linked_source": "引き落とし元", "note": "メモ", "is_active": "利用中"}
        help_texts = {
            "linked_source": "コード決済の場合に、実際に引き落とされるクレジットカードまたは銀行を選択します。",
            "is_active": "オフにすると、新しい家計簿入力の選択肢から外れます。過去の明細は残ります。",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        linked_sources = PaymentSource.objects.filter(
            is_active=True,
            kind__in=(PaymentSource.Kind.CREDIT, PaymentSource.Kind.BANK),
        )
        if self.instance.pk and self.instance.linked_source_id:
            linked_sources = PaymentSource.objects.filter(
                models.Q(
                    is_active=True,
                    kind__in=(PaymentSource.Kind.CREDIT, PaymentSource.Kind.BANK),
                )
                | models.Q(pk=self.instance.linked_source_id)
            )
        self.fields["linked_source"].queryset = linked_sources.order_by("kind", "name")

    def clean(self):
        cleaned = super().clean()
        kind, linked = cleaned.get("kind"), cleaned.get("linked_source")
        if kind == PaymentSource.Kind.CODE:
            if not linked:
                self.add_error("linked_source", "コード決済には引き落とし元のカードまたは銀行を選んでください。")
            elif linked.kind not in (PaymentSource.Kind.CREDIT, PaymentSource.Kind.BANK):
                self.add_error("linked_source", "引き落とし元にはクレジットカードまたは銀行を選んでください。")
        elif linked:
            self.add_error("linked_source", "引き落とし元はコード決済にだけ設定できます。")
        if self.instance.pk and linked and linked.pk == self.instance.pk:
            self.add_error("linked_source", "自分自身は引き落とし元にできません。")
        return cleaned


class PaymentLinkForm(forms.Form):
    code_payment = forms.ModelChoiceField(
        label="コード決済",
        queryset=PaymentSource.objects.none(),
    )
    linked_source = forms.ModelChoiceField(
        label="引き落とし元",
        queryset=PaymentSource.objects.none(),
        help_text="クレジットカードまたは銀行を選択してください。",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["code_payment"].queryset = PaymentSource.objects.filter(
            kind=PaymentSource.Kind.CODE
        ).order_by("name")
        self.fields["linked_source"].queryset = PaymentSource.objects.filter(
            is_active=True,
            kind__in=(PaymentSource.Kind.CREDIT, PaymentSource.Kind.BANK),
        ).order_by("kind", "name")


class PersonForm(forms.ModelForm):
    class Meta:
        model = Person
        fields = ["name", "is_active"]
        widgets = {"is_active": forms.CheckboxInput(attrs={"class": "checkbox-input"})}
        labels = {"name": "対象者名", "is_active": "利用中"}


class MedicalEntryForm(forms.ModelForm):
    class Meta:
        model = MedicalEntry
        fields = ["category", "provider_name", "paid_amount_yen"]
        labels = {
            "category": "区分",
            "provider_name": "病院名・薬局名・交通手段",
            "paid_amount_yen": "金額（円）",
        }


class MedicalBatchForm(forms.Form):
    visited_on = forms.DateField(label="日付", widget=DateInput())
    hospital_name = forms.CharField(label="病院名", max_length=150, required=False)
    hospital_amount = forms.IntegerField(label="病院の金額（円）", min_value=1, required=False)
    pharmacy_name = forms.CharField(label="薬局名", max_length=150, required=False)
    pharmacy_amount = forms.IntegerField(label="薬局の金額（円）", min_value=1, required=False)
    transport_method = forms.CharField(label="交通手段", max_length=150, required=False)
    transport_amount = forms.IntegerField(label="交通費（円）", min_value=1, required=False)

    pairs = (
        ("hospital_name", "hospital_amount", MedicalEntry.Category.HOSPITAL),
        ("pharmacy_name", "pharmacy_amount", MedicalEntry.Category.PHARMACY),
        ("transport_method", "transport_amount", MedicalEntry.Category.TRANSPORT),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.fields["visited_on"].initial = timezone.localdate()

    def clean(self):
        cleaned = super().clean()
        complete_count = 0
        for name_field, amount_field, _category in self.pairs:
            name = (cleaned.get(name_field) or "").strip()
            amount = cleaned.get(amount_field)
            cleaned[name_field] = name
            if name and amount is not None:
                complete_count += 1
            elif name and amount is None and amount_field not in self.errors:
                self.add_error(amount_field, "金額を入力してください。")
            elif amount is not None and not name:
                self.add_error(name_field, "名称または交通手段を入力してください。")
        if complete_count == 0 and not self.errors:
            raise ValidationError("病院、薬局、交通費のいずれか1項目以上を入力してください。")
        return cleaned

    @property
    def entries(self):
        return [
            (category, self.cleaned_data[name_field], self.cleaned_data[amount_field])
            for name_field, amount_field, category in self.pairs
            if self.cleaned_data.get(name_field) and self.cleaned_data.get(amount_field) is not None
        ]


class HospitalNameForm(forms.Form):
    hospital_name = forms.CharField(label="病院名", max_length=150)

    def clean_hospital_name(self):
        return self.cleaned_data["hospital_name"].strip()


class MedicalHospitalVisitForm(forms.Form):
    """A visit form whose hospital is selected by the URL, not user input."""

    visited_on = forms.DateField(label="日付", widget=DateInput())
    hospital_amount = forms.IntegerField(label="病院の金額（円）", min_value=1, required=False)
    pharmacy_name = forms.CharField(label="薬局名", max_length=150, required=False)
    pharmacy_amount = forms.IntegerField(label="薬局の金額（円）", min_value=1, required=False)
    transport_method = forms.CharField(label="交通手段", max_length=150, required=False)
    transport_amount = forms.IntegerField(label="交通費（円）", min_value=1, required=False)

    pairs = (
        ("pharmacy_name", "pharmacy_amount", MedicalEntry.Category.PHARMACY),
        ("transport_method", "transport_amount", MedicalEntry.Category.TRANSPORT),
    )

    def __init__(self, *args, hospital_name, **kwargs):
        self.hospital_name = hospital_name
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.fields["visited_on"].initial = timezone.localdate()

    def clean(self):
        cleaned = super().clean()
        complete_count = 1 if cleaned.get("hospital_amount") is not None else 0
        for name_field, amount_field, _category in self.pairs:
            name = (cleaned.get(name_field) or "").strip()
            amount = cleaned.get(amount_field)
            cleaned[name_field] = name
            if name and amount is not None:
                complete_count += 1
            elif name and amount is None and amount_field not in self.errors:
                self.add_error(amount_field, "金額を入力してください。")
            elif amount is not None and not name:
                self.add_error(name_field, "名称または交通手段を入力してください。")
        if complete_count == 0 and not self.errors:
            raise ValidationError("病院の金額、薬局、交通費のいずれか1項目以上を入力してください。")
        return cleaned

    @property
    def entries(self):
        entries = []
        if self.cleaned_data.get("hospital_amount") is not None:
            entries.append((MedicalEntry.Category.HOSPITAL, self.hospital_name, self.cleaned_data["hospital_amount"]))
        entries.extend(
            (category, self.cleaned_data[name_field], self.cleaned_data[amount_field])
            for name_field, amount_field, category in self.pairs
            if self.cleaned_data.get(name_field) and self.cleaned_data.get(amount_field) is not None
        )
        return entries


class JapanesePasswordChangeForm(PasswordChangeForm):
    old_password = forms.CharField(label="現在のパスワード", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "current-password", "autofocus": True}))
    new_password1 = forms.CharField(label="新しいパスワード", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    new_password2 = forms.CharField(label="新しいパスワード（確認）", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
