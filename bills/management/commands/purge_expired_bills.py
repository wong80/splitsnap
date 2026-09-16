from __future__ import annotations

import logging

from django.core.management.base import BaseCommand
from django.utils import timezone

from bills.models import Bill

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Delete expired bills and their associated storage objects."

    def handle(self, *args, **options):
        now = timezone.now()
        expired = Bill.objects.filter(expires_at__lt=now)

        count = 0
        for bill in expired.iterator():
            if bill.receipt_image:
                bill.receipt_image.delete(save=False)
            bill.delete()
            count += 1

        self.stdout.write(f"Purged {count} expired bill(s).")
        logger.info("purge.completed", extra={"count": count})
