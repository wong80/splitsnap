from __future__ import annotations

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404

from .models import Bill


def admin_bill_detail(request: HttpRequest, admin_token: str) -> HttpResponse:
    bill = get_object_or_404(Bill, admin_token=admin_token)
    return JsonResponse({"id": str(bill.id), "title": bill.title, "status": bill.status})


def share_bill_detail(request: HttpRequest, share_token: str) -> HttpResponse:
    bill = get_object_or_404(Bill, share_token=share_token)
    return JsonResponse({"id": str(bill.id), "title": bill.title, "status": bill.status})
