"""Email delivery service supporting both console logging and SMTP."""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class EmailDeliveryError(Exception):
    """Raised when email transmission fails."""
    pass


class EmailService:
    """Handles sending transactional emails including OTP verification codes."""

    def __init__(self) -> None:
        self.delivery_method = settings.EMAIL_DELIVERY_METHOD
        self.smtp_host = settings.SMTP_HOST
        self.smtp_port = settings.SMTP_PORT
        self.smtp_user = settings.SMTP_USER
        self.smtp_password = settings.SMTP_PASSWORD
        self.from_email = settings.SMTP_FROM_EMAIL

    async def send_otp_email(self, recipient_email: str, otp_code: str) -> None:
        """Deliver OTP verification code to recipient."""
        subject = f"Your Verification Code: {otp_code} - {settings.APP_NAME}"
        body_text = (
            f"Hello,\n\n"
            f"Your verification code is: {otp_code}\n\n"
            f"This code will expire in {settings.OTP_EXPIRE_MINUTES} minutes.\n"
            f"If you did not request this, please disregard this email."
        )

        if self.delivery_method == "console" or not self.smtp_user:
            logger.info("=" * 60)
            logger.info("📧 [LOCAL DEV EMAIL DISPATCH]")
            logger.info("To: %s", recipient_email)
            logger.info("Subject: %s", subject)
            logger.info("OTP Code: %s", otp_code)
            logger.info("=" * 60)
            return

        try:
            msg = MIMEMultipart()
            msg["From"] = self.from_email
            msg["To"] = recipient_email
            msg["Subject"] = subject
            msg.attach(MIMEText(body_text, "plain"))

            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_user, self.smtp_password)
                server.send_message(msg)

            logger.info("Successfully sent OTP email to %s", recipient_email)
        except Exception as exc:
            logger.error("Failed to send email to %s: %s", recipient_email, str(exc))
            raise EmailDeliveryError("Failed to deliver verification email") from exc


email_service = EmailService()
