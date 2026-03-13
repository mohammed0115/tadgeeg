from django.contrib.sessions.backends.db import SessionStore
from django.core.management.base import BaseCommand, CommandError
from django.test.client import RequestFactory

from apps.authentication.models import User
from apps.authentication.services.email_otp import (
    EmailOTPError,
    PENDING_EMAIL_VERIFICATION_SESSION_KEY,
    issue_email_otp,
    mask_email_address,
)


class Command(BaseCommand):
    help = "Send a test OTP email through the real onboarding OTP service."

    def add_arguments(self, parser):
        parser.add_argument("email", help="Target email address for the OTP flow.")
        parser.add_argument(
            "--create-if-missing",
            action="store_true",
            help="Create a temporary unverified user when the email does not exist.",
        )
        parser.add_argument(
            "--full-name",
            default="OTP Debug User",
            help="Full name used when creating a temporary debug user.",
        )
        parser.add_argument(
            "--force-new",
            action="store_true",
            help="Invalidate any reusable OTP and force a fresh email send.",
        )

    def handle(self, *args, **options):
        email = (options["email"] or "").strip().lower()
        if not email:
            raise CommandError("Email is required.")

        user = User.objects.filter(email__iexact=email).first()
        created = False

        if user is None:
            if not options["create_if_missing"]:
                raise CommandError(
                    "User not found. Use --create-if-missing to create a temporary unverified debug user."
                )

            user = User.objects.create_user(
                email=email,
                password=None,
                full_name=(options["full_name"] or "OTP Debug User").strip() or "OTP Debug User",
                role=User.Role.JUNIOR_AUDITOR,
                organization=None,
                is_active=True,
                email_verified_at=None,
            )
            created = True

        if user.is_email_verified:
            raise CommandError(
                "The selected user is already email-verified. Use an unverified account or a temporary debug user."
            )

        request = RequestFactory().get("/verify-email/")
        request.session = SessionStore()
        request.META["REMOTE_ADDR"] = "127.0.0.1"

        try:
            challenge, sent = issue_email_otp(
                user,
                request,
                allow_recent_reuse=not options["force_new"],
            )
        except EmailOTPError as exc:
            raise CommandError(f"OTP send failed: {exc.message}") from exc

        request.session.save()

        if created:
            self.stdout.write(self.style.SUCCESS("Temporary unverified debug user created."))

        if sent:
            self.stdout.write(self.style.SUCCESS("OTP email sent successfully."))
        else:
            self.stdout.write(self.style.WARNING("Existing OTP is still valid; the previous code was reused."))

        self.stdout.write(f"Email: {mask_email_address(user.email)}")
        self.stdout.write(f"User ID: {user.id}")
        self.stdout.write(f"Challenge ID: {challenge.id}")
        self.stdout.write(f"Expires At: {challenge.expires_at.isoformat()}")
        self.stdout.write(
            f"Pending Verification Session User ID: {request.session.get(PENDING_EMAIL_VERIFICATION_SESSION_KEY)}"
        )
