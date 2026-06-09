"""
Email service for sending OTP codes to users
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
import random
import logging

logger = logging.getLogger(__name__)


def generate_otp() -> str:
    """
    Generate a random 6-digit OTP.
    
    Returns:
        6-digit OTP string (e.g., "123456")
    """
    return str(random.randint(100000, 999999))


def send_otp_email(email: str, otp: str) -> bool:
    """
    Send OTP to user's email using Gmail SMTP.
    
    Args:
        email: Recipient's email address
        otp: 6-digit OTP code
    
    Returns:
        True if email sent successfully, False otherwise
    """
    try:
        sender_email = os.getenv("EMAIL_FROM") or os.getenv("SENDER_EMAIL")
        sender_password = os.getenv("SMTP_PASSWORD") or os.getenv("SENDER_EMAIL_PASSWORD")
        
        if not sender_email or not sender_password:
            logger.warning("⚠️  Email credentials not configured in .env")
            logger.warning(f"For testing: OTP for {email} is: {otp}")
            return False
        
        # Create email message
        message = MIMEMultipart()
        message["From"] = sender_email
        message["To"] = email
        message["Subject"] = "Your deInfluence OTP - Valid for 5 minutes"
        
        # HTML email body
        html_body = f"""
        <html>
          <body style="font-family: 'Plus Jakarta Sans', Arial, sans-serif; background: #fff8f5; line-height: 1.6;">
            <div style="max-width: 600px; margin: 0 auto; padding: 40px 20px; background: #ffffff; border-radius: 16px; border: 1px solid #ffdbc9;">
              
              <!-- Header -->
              <div style="text-align: center; margin-bottom: 40px;">
                <h1 style="color: #b4262f; margin: 0; font-size: 28px; font-weight: bold;">deInfluence</h1>
                <p style="color: #81746e; margin: 8px 0 0 0; font-size: 14px;">Editorial Glamour</p>
              </div>
              
              <!-- Main Content -->
              <div style="text-align: center;">
                <h2 style="color: #2a170b; font-size: 24px; margin: 0 0 16px 0;">Verify Your Email</h2>
                <p style="color: #4f453f; font-size: 16px; margin: 0 0 32px 0;">
                  Your One-Time Password (OTP) for email verification is:
                </p>
                
                <!-- OTP Code -->
                <div style="background: #ffeadf; padding: 24px; border-radius: 12px; margin: 0 0 32px 0;">
                  <h1 style="color: #b4262f; font-size: 48px; letter-spacing: 8px; margin: 0; font-weight: bold; font-family: 'Courier New', monospace;">
                    {otp}
                  </h1>
                </div>
                
                <!-- Expiry Notice -->
                <p style="color: #984444; font-size: 14px; font-weight: bold; margin: 0 0 24px 0;">
                  ⏱️ This OTP will expire in 5 minutes
                </p>
                
                <!-- Disclaimer -->
                <p style="color: #4f453f; font-size: 14px; margin: 0; line-height: 1.6;">
                  If you did not request this OTP or did not sign up for deInfluence, <br>
                  please ignore this email or contact our support team.
                </p>
              </div>
              
              <!-- Footer -->
              <div style="text-align: center; margin-top: 40px; padding-top: 24px; border-top: 1px solid #ffdbc9;">
                <p style="color: #81746e; font-size: 12px; margin: 0;">
                  © 2026 deInfluence. All rights reserved.<br>
                  <a href="#" style="color: #b4262f; text-decoration: none;">Privacy Policy</a> • 
                  <a href="#" style="color: #b4262f; text-decoration: none;">Terms of Service</a>
                </p>
              </div>
              
            </div>
          </body>
        </html>
        """
        
        message.attach(MIMEText(html_body, "html"))
        
        # Get SMTP configuration
        smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        smtp_port = int(os.getenv("SMTP_PORT", 587))
        
        # Send email via SMTP
        server = smtplib.SMTP(smtp_host, smtp_port)
        server.starttls()
        server.login(sender_email, sender_password)
        server.send_message(message)
        server.quit()
        
        logger.info(f"✅ OTP email sent to {email}")
        return True
    
    except smtplib.SMTPAuthenticationError:
        logger.error(f"❌ Gmail authentication failed. Check email/password in .env")
        return False
    except Exception as e:
        logger.error(f"❌ Error sending OTP email: {e}")
        return False


def send_welcome_email(email: str, name: str) -> bool:
    """
    Send welcome email after successful registration.
    
    Args:
        email: Recipient's email address
        name: User's name
    
    Returns:
        True if email sent successfully, False otherwise
    """
    try:
        sender_email = os.getenv("EMAIL_FROM") or os.getenv("SENDER_EMAIL")
        sender_password = os.getenv("SMTP_PASSWORD") or os.getenv("SENDER_EMAIL_PASSWORD")
        
        if not sender_email or not sender_password:
            return False
        
        message = MIMEMultipart()
        message["From"] = sender_email
        message["To"] = email
        message["Subject"] = "Welcome to deInfluence!"
        
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
        
        message.attach(MIMEText(html_body, "html"))
        
        # Get SMTP configuration
        smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        smtp_port = int(os.getenv("SMTP_PORT", 587))
        
        # Send email via SMTP
        server = smtplib.SMTP(smtp_host, smtp_port)
        server.starttls()
        server.login(sender_email, sender_password)
        server.send_message(message)
        server.quit()
        
        logger.info(f"✅ Welcome email sent to {email}")
        return True
    
    except Exception as e:
        logger.error(f"❌ Error sending welcome email: {e}")
        return False
