"""
Email service for sending OTP codes to users
"""

import os
import random
import logging
import resend

logger = logging.getLogger(__name__)

resend.api_key = os.getenv("RESEND_API_KEY")

# Use this until you verify your own domain on Resend
FROM_EMAIL = os.getenv("EMAIL_FROM", "onboarding@resend.dev")


def generate_otp() -> str:
    """Generate a random 6-digit OTP."""
    return str(random.randint(100000, 999999))


def send_otp_email(email: str, otp: str) -> bool:
    """
    Send OTP to user's email using Resend's HTTP API.
    """
    try:
        if not resend.api_key:
            logger.warning("⚠️  RESEND_API_KEY not configured")
            logger.warning(f"For testing: OTP for {email} is: {otp}")
            return False

        html_body = f"""
        <html>
          <body style="font-family: 'Plus Jakarta Sans', Arial, sans-serif; background: #fff8f5; line-height: 1.6;">
            <div style="max-width: 600px; margin: 0 auto; padding: 40px 20px; background: #ffffff; border-radius: 16px; border: 1px solid #ffdbc9;">
              <div style="text-align: center; margin-bottom: 40px;">
                <h1 style="color: #b4262f; margin: 0; font-size: 28px; font-weight: bold;">deInfluence</h1>
                <p style="color: #81746e; margin: 8px 0 0 0; font-size: 14px;">Editorial Glamour</p>
              </div>
              <div style="text-align: center;">
                <h2 style="color: #2a170b; font-size: 24px; margin: 0 0 16px 0;">Verify Your Email</h2>
                <p style="color: #4f453f; font-size: 16px; margin: 0 0 32px 0;">
                  Your One-Time Password (OTP) for email verification is:
                </p>
                <div style="background: #ffeadf; padding: 24px; border-radius: 12px; margin: 0 0 32px 0;">
                  <h1 style="color: #b4262f; font-size: 48px; letter-spacing: 8px; margin: 0; font-weight: bold; font-family: 'Courier New', monospace;">
                    {otp}
                  </h1>
                </div>
                <p style="color: #984444; font-size: 14px; font-weight: bold; margin: 0 0 24px 0;">
                  ⏱️ This OTP will expire in 5 minutes
                </p>
                <p style="color: #4f453f; font-size: 14px; margin: 0; line-height: 1.6;">
                  If you did not request this OTP or did not sign up for deInfluence, <br>
                  please ignore this email or contact our support team.
                </p>
              </div>
              <div style="text-align: center; margin-top: 40px; padding-top: 24px; border-top: 1px solid #ffdbc9;">
                <p style="color: #81746e; font-size: 12px; margin: 0;">
                  © 2026 deInfluence. All rights reserved.
                </p>
              </div>
            </div>
          </body>
        </html>
        """

        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": email,
            "subject": "Your deInfluence OTP - Valid for 5 minutes",
            "html": html_body,
        })

        logger.info(f"✅ OTP email sent to {email}")
        return True

    except Exception as e:
        logger.error(f"❌ Error sending OTP email: {e}")
        return False


def send_welcome_email(email: str, name: str) -> bool:
    """
    Send welcome email after successful registration.
    """
    try:
        if not resend.api_key:
            return False

        html_body = f"""
        <html>
          <body style="font-family: 'Plus Jakarta Sans', Arial, sans-serif; background: #fff8f5;">
            <div style="max-width: 600px; margin: 40px auto; padding: 40px; background: #ffffff; border-radius: 16px; border: 1px solid #ffdbc9;">
              <h2 style="color: #b4262f;">Welcome to deInfluence, {name}!</h2>
              <p>Your account has been verified successfully. Start your editorial beauty journey today.</p>
              <a href="http://localhost:5500/frontend-html/quiz.html" style="display: inline-block; background: #b4262f; color: white; padding: 12px 24px; border-radius: 8px; text-decoration: none; font-weight: bold; margin-top: 20px;">
                Complete Your Profile
              </a>
            </div>
          </body>
        </html>
        """

        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": email,
            "subject": "Welcome to deInfluence!",
            "html": html_body,
        })

        logger.info(f"✅ Welcome email sent to {email}")
        return True

    except Exception as e:
        logger.error(f"❌ Error sending welcome email: {e}")
        return False