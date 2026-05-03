"""Long-lived stream worker.

Usage:
    python manage.py run_stream_worker
    python manage.py run_stream_worker --max-seconds 60
    python manage.py run_stream_worker --group anomaly --consumer worker-2
"""

from __future__ import annotations

import signal
import threading

from django.core.management.base import BaseCommand

from apps.streaming.worker import run_consumer


class Command(BaseCommand):
    help = "Run the continuous-auditing stream consumer."

    def add_arguments(self, parser):
        parser.add_argument("--group",       default="tadgeeg-anomaly")
        parser.add_argument("--consumer",    default="worker-1")
        parser.add_argument("--max-seconds", type=int, default=None,
                            help="Exit after N seconds (useful for cron-style runs).")

    def handle(self, *args, **opts):
        stop_event = threading.Event()

        def _stop(signum, _frame):
            self.stdout.write(self.style.WARNING(f"received signal {signum} — stopping"))
            stop_event.set()

        signal.signal(signal.SIGINT, _stop)
        signal.signal(signal.SIGTERM, _stop)

        summary = run_consumer(
            group=opts["group"], consumer=opts["consumer"],
            stop_event=stop_event, max_seconds=opts["max_seconds"],
        )
        self.stdout.write(self.style.SUCCESS(f"worker exited: {summary}"))
