from django.db import models
from django.core.validators import MinValueValidator


class PaymentSource(models.Model):
    class Kind(models.TextChoices):
        CREDIT = "credit_card", "クレジットカード"
        CODE = "code_payment", "コード決済"
        POINT = "point", "ポイント"
        BANK = "bank", "銀行"
        CASH = "cash", "現金・その他"

    kind = models.CharField(max_length=20, choices=Kind.choices)
    name = models.CharField(max_length=100)
    linked_source = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="code_payments")
    note = models.CharField(max_length=300, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["kind", "name"]
        constraints = [models.UniqueConstraint(fields=["kind", "name"], name="unique_source_name_per_kind")]

    def __str__(self):
        return self.name


class HouseholdEntry(models.Model):
    spent_on = models.DateField()
    shop_name = models.CharField(max_length=150)
    description = models.CharField(max_length=200)
    amount_yen = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    payment_source = models.ForeignKey(PaymentSource, on_delete=models.PROTECT, related_name="entries")
    payment_source_name_snapshot = models.CharField(max_length=100)
    payment_source_kind_snapshot = models.CharField(max_length=20)
    linked_source = models.ForeignKey(PaymentSource, null=True, blank=True, on_delete=models.PROTECT, related_name="funded_entries")
    linked_source_name_snapshot = models.CharField(max_length=100, blank=True)
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
