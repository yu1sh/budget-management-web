import calendar
from datetime import date, timedelta

from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


def _tint_hex(value, white_ratio):
    """Blend a validated source color with white for safe inline styles."""
    try:
        if not isinstance(value, str) or len(value) != 7 or value[0] != "#":
            raise ValueError
        channels = [int(value[index:index + 2], 16) for index in (1, 3, 5)]
    except (TypeError, ValueError):
        channels = [20, 86, 160]
    return "#" + "".join(f"{round(channel + (255 - channel) * white_ratio):02X}" for channel in channels)


def _shift_month(year, month, delta):
    ordinal = year * 12 + (month - 1) + delta
    return ordinal // 12, ordinal % 12 + 1


def _clamped_day(year, month, day):
    return date(year, month, min(max(int(day), 1), calendar.monthrange(year, month)[1]))


class PaymentSource(models.Model):
    DEFAULT_MAIN_COLOR = "#1456A0"

    class Kind(models.TextChoices):
        CREDIT = "credit_card", "クレジットカード"
        CODE = "code_payment", "コード決済"
        POINT = "point", "ポイント"
        BANK = "bank", "銀行"
        CASH = "cash", "現金・その他"
        TRANSIT = "transit", "交通系"
        FLEA_MARKET = "flea_market", "フリマ"

    kind = models.CharField(max_length=20, choices=Kind.choices)
    name = models.CharField(max_length=100)
    linked_source = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="code_payments")
    note = models.CharField(max_length=300, blank=True)
    # A source's visual identity is deliberately kept as a validated hex
    # value instead of allowing arbitrary CSS.  This lets the templates use
    # it safely in custom properties for cards and print views.
    main_color = models.CharField(
        max_length=7,
        default=DEFAULT_MAIN_COLOR,
        validators=[RegexValidator(r"^#[0-9A-Fa-f]{6}$", "カラーは#RRGGBB形式で入力してください。")],
    )
    # Billing schedule fields apply only to credit cards.  A null triplet is
    # the explicit/legacy "未設定" state; a 31st day is also the natural
    # representation of 月末 because statement calculations clamp it to the
    # selected month's final day.
    closing_day = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(31)],
    )
    payment_day = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(31)],
    )
    PAYMENT_MONTH_OFFSET_CHOICES = (
        (0, "当月"),
        (1, "翌月"),
        (2, "翌々月"),
    )
    payment_month_offset = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        choices=PAYMENT_MONTH_OFFSET_CHOICES,
        validators=[MinValueValidator(0), MaxValueValidator(2)],
    )
    is_active = models.BooleanField(default=True)
    # Logical deletion is used whenever history or a current link depends on
    # a source.  Truly unused sources may still be physically removed by the
    # POST-only settings action.
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["kind", "name"]
        constraints = [models.UniqueConstraint(
            fields=["kind", "name"],
            condition=Q(deleted_at__isnull=True),
            name="unique_source_name_per_kind",
        )]

    def __init__(self, *args, **kwargs):
        # Accept the common shorter names when importing data or constructing
        # fixtures while keeping one canonical database column.
        for alias in ("color", "image_color"):
            if alias in kwargs and "main_color" not in kwargs:
                kwargs["main_color"] = kwargs.pop(alias)
        super().__init__(*args, **kwargs)

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        schedule = (self.closing_day, self.payment_day, self.payment_month_offset)
        if self.kind == self.Kind.CREDIT:
            if any(value is not None for value in schedule) and not all(value is not None for value in schedule):
                raise ValidationError({
                    field: "締め日・支払い日・支払い月をすべて設定してください。"
                    for field, value in zip(("closing_day", "payment_day", "payment_month_offset"), schedule)
                    if value is None
                })
        elif any(value is not None for value in schedule):
            raise ValidationError({field: "クレジットカードにのみ設定できます。" for field in (
                "closing_day", "payment_day", "payment_month_offset",
            )})

    @property
    def is_deleted(self):
        return self.deleted_at is not None

    @property
    def color(self):
        """Compatibility alias for callers that use the shorter color name."""
        return self.main_color

    @color.setter
    def color(self, value):
        self.main_color = value

    @property
    def image_color(self):
        """Japanese UI copy calls the source color its image color."""
        return self.main_color

    @property
    def safe_main_color(self):
        """Validated value for CSS; protects pages from legacy bad rows."""
        value = self.main_color
        if isinstance(value, str) and len(value) == 7 and value[0] == "#":
            try:
                int(value[1:], 16)
                return value
            except (TypeError, ValueError):
                pass
        return self.DEFAULT_MAIN_COLOR

    @property
    def pale_color(self):
        """Very pale background tint suitable for a source card."""
        return _tint_hex(self.safe_main_color, 0.92)

    @property
    def name_color(self):
        """A lighter but still legible tint used for source names."""
        return _tint_hex(self.safe_main_color, 0.32)

    @property
    def schedule_configured(self):
        return all(value is not None for value in (self.closing_day, self.payment_day, self.payment_month_offset))

    @property
    def is_schedule_configured(self):
        return self.schedule_configured

    def schedule_display(self):
        if not self.schedule_configured:
            return "未設定"
        closing = "月末" if self.closing_day == 31 else f"{self.closing_day}日"
        payment = "月末" if self.payment_day == 31 else f"{self.payment_day}日"
        offset = dict(self.PAYMENT_MONTH_OFFSET_CHOICES).get(self.payment_month_offset, "未設定")
        return f"{closing}締め・{offset}{payment}払い"

    def statement_period(self, payment_year, payment_month):
        """Return (period_start, period_end, payment_date) for a payment month.

        Closing/payment days 28–31 are clamped to the actual month end.  The
        selected month is always the payment month; offset moves the closing
        month backwards (e.g. September + 翌月 => an August closing period).
        Unconfigured or invalid legacy rows return ``None`` so old cards can
        be shown as 未設定 without taking down the page.
        """
        if not self.schedule_configured:
            return None
        try:
            payment_year, payment_month = int(payment_year), int(payment_month)
            if not 1 <= payment_month <= 12:
                return None
            offset = int(self.payment_month_offset)
            if offset not in (0, 1, 2):
                return None
            payment_date = _clamped_day(payment_year, payment_month, self.payment_day)
            closing_year, closing_month = _shift_month(payment_year, payment_month, -offset)
            period_end = _clamped_day(closing_year, closing_month, self.closing_day)
            prior_year, prior_month = _shift_month(closing_year, closing_month, -1)
            prior_close = _clamped_day(prior_year, prior_month, self.closing_day)
            period_start = prior_close + timedelta(days=1)
            return period_start, period_end, payment_date
        except (TypeError, ValueError, OverflowError):
            return None

    # A descriptive alias makes the calculation convenient in views/tests and
    # keeps the model API unsurprising for future callers.
    get_statement_period = statement_period


def resolve_settlement(source):
    """Return immediate source, final settlement source, and display path.

    A code payment without a configured source deliberately remains unresolved;
    it must not be silently attributed to the code payment itself.
    """
    if source.kind in (PaymentSource.Kind.CODE, PaymentSource.Kind.CREDIT) and not source.linked_source_id:
        return None, None, f"{source.name} → 未設定"
    immediate = source.linked_source
    current = source
    names = [source.name]
    seen = {source.pk}
    while current.linked_source_id:
        current = current.linked_source
        if current.pk in seen:
            return immediate, None, " → ".join(names + ["設定エラー"])
        seen.add(current.pk)
        names.append(current.name)
        # A code payment may be directly charged to a card. Without that
        # card's bank setting, the card is known but the final settlement is
        # deliberately unresolved.
        if current.kind == PaymentSource.Kind.CREDIT and not current.linked_source_id:
            return immediate, None, " → ".join(names + ["未設定"])
    return immediate, current, " → ".join(names)


class HouseholdEntry(models.Model):
    class EntryType(models.TextChoices):
        EXPENSE = "expense", "通常支出"
        FLEA_PROFIT = "flea_profit", "フリマ利益"
        FLEA_WITHDRAWAL = "flea_withdrawal", "フリマ出金"

    spent_on = models.DateField()
    shop_name = models.CharField(max_length=150)
    description = models.CharField(max_length=200)
    amount_yen = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    entry_type = models.CharField(max_length=20, choices=EntryType.choices, default=EntryType.EXPENSE)
    payment_source = models.ForeignKey(PaymentSource, on_delete=models.PROTECT, related_name="entries")
    payment_source_name_snapshot = models.CharField(max_length=100)
    payment_source_kind_snapshot = models.CharField(max_length=20)
    linked_source = models.ForeignKey(PaymentSource, null=True, blank=True, on_delete=models.PROTECT, related_name="funded_entries")
    linked_source_name_snapshot = models.CharField(max_length=100, blank=True)
    settlement_source = models.ForeignKey(PaymentSource, null=True, blank=True, on_delete=models.PROTECT, related_name="settled_entries")
    settlement_source_name_snapshot = models.CharField(max_length=100, blank=True)
    settlement_path_snapshot = models.CharField(max_length=320, blank=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-spent_on", "-created_at", "-id"]

    @property
    def is_deleted(self):
        return self.deleted_at is not None


class Person(models.Model):
    name = models.CharField(max_length=100, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class MedicalVisit(models.Model):
    """One date's visit, with hospital, pharmacy, and transport line items."""

    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="medical_visits")
    record_year = models.PositiveSmallIntegerField()
    visited_on = models.DateField()
    # Empty is used only for safely migrated legacy pharmacy/transport records
    # whose originating hospital cannot be known.
    hospital_name = models.CharField(max_length=150, blank=True)
    cumulative_amount_yen = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-visited_on", "-created_at", "-id"]

    @property
    def is_deleted(self):
        return self.deleted_at is not None

    @property
    def display_name(self):
        if self.hospital_name:
            return self.hospital_name
        first_detail = self.entries.filter(deleted_at__isnull=True).order_by("created_at", "id").first()
        return first_detail.provider_name if first_detail else "名称未設定"


class MedicalEntry(models.Model):
    class Category(models.TextChoices):
        HOSPITAL = "hospital", "病院"
        PHARMACY = "pharmacy", "薬局"
        TRANSPORT = "transport", "交通費"

    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="medical_entries")
    visit = models.ForeignKey(
        MedicalVisit,
        on_delete=models.PROTECT,
        related_name="entries",
        null=True,
        blank=True,
    )
    record_year = models.PositiveSmallIntegerField()
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.HOSPITAL)
    provider_name = models.CharField(max_length=150)
    paid_amount_yen = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    cumulative_amount_yen = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "id"]
