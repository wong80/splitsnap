from __future__ import annotations

import contextlib
import datetime
import logging

from django.core.files.base import ContentFile
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods
from django_ratelimit.decorators import ratelimit

from receipts.extraction import get_extractor
from receipts.images import prepare_image
from receipts.validation import run_extraction
from splitting.engine import Charge, Item, PaymentEntry, compute_shares
from splitting.money import CURRENCIES, to_display, to_minor
from splitting.settle import settle

from .models import (
    Bill,
    BillCharge,
    BillStatus,
    ChargeKind,
    ItemClaim,
    LineItem,
    Participant,
    Payment,
    SplitSnapshot,
    Transfer,
)

logger = logging.getLogger(__name__)


def _bill_context(bill: Bill) -> dict:
    items = list(bill.line_items.all())
    charges = list(bill.charges.all())
    participants = list(bill.participants.all())

    item_total = sum(it.amount_minor - it.item_discount_minor for it in items)
    charge_total = sum(ch.amount_minor for ch in charges)
    gap = item_total + charge_total - bill.printed_total_minor

    payments = list(bill.payments.select_related("participant").all())
    payment_total = sum(p.amount_minor for p in payments)

    engine_items = []
    for it in items:
        claims = list(it.claims.select_related("participant").all())
        engine_items.append(
            Item(
                amount_minor=it.amount_minor,
                discount_minor=it.item_discount_minor,
                claims=[(c.participant_id, c.weight) for c in claims],
            )
        )

    engine_charges = [Charge(amount_minor=ch.amount_minor) for ch in charges]
    engine_payments = [
        PaymentEntry(participant_id=p.participant_id, amount_minor=p.amount_minor)
        for p in payments
    ]

    shares = compute_shares(engine_items, engine_charges, engine_payments)

    all_claimed = all(it.claims.exists() for it in items) if items else False
    item_subtotals_positive = (
        any(v > 0 for v in shares.item_subtotals.values()) if shares.item_subtotals else True
    )
    has_charges = bool(charges)
    can_lock = (
        all_claimed
        and gap == 0
        and payment_total == bill.printed_total_minor
        and (not has_charges or item_subtotals_positive)
        and items
    )

    return {
        "bill": bill,
        "items": items,
        "charges": charges,
        "participants": participants,
        "payments": payments,
        "gap": gap,
        "gap_display": to_display(gap, bill.currency),
        "payment_total": payment_total,
        "payment_total_display": to_display(payment_total, bill.currency),
        "printed_total_display": to_display(bill.printed_total_minor, bill.currency),
        "shares": shares,
        "can_lock": can_lock,
        "all_claimed": all_claimed,
        "charge_kinds": ChargeKind.choices,
    }


def _person_totals(bill: Bill, shares) -> list[dict]:
    participants = {p.id: p for p in bill.participants.all()}
    totals = []
    for pid, name in sorted(
        ((p.id, p.name) for p in participants.values()), key=lambda x: x[1].lower()
    ):
        totals.append(
            {
                "name": name,
                "owed": shares.owed.get(pid, 0),
                "owed_display": to_display(shares.owed.get(pid, 0), bill.currency),
                "net": shares.net.get(pid, 0),
                "net_display": to_display(shares.net.get(pid, 0), bill.currency),
            }
        )
    return totals


# --- Upload ---


@ratelimit(key="ip", rate="10/h", method="POST", block=True)
@require_http_methods(["GET", "POST"])
def upload(request: HttpRequest) -> HttpResponse:
    if request.method == "GET":
        return render(request, "bills/upload.html")

    file = request.FILES.get("receipt")
    if not file:
        return render(request, "bills/upload.html", {"error": "Please select a file."})

    if file.size > 10 * 1024 * 1024:
        return render(request, "bills/upload.html", {"error": "File too large (max 10 MB)."})

    try:
        image_data = prepare_image(file.read())
    except ValueError:
        return render(
            request,
            "bills/upload.html",
            {"error": "Invalid image. Please upload JPEG, PNG, WEBP, or HEIC."},
        )

    extractor = get_extractor()
    result = run_extraction(image_data, extractor)

    now = timezone.now()
    bill = Bill.objects.create(
        title=result.receipt.title,
        currency=result.receipt.currency.upper(),
        status=BillStatus.REVIEW,
        extraction_attempts=result.attempts,
        prompt_version="extract_v1",
        expires_at=now + datetime.timedelta(days=7),
    )
    bill.receipt_image.save("receipt.jpg", ContentFile(image_data), save=True)

    if result.receipt.printed_total:
        try:
            bill.printed_total_minor = to_minor(result.receipt.printed_total, bill.currency)
            bill.save(update_fields=["printed_total_minor"])
        except ValueError:
            pass

    for i, item in enumerate(result.receipt.items):
        try:
            amount = to_minor(item.amount, bill.currency)
            discount = to_minor(item.item_discount, bill.currency)
        except ValueError:
            continue
        LineItem.objects.create(
            bill=bill,
            position=i + 1,
            description=item.description,
            quantity=item.quantity,
            amount_minor=amount,
            item_discount_minor=discount,
        )

    for charge in result.receipt.charges:
        try:
            amount = to_minor(charge.amount, bill.currency)
        except ValueError:
            continue
        kind = charge.kind if charge.kind in dict(ChargeKind.choices) else "other"
        BillCharge.objects.create(bill=bill, kind=kind, label=charge.label, amount_minor=amount)

    logger.info("bill.created", extra={"bill_id": str(bill.id), "currency": bill.currency})
    return redirect("admin-bill-detail", admin_token=bill.admin_token)


# --- Admin detail ---


@require_http_methods(["GET", "POST"])
def admin_bill_detail(request: HttpRequest, admin_token: str) -> HttpResponse:
    bill = get_object_or_404(Bill, admin_token=admin_token)

    if bill.status == BillStatus.LOCKED:
        if request.method == "POST" and request.POST.get("action") == "unlock":
            return _handle_unlock(request, bill)
        return _render_summary(request, bill, is_admin=True)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "update_bill":
            return _handle_update_bill(request, bill)
        if action == "add_item":
            return _handle_add_item(request, bill)
        if action == "delete_item":
            return _handle_delete_item(request, bill)
        if action == "add_charge":
            return _handle_add_charge(request, bill)
        if action == "delete_charge":
            return _handle_delete_charge(request, bill)
        if action == "add_participant":
            return _handle_add_participant(request, bill)
        if action == "remove_participant":
            return _handle_remove_participant(request, bill)
        if action == "add_payment":
            return _handle_add_payment(request, bill)
        if action == "delete_payment":
            return _handle_delete_payment(request, bill)
        if action == "confirm":
            return _handle_confirm(request, bill)
        if action == "lock":
            return _handle_lock(request, bill)
        if action == "unlock":
            return _handle_unlock(request, bill)

    ctx = _bill_context(bill)
    ctx["person_totals"] = _person_totals(bill, ctx["shares"])
    ctx["is_admin"] = True
    return render(request, "bills/admin_detail.html", ctx)


# --- Share detail ---


@require_http_methods(["GET", "POST"])
def share_bill_detail(request: HttpRequest, share_token: str) -> HttpResponse:
    bill = get_object_or_404(Bill, share_token=share_token)

    if bill.status == BillStatus.LOCKED:
        return redirect("share-summary", share_token=share_token)

    if bill.status in (BillStatus.EXTRACTING, BillStatus.REVIEW):
        return render(request, "bills/share_waiting.html", {"bill": bill})

    try:
        participant_id = request.get_signed_cookie(f"participant_{bill.id}")
    except Exception:
        participant_id = None
    participant = None
    if participant_id:
        with contextlib.suppress(Participant.DoesNotExist):
            participant = Participant.objects.get(id=participant_id, bill=bill)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "identify":
            return _handle_identify(request, bill)
        if action == "toggle_claim" and participant:
            return _handle_toggle_claim(request, bill, participant)
        if action == "set_weight" and participant:
            return _handle_set_weight(request, bill, participant)

    ctx = _bill_context(bill)
    ctx["person_totals"] = _person_totals(bill, ctx["shares"])
    ctx["participant"] = participant
    ctx["is_admin"] = False
    if participant:
        ctx["claimed_ids"] = set(
            ItemClaim.objects.filter(participant=participant).values_list(
                "line_item_id", flat=True
            )
        )
    else:
        ctx["claimed_ids"] = set()
    response = render(request, "bills/share_detail.html", ctx)
    return response


@require_GET
def share_summary(request: HttpRequest, share_token: str) -> HttpResponse:
    bill = get_object_or_404(Bill, share_token=share_token)
    if bill.status != BillStatus.LOCKED:
        return redirect("share-bill-detail", share_token=share_token)
    return _render_summary(request, bill, is_admin=False)


# --- Action handlers ---


def _handle_update_bill(request: HttpRequest, bill: Bill) -> HttpResponse:
    title = request.POST.get("title", bill.title)
    currency = request.POST.get("currency", bill.currency).upper()
    printed_total = request.POST.get("printed_total", "")

    bill.title = title
    if currency in CURRENCIES:
        bill.currency = currency
    if printed_total:
        with contextlib.suppress(ValueError):
            bill.printed_total_minor = to_minor(printed_total, bill.currency)
    bill.save()
    return redirect("admin-bill-detail", admin_token=bill.admin_token)


def _handle_add_item(request: HttpRequest, bill: Bill) -> HttpResponse:
    desc = request.POST.get("description", "New item")
    amount = request.POST.get("amount", "0")
    try:
        quantity = int(request.POST.get("quantity", "1") or "1")
    except ValueError:
        quantity = 1
    discount = request.POST.get("discount", "0")

    last_pos = (
        bill.line_items.order_by("-position").values_list("position", flat=True).first() or 0
    )

    try:
        amount_minor = to_minor(amount, bill.currency)
        discount_minor = to_minor(discount, bill.currency)
    except ValueError:
        return redirect("admin-bill-detail", admin_token=bill.admin_token)

    LineItem.objects.create(
        bill=bill,
        position=last_pos + 1,
        description=desc,
        quantity=max(1, quantity),
        amount_minor=max(0, amount_minor),
        item_discount_minor=max(0, discount_minor),
    )
    return redirect("admin-bill-detail", admin_token=bill.admin_token)


def _handle_delete_item(request: HttpRequest, bill: Bill) -> HttpResponse:
    item_id = request.POST.get("item_id")
    bill.line_items.filter(id=item_id).delete()
    return redirect("admin-bill-detail", admin_token=bill.admin_token)


def _handle_add_charge(request: HttpRequest, bill: Bill) -> HttpResponse:
    kind = request.POST.get("kind", "other")
    if kind not in dict(ChargeKind.choices):
        kind = "other"
    label = request.POST.get("label", "")
    amount = request.POST.get("amount", "0")
    try:
        amount_minor = to_minor(amount, bill.currency)
    except ValueError:
        return redirect("admin-bill-detail", admin_token=bill.admin_token)
    BillCharge.objects.create(bill=bill, kind=kind, label=label, amount_minor=amount_minor)
    return redirect("admin-bill-detail", admin_token=bill.admin_token)


def _handle_delete_charge(request: HttpRequest, bill: Bill) -> HttpResponse:
    charge_id = request.POST.get("charge_id")
    bill.charges.filter(id=charge_id).delete()
    return redirect("admin-bill-detail", admin_token=bill.admin_token)


def _handle_add_participant(request: HttpRequest, bill: Bill) -> HttpResponse:
    name = request.POST.get("name", "").strip()
    if name:
        existing = bill.participants.filter(name__iexact=name).first()
        if not existing and bill.participants.count() < 20:
            Participant.objects.create(bill=bill, name=name)
    return redirect("admin-bill-detail", admin_token=bill.admin_token)


def _handle_remove_participant(request: HttpRequest, bill: Bill) -> HttpResponse:
    pid = request.POST.get("participant_id")
    bill.participants.filter(id=pid).delete()
    return redirect("admin-bill-detail", admin_token=bill.admin_token)


def _handle_add_payment(request: HttpRequest, bill: Bill) -> HttpResponse:
    pid = request.POST.get("participant_id")
    amount = request.POST.get("amount", "0")
    try:
        amount_minor = to_minor(amount, bill.currency)
    except ValueError:
        return redirect("admin-bill-detail", admin_token=bill.admin_token)
    if amount_minor > 0 and pid:
        if not bill.participants.filter(id=pid).exists():
            return redirect("admin-bill-detail", admin_token=bill.admin_token)
        Payment.objects.update_or_create(
            bill=bill,
            participant_id=pid,
            defaults={"amount_minor": amount_minor},
        )
    return redirect("admin-bill-detail", admin_token=bill.admin_token)


def _handle_delete_payment(request: HttpRequest, bill: Bill) -> HttpResponse:
    payment_id = request.POST.get("payment_id")
    bill.payments.filter(id=payment_id).delete()
    return redirect("admin-bill-detail", admin_token=bill.admin_token)


def _handle_confirm(request: HttpRequest, bill: Bill) -> HttpResponse:
    if bill.status == BillStatus.REVIEW:
        bill.status = BillStatus.OPEN
        bill.save(update_fields=["status"])
    return redirect("admin-bill-detail", admin_token=bill.admin_token)


def _handle_lock(request: HttpRequest, bill: Bill) -> HttpResponse:
    if bill.status != BillStatus.OPEN:
        return redirect("admin-bill-detail", admin_token=bill.admin_token)

    ctx = _bill_context(bill)
    if not ctx["can_lock"]:
        return redirect("admin-bill-detail", admin_token=bill.admin_token)

    shares = ctx["shares"]
    charges_list = list(bill.charges.all())
    now = timezone.now()

    for pid in shares.owed:
        participant = Participant.objects.get(id=pid)
        per_charge = []
        for i, ch in enumerate(charges_list):
            amount = shares.charge_allocations[i].get(pid, 0)
            if amount != 0:
                per_charge.append(
                    {
                        "kind": ch.kind,
                        "label": ch.label or ch.get_kind_display(),
                        "amount": amount,
                    }
                )
        SplitSnapshot.objects.create(
            bill=bill,
            participant=participant,
            items_minor=shares.item_subtotals.get(pid, 0),
            charges_minor=per_charge,
            owed_minor=shares.owed[pid],
            paid_minor=shares.net[pid] + shares.owed[pid],
        )

    transfers = settle(shares.net)
    for t in transfers:
        Transfer.objects.create(
            bill=bill,
            from_participant_id=t.from_id,
            to_participant_id=t.to_id,
            amount_minor=t.amount_minor,
        )

    bill.status = BillStatus.LOCKED
    bill.locked_at = now
    bill.expires_at = now + datetime.timedelta(days=30)
    bill.save(update_fields=["status", "locked_at", "expires_at"])
    logger.info("bill.locked", extra={"bill_id": str(bill.id)})
    return redirect("admin-bill-detail", admin_token=bill.admin_token)


def _handle_unlock(request: HttpRequest, bill: Bill) -> HttpResponse:
    if bill.status != BillStatus.LOCKED:
        return redirect("admin-bill-detail", admin_token=bill.admin_token)

    bill.snapshots.all().delete()
    bill.transfers.all().delete()
    bill.status = BillStatus.OPEN
    bill.locked_at = None
    bill.expires_at = bill.created_at + datetime.timedelta(days=7)
    bill.save(update_fields=["status", "locked_at", "expires_at"])
    logger.info("bill.unlocked", extra={"bill_id": str(bill.id)})
    return redirect("admin-bill-detail", admin_token=bill.admin_token)


# --- Share page actions ---


def _handle_identify(request: HttpRequest, bill: Bill) -> HttpResponse:
    if bill.status != BillStatus.OPEN:
        return redirect("share-bill-detail", share_token=bill.share_token)

    name = request.POST.get("name", "").strip()
    pid = request.POST.get("participant_id")

    participant = None
    if pid:
        with contextlib.suppress(Participant.DoesNotExist):
            participant = Participant.objects.get(id=pid, bill=bill)
    elif name:
        participant = bill.participants.filter(name__iexact=name).first()
        if not participant and bill.participants.count() < 20:
            participant = Participant.objects.create(bill=bill, name=name)

    if participant:
        response = redirect("share-bill-detail", share_token=bill.share_token)
        response.set_signed_cookie(
            f"participant_{bill.id}",
            str(participant.id),
            max_age=30 * 24 * 3600,
            httponly=True,
            samesite="Lax",
        )
        return response
    return redirect("share-bill-detail", share_token=bill.share_token)


def _handle_toggle_claim(
    request: HttpRequest, bill: Bill, participant: Participant
) -> HttpResponse:
    if bill.status != BillStatus.OPEN:
        return redirect("share-bill-detail", share_token=bill.share_token)

    item_id = request.POST.get("item_id")
    try:
        item = bill.line_items.get(id=item_id)
    except LineItem.DoesNotExist:
        return redirect("share-bill-detail", share_token=bill.share_token)

    claim = ItemClaim.objects.filter(line_item=item, participant=participant).first()
    if claim:
        claim.delete()
    else:
        ItemClaim.objects.create(line_item=item, participant=participant, weight=1)

    return redirect("share-bill-detail", share_token=bill.share_token)


def _handle_set_weight(request: HttpRequest, bill: Bill, participant: Participant) -> HttpResponse:
    if bill.status != BillStatus.OPEN:
        return redirect("share-bill-detail", share_token=bill.share_token)

    item_id = request.POST.get("item_id")
    try:
        weight = int(request.POST.get("weight", "1") or "1")
    except ValueError:
        weight = 1

    try:
        item = bill.line_items.get(id=item_id)
    except LineItem.DoesNotExist:
        return redirect("share-bill-detail", share_token=bill.share_token)

    weight = max(1, min(weight, item.quantity))
    ItemClaim.objects.update_or_create(
        line_item=item,
        participant=participant,
        defaults={"weight": weight},
    )
    return redirect("share-bill-detail", share_token=bill.share_token)


# --- Summary ---


def _render_summary(request: HttpRequest, bill: Bill, *, is_admin: bool) -> HttpResponse:
    snapshots = list(bill.snapshots.select_related("participant").order_by("participant__name"))
    transfers = list(bill.transfers.select_related("from_participant", "to_participant").all())

    for snap in snapshots:
        snap.owed_display = to_display(snap.owed_minor, bill.currency)
        snap.paid_display = to_display(snap.paid_minor, bill.currency)
        snap.net_display = to_display(snap.paid_minor - snap.owed_minor, bill.currency)

    for t in transfers:
        t.amount_display = to_display(t.amount_minor, bill.currency)

    text_lines = [f"{bill.title} — Settlement"]
    text_lines.append("")
    for t in transfers:
        text_lines.append(
            f"{t.from_participant.name} → {t.to_participant.name}: "
            f"{to_display(t.amount_minor, bill.currency)} {bill.currency}"
        )
    text_lines.append("")
    for snap in snapshots:
        text_lines.append(f"{snap.participant.name}: owes {snap.owed_display}")
    plain_text = "\n".join(text_lines)

    ctx = {
        "bill": bill,
        "snapshots": snapshots,
        "transfers": transfers,
        "plain_text": plain_text,
        "is_admin": is_admin,
        "printed_total_display": to_display(bill.printed_total_minor, bill.currency),
    }
    return render(request, "bills/summary.html", ctx)
