from __future__ import annotations

import secrets
import uuid

from django.core.exceptions import ValidationError
from django.db import models

from .storage import receipt_upload_path


def generate_token() -> str:
    return secrets.token_urlsafe(32)


class BillStatus(models.TextChoices):
    EXTRACTING = "extracting"
    REVIEW = "review"
    OPEN = "open"
    LOCKED = "locked"


class ChargeKind(models.TextChoices):
    DISCOUNT = "discount"
    SERVICE_CHARGE = "service_charge"
    TAX = "tax"
    ROUNDING = "rounding"
    ADJUSTMENT = "adjustment"
    OTHER = "other"


class Bill(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    admin_token = models.CharField(max_length=64, unique=True, default=generate_token)
    share_token = models.CharField(max_length=64, unique=True, default=generate_token)
    title = models.CharField(max_length=200, blank=True, default="")
    currency = models.CharField(max_length=3, default="MYR")
    status = models.CharField(
        max_length=20, choices=BillStatus.choices, default=BillStatus.EXTRACTING
    )
    receipt_image = models.ImageField(upload_to=receipt_upload_path, blank=True)
    printed_total_minor = models.IntegerField(default=0)
    extraction_attempts = models.PositiveSmallIntegerField(default=0)
    prompt_version = models.CharField(max_length=50, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    locked_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.title or str(self.id)[:8]


class LineItem(models.Model):
    bill = models.ForeignKey(Bill, on_delete=models.CASCADE, related_name="line_items")
    position = models.PositiveSmallIntegerField()
    description = models.CharField(max_length=300)
    quantity = models.PositiveSmallIntegerField(default=1)
    amount_minor = models.PositiveIntegerField()
    item_discount_minor = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position"]
        unique_together = [("bill", "position")]

    def __str__(self) -> str:
        return self.description

    def clean(self) -> None:
        if self.item_discount_minor > self.amount_minor:
            raise ValidationError("Item discount cannot exceed item amount.")


class BillCharge(models.Model):
    bill = models.ForeignKey(Bill, on_delete=models.CASCADE, related_name="charges")
    kind = models.CharField(max_length=20, choices=ChargeKind.choices)
    label = models.CharField(max_length=200, blank=True, default="")
    amount_minor = models.IntegerField()

    def __str__(self) -> str:
        return self.label or self.get_kind_display()


class Participant(models.Model):
    bill = models.ForeignKey(Bill, on_delete=models.CASCADE, related_name="participants")
    name = models.CharField(max_length=100)

    class Meta:
        unique_together = [("bill", "name")]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs) -> None:
        self.name = self.name.strip()
        super().save(*args, **kwargs)

    def clean(self) -> None:
        self.name = self.name.strip()
        if not self.name:
            raise ValidationError("Participant name cannot be blank.")
        existing = Participant.objects.filter(bill=self.bill).exclude(pk=self.pk)
        if existing.filter(name__iexact=self.name).exists():
            raise ValidationError("A participant with this name already exists on this bill.")
        if not self.pk and existing.count() >= 20:
            raise ValidationError("A bill cannot have more than 20 participants.")


class ItemClaim(models.Model):
    line_item = models.ForeignKey(LineItem, on_delete=models.CASCADE, related_name="claims")
    participant = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name="claims")
    weight = models.PositiveSmallIntegerField(default=1)

    class Meta:
        unique_together = [("line_item", "participant")]

    def __str__(self) -> str:
        return f"{self.participant.name} → {self.line_item.description} (x{self.weight})"

    def clean(self) -> None:
        if self.weight < 1:
            raise ValidationError("Weight must be at least 1.")
        if self.weight > self.line_item.quantity:
            raise ValidationError("Weight cannot exceed item quantity.")


class Payment(models.Model):
    bill = models.ForeignKey(Bill, on_delete=models.CASCADE, related_name="payments")
    participant = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name="payments")
    amount_minor = models.PositiveIntegerField()

    class Meta:
        unique_together = [("bill", "participant")]

    def __str__(self) -> str:
        return f"{self.participant.name}: {self.amount_minor}"

    def clean(self) -> None:
        if self.amount_minor <= 0:
            raise ValidationError("Payment amount must be positive.")


class SplitSnapshot(models.Model):
    bill = models.ForeignKey(Bill, on_delete=models.CASCADE, related_name="snapshots")
    participant = models.ForeignKey(
        Participant, on_delete=models.CASCADE, related_name="snapshots"
    )
    items_minor = models.JSONField()
    charges_minor = models.JSONField()
    owed_minor = models.IntegerField()
    paid_minor = models.IntegerField()

    class Meta:
        unique_together = [("bill", "participant")]

    def __str__(self) -> str:
        return f"{self.participant.name}: owes {self.owed_minor}"


class Transfer(models.Model):
    bill = models.ForeignKey(Bill, on_delete=models.CASCADE, related_name="transfers")
    from_participant = models.ForeignKey(
        Participant, on_delete=models.CASCADE, related_name="transfers_out"
    )
    to_participant = models.ForeignKey(
        Participant, on_delete=models.CASCADE, related_name="transfers_in"
    )
    amount_minor = models.PositiveIntegerField()

    def __str__(self) -> str:
        return f"{self.from_participant.name} → {self.to_participant.name}: {self.amount_minor}"

    def clean(self) -> None:
        if self.amount_minor <= 0:
            raise ValidationError("Transfer amount must be positive.")
