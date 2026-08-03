import smtplib
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from typing import Optional, List
from jinja2 import Template
import logging
import io

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class EmailService:
    def __init__(
        self,
        smtp_server: str = "smtp.gmail.com",
        smtp_port: int = 587,
        sender_email: str = "",
        sender_password: str = "",
        use_tls: bool = True,
        resend_api_key: str = "",
        use_resend: bool = False,
        resend_from_email: str = "onboarding@resend.dev",
        brevo_api_key: str = "",
        use_brevo: bool = False,
        brevo_from_email: str = "",
        brevo_from_name: str = "Glimmora Hotel",
    ):
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.sender_email = sender_email
        self.sender_password = sender_password
        self.use_tls = use_tls
        self.resend_api_key = resend_api_key
        self.use_resend = use_resend and bool(resend_api_key)
        self.resend_from_email = resend_from_email
        self.brevo_api_key = brevo_api_key
        self.use_brevo = use_brevo and bool(brevo_api_key)
        self.brevo_from_email = brevo_from_email or sender_email
        self.brevo_from_name = brevo_from_name

    def send_email(
        self,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: Optional[str] = None,
        attachments: Optional[List[dict]] = None,
    ) -> bool:
        """
        Send an email using Brevo API (preferred), Resend API, or SMTP fallback.

        Args:
            to_email: Recipient email address
            subject: Email subject
            html_body: HTML content of the email
            text_body: Plain text content (optional)
            attachments: List of attachment dicts with 'filename' and 'content' (bytes) or 'file_path'

        Returns:
            bool: True if email sent successfully, False otherwise
        """
        # Use Brevo API if configured (preferred - no domain verification needed)
        if self.use_brevo:
            return self._send_via_brevo(to_email, subject, html_body, text_body, attachments)

        # Use Resend API if configured (requires domain verification)
        if self.use_resend:
            return self._send_via_resend(to_email, subject, html_body, text_body, attachments)

        # Fallback to SMTP
        return self._send_via_smtp(to_email, subject, html_body, text_body, attachments)

    def _send_via_brevo(
        self,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: Optional[str] = None,
        attachments: Optional[List[dict]] = None,
    ) -> bool:
        """Send email via Brevo API (HTTPS - works on all cloud providers)"""
        try:
            payload = {
                "sender": {
                    "name": self.brevo_from_name,
                    "email": self.brevo_from_email,
                },
                "to": [{"email": to_email}],
                "subject": subject,
                "htmlContent": html_body,
            }

            if text_body:
                payload["textContent"] = text_body

            if attachments:
                brevo_attachments = []
                for attachment in attachments:
                    if 'file_path' in attachment:
                        with open(attachment['file_path'], 'rb') as f:
                            file_data = f.read()
                        filename = attachment.get('filename', attachment['file_path'].split('/')[-1])
                    elif 'content' in attachment:
                        file_data = attachment['content']
                        filename = attachment.get('filename', 'attachment.pdf')
                    else:
                        continue

                    brevo_attachments.append({
                        "name": filename,
                        "content": base64.b64encode(file_data).decode('utf-8'),
                    })

                if brevo_attachments:
                    payload["attachment"] = brevo_attachments

            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    "https://api.brevo.com/v3/smtp/email",
                    headers={
                        "api-key": self.brevo_api_key,
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                    json=payload,
                )

                if response.status_code in (200, 201):
                    logger.info(f"Email sent successfully via Brevo to {to_email}")
                    return True
                else:
                    logger.error(f"Brevo API error: {response.status_code} - {response.text}")
                    return False

        except Exception as e:
            logger.error(f"Failed to send email via Brevo to {to_email}: {str(e)}")
            return False

    def _send_via_resend(
        self,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: Optional[str] = None,
        attachments: Optional[List[dict]] = None,
    ) -> bool:
        """Send email via Resend API (HTTPS - not blocked by cloud providers)"""
        try:
            payload = {
                "from": self.resend_from_email,
                "to": [to_email],
                "subject": subject,
                "html": html_body,
            }

            if text_body:
                payload["text"] = text_body

            if attachments:
                resend_attachments = []
                for attachment in attachments:
                    if 'file_path' in attachment:
                        with open(attachment['file_path'], 'rb') as f:
                            file_data = f.read()
                        filename = attachment.get('filename', attachment['file_path'].split('/')[-1])
                    elif 'content' in attachment:
                        file_data = attachment['content']
                        filename = attachment.get('filename', 'attachment.pdf')
                    else:
                        continue

                    resend_attachments.append({
                        "filename": filename,
                        "content": base64.b64encode(file_data).decode('utf-8'),
                    })

                if resend_attachments:
                    payload["attachments"] = resend_attachments

            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    "https://api.resend.com/emails",
                    headers={
                        "Authorization": f"Bearer {self.resend_api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )

                if response.status_code == 200:
                    logger.info(f"Email sent successfully via Resend to {to_email}")
                    return True
                else:
                    logger.error(f"Resend API error: {response.status_code} - {response.text}")
                    return False

        except Exception as e:
            logger.error(f"Failed to send email via Resend to {to_email}: {str(e)}")
            return False

    def _send_via_smtp(
        self,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: Optional[str] = None,
        attachments: Optional[List[dict]] = None,
    ) -> bool:
        """Send email via SMTP (fallback)"""
        try:
            # Create message
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self.sender_email
            msg["To"] = to_email

            # Add text and HTML parts
            if text_body:
                text_part = MIMEText(text_body, "plain")
                msg.attach(text_part)

            html_part = MIMEText(html_body, "html")
            msg.attach(html_part)

            # Add attachments if provided
            if attachments:
                for attachment in attachments:
                    if 'file_path' in attachment:
                        # Read from file path
                        with open(attachment['file_path'], 'rb') as f:
                            file_data = f.read()
                        filename = attachment.get('filename', attachment['file_path'].split('/')[-1])
                    elif 'content' in attachment:
                        # Use provided content (bytes)
                        file_data = attachment['content']
                        filename = attachment.get('filename', 'attachment.pdf')
                    else:
                        continue
                    
                    part = MIMEBase('application', 'octet-stream')
                    part.set_payload(file_data)
                    encoders.encode_base64(part)
                    part.add_header(
                        'Content-Disposition',
                        f'attachment; filename= {filename}'
                    )
                    msg.attach(part)

            # Connect to SMTP server and send
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                if self.use_tls:
                    server.starttls()
                server.login(self.sender_email, self.sender_password)
                server.send_message(msg)

            logger.info(f"Email sent successfully to {to_email}")
            return True
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {str(e)}")
            return False

    def send_password_reset_email(
        self,
        to_email: str,
        reset_token: str,
        reset_url: str,
        user_name: Optional[str] = None,
    ) -> bool:
        """
        Send password reset email with secure token
        
        Args:
            to_email: Recipient email address
            reset_token: Password reset token
            reset_url: Full URL for password reset (includes token)
            user_name: User's name (optional)
            
        Returns:
            bool: True if email sent successfully, False otherwise
        """
        subject = "Reset Your Password - Glimmora Hotel"

        # HTML email template
        html_template = Template("""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Reset Your Password</title>
        </head>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, #A57865 0%, #8E6554 100%); padding: 30px; text-align: center; border-radius: 10px 10px 0 0;">
                <h1 style="color: white; margin: 0; font-size: 28px;">Glimmora Hotel</h1>
            </div>
            
            <div style="background: #ffffff; padding: 40px; border: 1px solid #e0e0e0; border-top: none; border-radius: 0 0 10px 10px;">
                <h2 style="color: #A57865; margin-top: 0;">Password Reset Request</h2>
                
                {% if user_name %}
                <p>Hello {{ user_name }},</p>
                {% else %}
                <p>Hello,</p>
                {% endif %}
                
                <p>We received a request to reset your password for your Glimmora Hotel account. If you made this request, please click the button below to reset your password:</p>
                
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{{ reset_url }}" 
                       style="background-color: #A57865; color: white; padding: 14px 28px; text-decoration: none; border-radius: 6px; display: inline-block; font-weight: bold; font-size: 16px;">
                        Reset Password
                    </a>
                </div>
                
                <p>Or copy and paste this link into your browser:</p>
                <p style="word-break: break-all; color: #666; font-size: 14px; background: #f5f5f5; padding: 10px; border-radius: 4px;">{{ reset_url }}</p>
                
                <p style="color: #d32f2f; font-weight: bold;">⚠️ Important Security Information:</p>
                <ul style="color: #666;">
                    <li>This link will expire in 1 hour</li>
                    <li>This link can only be used once</li>
                    <li>If you didn't request this, please ignore this email</li>
                    <li>Your password will not change unless you click the link above</li>
                </ul>
                
                <p style="margin-top: 30px; color: #666; font-size: 14px;">
                    If you're having trouble clicking the button, copy and paste the URL above into your web browser.
                </p>
                
                <hr style="border: none; border-top: 1px solid #e0e0e0; margin: 30px 0;">
                
                <p style="color: #999; font-size: 12px; margin: 0;">
                    This is an automated email. Please do not reply to this message.<br>
                    If you have any questions, please contact our support team.
                </p>
            </div>
        </body>
        </html>
        """)

        # Plain text version
        text_template = Template("""
        Password Reset Request - Glimmora Hotel
        
        {% if user_name %}
        Hello {{ user_name }},
        {% else %}
        Hello,
        {% endif %}
        
        We received a request to reset your password for your Glimmora Hotel account.
        
        To reset your password, please visit the following link:
        {{ reset_url }}
        
        Important Security Information:
        - This link will expire in 1 hour
        - This link can only be used once
        - If you didn't request this, please ignore this email
        - Your password will not change unless you visit the link above
        
        If you're having trouble, copy and paste the URL above into your web browser.
        
        This is an automated email. Please do not reply to this message.
        """)

        html_body = html_template.render(
            reset_url=reset_url,
            user_name=user_name,
        )
        text_body = text_template.render(
            reset_url=reset_url,
            user_name=user_name,
        )

        return self.send_email(to_email, subject, html_body, text_body)

    def send_booking_confirmation_email(
        self,
        to_email: str,
        booking_number: str,
        guest_name: str,
        check_in: str,
        check_out: str,
        room_type: str,
        room_number: Optional[str],
        total_amount: float,
        currency: str = "INR",
        precheckin_url: Optional[str] = None,
        pdf_content: Optional[bytes] = None,
    ) -> bool:
        """
        Send booking confirmation email with PDF attachment
        
        Args:
            to_email: Recipient email address
            booking_number: Booking confirmation code
            guest_name: Guest's full name
            check_in: Check-in date (ISO format)
            check_out: Check-out date (ISO format)
            room_type: Type of room booked
            room_number: Room number (if assigned)
            total_amount: Total booking amount
            currency: Currency code
            precheckin_url: URL for pre-checkin (with booking ID)
            pdf_content: PDF file content as bytes
            
        Returns:
            bool: True if email sent successfully, False otherwise
        """
        subject = f"Booking Confirmation - {booking_number} - Glimmora Hotel"
        
        # Format dates
        from datetime import datetime
        try:
            check_in_date = datetime.fromisoformat(check_in.replace('Z', '+00:00'))
            check_out_date = datetime.fromisoformat(check_out.replace('Z', '+00:00'))
            check_in_formatted = check_in_date.strftime("%B %d, %Y")
            check_out_formatted = check_out_date.strftime("%B %d, %Y")
            nights = (check_out_date - check_in_date).days
        except:
            check_in_formatted = check_in
            check_out_formatted = check_out
            nights = 1
        
        # HTML email template
        html_template = Template("""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Booking Confirmation</title>
        </head>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, #A57865 0%, #8E6554 100%); padding: 30px; text-align: center; border-radius: 10px 10px 0 0;">
                <h1 style="color: white; margin: 0; font-size: 28px;">Glimmora Hotel</h1>
                <p style="color: rgba(255,255,255,0.9); margin: 10px 0 0 0; font-size: 16px;">Booking Confirmation</p>
            </div>
            
            <div style="background: #ffffff; padding: 40px; border: 1px solid #e0e0e0; border-top: none; border-radius: 0 0 10px 10px;">
                <div style="background: #f0f9ff; border-left: 4px solid #A57865; padding: 15px; margin-bottom: 30px;">
                    <p style="margin: 0; font-size: 18px; font-weight: bold; color: #A57865;">
                        Confirmation Number: {{ booking_number }}
                    </p>
                </div>
                
                <p>Dear {{ guest_name }},</p>
                
                <p>Thank you for choosing Glimmora Hotel! We're delighted to confirm your reservation.</p>
                
                <h3 style="color: #A57865; margin-top: 30px; margin-bottom: 15px;">Booking Details</h3>
                <table style="width: 100%; border-collapse: collapse; margin-bottom: 20px;">
                    <tr>
                        <td style="padding: 8px 0; border-bottom: 1px solid #e0e0e0; font-weight: bold; width: 40%;">Check-in:</td>
                        <td style="padding: 8px 0; border-bottom: 1px solid #e0e0e0;">{{ check_in_formatted }}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; border-bottom: 1px solid #e0e0e0; font-weight: bold;">Check-out:</td>
                        <td style="padding: 8px 0; border-bottom: 1px solid #e0e0e0;">{{ check_out_formatted }}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; border-bottom: 1px solid #e0e0e0; font-weight: bold;">Duration:</td>
                        <td style="padding: 8px 0; border-bottom: 1px solid #e0e0e0;">{{ nights }} night{% if nights > 1 %}s{% endif %}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; border-bottom: 1px solid #e0e0e0; font-weight: bold;">Room Type:</td>
                        <td style="padding: 8px 0; border-bottom: 1px solid #e0e0e0;">{{ room_type }}{% if room_number %} - Room {{ room_number }}{% endif %}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; font-weight: bold;">Total Amount:</td>
                        <td style="padding: 8px 0; font-size: 18px; font-weight: bold; color: #A57865;">{{ currency }} {{ "%.2f"|format(total_amount) }}</td>
                    </tr>
                </table>
                
                {% if precheckin_url %}
                <div style="background: #f0f9ff; padding: 20px; border-radius: 8px; margin: 30px 0; text-align: center;">
                    <p style="margin: 0 0 15px 0; font-weight: bold; color: #A57865;">Complete Your Pre-Check-In</p>
                    <p style="margin: 0 0 15px 0; color: #666; font-size: 14px;">
                        Save time at check-in by completing your pre-check-in now!
                    </p>
                    <a href="{{ precheckin_url }}" 
                       style="background-color: #A57865; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; display: inline-block; font-weight: bold;">
                        Complete Pre-Check-In
                    </a>
                </div>
                {% endif %}
                
                <div style="background: #fff9e6; padding: 15px; border-radius: 8px; margin: 20px 0;">
                    <p style="margin: 0; font-size: 14px; color: #856404;">
                        <strong>📎 Important:</strong> Your booking confirmation PDF is attached to this email. Please keep it for your records.
                    </p>
                </div>
                
                <h3 style="color: #A57865; margin-top: 30px; margin-bottom: 15px;">What's Next?</h3>
                <ul style="color: #666; padding-left: 20px;">
                    <li>Complete your pre-check-in to expedite your arrival</li>
                    <li>Review your booking details in the attached PDF</li>
                    <li>Contact us if you need to make any changes</li>
                    <li>We look forward to welcoming you!</li>
                </ul>
                
                <hr style="border: none; border-top: 1px solid #e0e0e0; margin: 30px 0;">
                
                <p style="color: #999; font-size: 12px; margin: 0;">
                    If you have any questions or need assistance, please contact our reservations team.<br>
                    This is an automated email. Please do not reply to this message.
                </p>
            </div>
        </body>
        </html>
        """)
        
        # Plain text version
        text_template = Template("""
        Booking Confirmation - Glimmora Hotel
        
        Confirmation Number: {{ booking_number }}
        
        Dear {{ guest_name }},
        
        Thank you for choosing Glimmora Hotel! We're delighted to confirm your reservation.
        
        Booking Details:
        - Check-in: {{ check_in_formatted }}
        - Check-out: {{ check_out_formatted }}
        - Duration: {{ nights }} night{% if nights > 1 %}s{% endif %}
        - Room Type: {{ room_type }}{% if room_number %} - Room {{ room_number }}{% endif %}
        - Total Amount: {{ currency }} {{ "%.2f"|format(total_amount) }}
        
        {% if precheckin_url %}
        Complete Your Pre-Check-In:
        {{ precheckin_url }}
        
        Save time at check-in by completing your pre-check-in now!
        {% endif %}
        
        Your booking confirmation PDF is attached to this email. Please keep it for your records.
        
        If you have any questions or need assistance, please contact our reservations team.
        This is an automated email. Please do not reply to this message.
        """)
        
        html_body = html_template.render(
            booking_number=booking_number,
            guest_name=guest_name,
            check_in_formatted=check_in_formatted,
            check_out_formatted=check_out_formatted,
            nights=nights,
            room_type=room_type,
            room_number=room_number,
            total_amount=total_amount,
            currency=currency,
            precheckin_url=precheckin_url,
        )
        text_body = text_template.render(
            booking_number=booking_number,
            guest_name=guest_name,
            check_in_formatted=check_in_formatted,
            check_out_formatted=check_out_formatted,
            nights=nights,
            room_type=room_type,
            room_number=room_number,
            total_amount=total_amount,
            currency=currency,
            precheckin_url=precheckin_url,
        )
        
        # Prepare attachments
        attachments = []
        if pdf_content:
            attachments.append({
                'filename': f'Booking_Confirmation_{booking_number}.pdf',
                'content': pdf_content
            })
        
        return self.send_email(to_email, subject, html_body, text_body, attachments)

    def send_otp_email(
        self,
        to_email: str,
        otp_code: str,
        user_name: Optional[str] = None,
        purpose: str = "verification",
    ) -> bool:
        """
        Send OTP verification email
        
        Args:
            to_email: Recipient email address
            otp_code: 6-digit OTP code
            user_name: User's name (optional)
            purpose: Purpose of OTP (e.g., 'booking_payment', 'email_verification')
            
        Returns:
            bool: True if email sent successfully, False otherwise
        """
        purpose_text = {
            'booking_payment': 'complete your booking payment',
            'email_verification': 'verify your email address',
        }.get(purpose, 'verify your request')
        
        subject = f"Your Verification Code - Glimmora Hotel"
        
        # HTML email template
        html_template = Template("""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Verification Code</title>
        </head>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, #A57865 0%, #8E6554 100%); padding: 30px; text-align: center; border-radius: 10px 10px 0 0;">
                <h1 style="color: white; margin: 0; font-size: 28px;">Glimmora Hotel</h1>
            </div>
            
            <div style="background: #ffffff; padding: 40px; border: 1px solid #e0e0e0; border-top: none; border-radius: 0 0 10px 10px;">
                <h2 style="color: #A57865; margin-top: 0;">Email Verification Required</h2>
                
                {% if user_name %}
                <p>Hello {{ user_name }},</p>
                {% else %}
                <p>Hello,</p>
                {% endif %}
                
                <p>To {{ purpose_text }}, please use the verification code below:</p>
                
                <div style="text-align: center; margin: 30px 0;">
                    <div style="background: #f0f9ff; border: 2px dashed #A57865; padding: 20px; border-radius: 8px; display: inline-block;">
                        <div style="font-size: 32px; font-weight: bold; color: #A57865; letter-spacing: 8px; font-family: 'Courier New', monospace;">
                            {{ otp_code }}
                        </div>
                    </div>
                </div>
                
                <p style="color: #d32f2f; font-weight: bold;">⚠️ Important Security Information:</p>
                <ul style="color: #666;">
                    <li>This code will expire in 10 minutes</li>
                    <li>Never share this code with anyone</li>
                    <li>If you didn't request this, please ignore this email</li>
                </ul>
                
                <hr style="border: none; border-top: 1px solid #e0e0e0; margin: 30px 0;">
                
                <p style="color: #999; font-size: 12px; margin: 0;">
                    This is an automated email. Please do not reply to this message.<br>
                    If you have any questions, please contact our support team.
                </p>
            </div>
        </body>
        </html>
        """)
        
        # Plain text version
        text_template = Template("""
        Email Verification Required - Glimmora Hotel
        
        {% if user_name %}
        Hello {{ user_name }},
        {% else %}
        Hello,
        {% endif %}
        
        To {{ purpose_text }}, please use the verification code below:
        
        {{ otp_code }}
        
        Important Security Information:
        - This code will expire in 10 minutes
        - Never share this code with anyone
        - If you didn't request this, please ignore this email
        
        This is an automated email. Please do not reply to this message.
        """)
        
        html_body = html_template.render(
            otp_code=otp_code,
            user_name=user_name,
            purpose_text=purpose_text,
        )
        text_body = text_template.render(
            otp_code=otp_code,
            user_name=user_name,
            purpose_text=purpose_text,
        )
        
        return self.send_email(to_email, subject, html_body, text_body)

    def send_precheckin_reminder_email(
        self,
        to_email: str,
        guest_name: str,
        booking_number: str,
        check_in_date: str,
        precheckin_url: str,
    ) -> bool:
        """
        Send pre-checkin reminder email (1 day before check-in)
        
        Args:
            to_email: Recipient email address
            guest_name: Guest's full name
            booking_number: Booking confirmation code
            check_in_date: Check-in date (formatted)
            precheckin_url: URL for pre-checkin (with booking ID)
            
        Returns:
            bool: True if email sent successfully, False otherwise
        """
        subject = f"Pre-Check-In Reminder - Your Stay Starts Tomorrow - Glimmora Hotel"
        
        # HTML email template
        html_template = Template("""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Pre-Check-In Reminder</title>
        </head>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, #A57865 0%, #8E6554 100%); padding: 30px; text-align: center; border-radius: 10px 10px 0 0;">
                <h1 style="color: white; margin: 0; font-size: 28px;">Glimmora Hotel</h1>
            </div>
            
            <div style="background: #ffffff; padding: 40px; border: 1px solid #e0e0e0; border-top: none; border-radius: 0 0 10px 10px;">
                <h2 style="color: #A57865; margin-top: 0;">Your Stay Starts Tomorrow!</h2>
                
                <p>Dear {{ guest_name }},</p>
                
                <p>We're excited to welcome you to Glimmora Hotel tomorrow!</p>
                
                <div style="background: #f0f9ff; padding: 20px; border-radius: 8px; margin: 20px 0;">
                    <p style="margin: 0 0 10px 0; font-weight: bold; color: #A57865;">Booking: {{ booking_number }}</p>
                    <p style="margin: 0; color: #666;">Check-in: {{ check_in_date }}</p>
                </div>
                
                <p style="font-weight: bold; color: #A57865; font-size: 18px; text-align: center; margin: 30px 0;">
                    ⏰ Complete Your Pre-Check-In Now!
                </p>
                
                <p>Save time at check-in by completing your pre-check-in now. This will help us prepare for your arrival and make your check-in process faster and smoother.</p>
                
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{{ precheckin_url }}" 
                       style="background-color: #A57865; color: white; padding: 14px 28px; text-decoration: none; border-radius: 6px; display: inline-block; font-weight: bold; font-size: 16px;">
                        Complete Pre-Check-In
                    </a>
                </div>
                
                <div style="background: #fff9e6; padding: 15px; border-radius: 8px; margin: 20px 0;">
                    <p style="margin: 0; font-size: 14px; color: #856404;">
                        <strong>💡 Tip:</strong> Completing pre-check-in allows you to:
                    </p>
                    <ul style="margin: 10px 0 0 0; padding-left: 20px; color: #856404; font-size: 14px;">
                        <li>Provide your preferences in advance</li>
                        <li>Upload identification documents</li>
                        <li>Expedite your check-in process</li>
                    </ul>
                </div>
                
                <hr style="border: none; border-top: 1px solid #e0e0e0; margin: 30px 0;">
                
                <p style="color: #999; font-size: 12px; margin: 0;">
                    If you have any questions or need assistance, please contact our reservations team.<br>
                    This is an automated email. Please do not reply to this message.
                </p>
            </div>
        </body>
        </html>
        """)
        
        # Plain text version
        text_template = Template("""
        Pre-Check-In Reminder - Glimmora Hotel
        
        Your Stay Starts Tomorrow!
        
        Dear {{ guest_name }},
        
        We're excited to welcome you to Glimmora Hotel tomorrow!
        
        Booking: {{ booking_number }}
        Check-in: {{ check_in_date }}
        
        Complete Your Pre-Check-In Now!
        
        Save time at check-in by completing your pre-check-in now. This will help us prepare for your arrival and make your check-in process faster and smoother.
        
        Pre-Check-In Link: {{ precheckin_url }}
        
        Completing pre-check-in allows you to:
        - Provide your preferences in advance
        - Upload identification documents
        - Expedite your check-in process
        
        If you have any questions or need assistance, please contact our reservations team.
        This is an automated email. Please do not reply to this message.
        """)
        
        html_body = html_template.render(
            guest_name=guest_name,
            booking_number=booking_number,
            check_in_date=check_in_date,
            precheckin_url=precheckin_url,
        )
        text_body = text_template.render(
            guest_name=guest_name,
            booking_number=booking_number,
            check_in_date=check_in_date,
            precheckin_url=precheckin_url,
        )
        
        return self.send_email(to_email, subject, html_body, text_body)

    def send_staff_welcome_email(
        self,
        to_email: str,
        staff_name: str,
        role: str,
        department: str,
        password: str = None,
        work_email: str = None,
    ) -> bool:
        """Send welcome email to new staff member with login credentials.

        Args:
            to_email: Where to deliver the email (personal email preferred).
            work_email: The staff's work/login email. If different from to_email,
                        shown prominently so the staff knows what to log in with.
        """
        # The login email is always the work email; fall back to to_email
        login_email = work_email or to_email
        subject = "Welcome to Glimmora Hotel Team - Your Login Credentials"

        html_template = Template("""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, #A57865 0%, #8E6554 100%); padding: 30px; text-align: center; border-radius: 10px 10px 0 0;">
                <h1 style="color: white; margin: 0; font-size: 28px;">Welcome to Glimmora Hotel</h1>
            </div>

            <div style="background: #ffffff; padding: 40px; border: 1px solid #e0e0e0; border-top: none; border-radius: 0 0 10px 10px;">
                <h2 style="color: #A57865; margin-top: 0;">Welcome Aboard, {{ staff_name }}!</h2>

                <p>We're thrilled to have you join our team at Glimmora Hotel.</p>

                <div style="background: #f0f9ff; padding: 20px; border-radius: 8px; margin: 20px 0;">
                    <p style="margin: 5px 0;"><strong>Role:</strong> {{ role }}</p>
                    <p style="margin: 5px 0;"><strong>Department:</strong> {{ department }}</p>
                </div>

                <h3 style="color: #A57865;">Your Login Credentials</h3>
                <div style="background: #fff3cd; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #ffc107;">
                    <p style="margin: 5px 0;"><strong>Login Email (Work):</strong> {{ login_email }}</p>
                    {% if password %}
                    <p style="margin: 5px 0;"><strong>Temporary Password:</strong> <code style="background: #f8f9fa; padding: 2px 6px; border-radius: 4px;">{{ password }}</code></p>
                    <p style="margin-top: 15px; color: #856404; font-size: 12px;"><em>⚠️ You must change your password on first login. This temporary password expires in 72 hours.</em></p>
                    {% else %}
                    <p style="margin: 5px 0;"><em>Please contact your administrator for your temporary password.</em></p>
                    {% endif %}
                </div>

                <p>Use your <strong>work email</strong> above to log in to the staff portal.</p>

                <p>If you have any questions, please don't hesitate to reach out to your supervisor or HR department.</p>

                <p style="margin-top: 30px;">Best regards,<br>Glimmora Hotel Management</p>
            </div>
        </body>
        </html>
        """)

        text_template = Template("""
        Welcome to Glimmora Hotel Team!

        Welcome Aboard, {{ staff_name }}!

        We're thrilled to have you join our team at Glimmora Hotel.

        Role: {{ role }}
        Department: {{ department }}

        YOUR LOGIN CREDENTIALS:
        Login Email (Work): {{ login_email }}
        {% if password %}Temporary Password: {{ password }}

        You must change your password on first login. This temporary password expires in 72 hours.
        {% else %}Please contact your administrator for your temporary password.
        {% endif %}

        Use your work email above to log in to the staff portal.

        If you have any questions, please don't hesitate to reach out to your supervisor or HR department.

        Best regards,
        Glimmora Hotel Management
        """)

        html_body = html_template.render(
            staff_name=staff_name,
            role=role,
            department=department,
            login_email=login_email,
            password=password,
        )
        text_body = text_template.render(
            staff_name=staff_name,
            role=role,
            department=department,
            login_email=login_email,
            password=password,
        )

        return self.send_email(to_email, subject, html_body, text_body)

    def send_shift_assignment_email(
        self,
        to_email: str,
        staff_name: str,
        shift_date: str,
        shift_type: str,
        start_time: str,
        end_time: str,
    ) -> bool:
        """Send shift assignment notification to staff"""
        subject = f"Shift Assignment - {shift_date} - Glimmora Hotel"

        html_template = Template("""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, #A57865 0%, #8E6554 100%); padding: 30px; text-align: center; border-radius: 10px 10px 0 0;">
                <h1 style="color: white; margin: 0; font-size: 28px;">Shift Assignment</h1>
            </div>

            <div style="background: #ffffff; padding: 40px; border: 1px solid #e0e0e0; border-top: none; border-radius: 0 0 10px 10px;">
                <p>Hello {{ staff_name }},</p>

                <p>You have been assigned a new shift:</p>

                <div style="background: #f0f9ff; border-left: 4px solid #A57865; padding: 20px; margin: 20px 0;">
                    <p style="margin: 5px 0;"><strong>📅 Date:</strong> {{ shift_date }}</p>
                    <p style="margin: 5px 0;"><strong>⏰ Shift:</strong> {{ shift_type | capitalize }}</p>
                    <p style="margin: 5px 0;"><strong>🕐 Time:</strong> {{ start_time }} - {{ end_time }}</p>
                </div>

                <p>Please ensure you arrive on time and are prepared for your shift.</p>

                <p>If you have any conflicts with this schedule, please contact your supervisor immediately.</p>
            </div>
        </body>
        </html>
        """)

        text_template = Template("""
        Shift Assignment - Glimmora Hotel

        Hello {{ staff_name }},

        You have been assigned a new shift:

        Date: {{ shift_date }}
        Shift: {{ shift_type | capitalize }}
        Time: {{ start_time }} - {{ end_time }}

        Please ensure you arrive on time and are prepared for your shift.

        If you have any conflicts with this schedule, please contact your supervisor immediately.
        """)

        html_body = html_template.render(
            staff_name=staff_name,
            shift_date=shift_date,
            shift_type=shift_type,
            start_time=start_time,
            end_time=end_time,
        )
        text_body = text_template.render(
            staff_name=staff_name,
            shift_date=shift_date,
            shift_type=shift_type,
            start_time=start_time,
            end_time=end_time,
        )

        return self.send_email(to_email, subject, html_body, text_body)

    def send_leave_status_email(
        self,
        to_email: str,
        staff_name: str,
        leave_type: str,
        start_date: str,
        end_date: str,
        status: str,
        rejection_reason: Optional[str] = None,
    ) -> bool:
        """Send leave request status notification"""
        status_text = "Approved ✓" if status == "approved" else "Rejected ✗"
        subject = f"Leave Request {status_text} - Glimmora Hotel"

        html_template = Template("""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, {{ '#4E5840' if status == 'approved' else '#d32f2f' }} 0%, {{ '#3d4632' if status == 'approved' else '#b71c1c' }} 100%); padding: 30px; text-align: center; border-radius: 10px 10px 0 0;">
                <h1 style="color: white; margin: 0; font-size: 28px;">Leave Request {{ 'Approved' if status == 'approved' else 'Rejected' }}</h1>
            </div>

            <div style="background: #ffffff; padding: 40px; border: 1px solid #e0e0e0; border-top: none; border-radius: 0 0 10px 10px;">
                <p>Hello {{ staff_name }},</p>

                <p>Your leave request has been <strong>{{ status }}</strong>.</p>

                <div style="background: #f5f5f5; padding: 20px; border-radius: 8px; margin: 20px 0;">
                    <p style="margin: 5px 0;"><strong>Leave Type:</strong> {{ leave_type | capitalize }}</p>
                    <p style="margin: 5px 0;"><strong>From:</strong> {{ start_date }}</p>
                    <p style="margin: 5px 0;"><strong>To:</strong> {{ end_date }}</p>
                </div>

                {% if status == 'rejected' and rejection_reason %}
                <div style="background: #ffebee; padding: 15px; border-radius: 8px; margin: 20px 0;">
                    <p style="margin: 0; color: #c62828;"><strong>Reason:</strong> {{ rejection_reason }}</p>
                </div>
                {% endif %}

                {% if status == 'approved' %}
                <p>Enjoy your time off! Please ensure your tasks are properly handed over before your leave begins.</p>
                {% else %}
                <p>If you have questions about this decision, please contact your supervisor or HR department.</p>
                {% endif %}
            </div>
        </body>
        </html>
        """)

        text_template = Template("""
        Leave Request {{ 'Approved' if status == 'approved' else 'Rejected' }} - Glimmora Hotel

        Hello {{ staff_name }},

        Your leave request has been {{ status }}.

        Leave Type: {{ leave_type | capitalize }}
        From: {{ start_date }}
        To: {{ end_date }}

        {% if status == 'rejected' and rejection_reason %}
        Reason: {{ rejection_reason }}
        {% endif %}

        {% if status == 'approved' %}
        Enjoy your time off! Please ensure your tasks are properly handed over before your leave begins.
        {% else %}
        If you have questions about this decision, please contact your supervisor or HR department.
        {% endif %}
        """)

        html_body = html_template.render(
            staff_name=staff_name,
            leave_type=leave_type,
            start_date=start_date,
            end_date=end_date,
            status=status,
            rejection_reason=rejection_reason,
        )
        text_body = text_template.render(
            staff_name=staff_name,
            leave_type=leave_type,
            start_date=start_date,
            end_date=end_date,
            status=status,
            rejection_reason=rejection_reason,
        )

        return self.send_email(to_email, subject, html_body, text_body)

    def send_staff_message_email(
        self,
        to_email: str,
        staff_name: str,
        subject: str,
        message: str,
        priority: str = "normal",
        sender_name: str = "Management",
    ) -> bool:
        """Send message to staff member"""
        priority_colors = {
            "low": "#4E5840",
            "normal": "#A57865",
            "high": "#CDB261",
            "urgent": "#d32f2f",
        }
        color = priority_colors.get(priority, "#A57865")

        html_template = Template("""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, {{ color }} 0%, {{ color }}dd 100%); padding: 30px; text-align: center; border-radius: 10px 10px 0 0;">
                <h1 style="color: white; margin: 0; font-size: 24px;">{{ email_subject }}</h1>
                {% if priority in ['high', 'urgent'] %}
                <span style="background: white; color: {{ color }}; padding: 4px 12px; border-radius: 12px; font-size: 12px; font-weight: bold; margin-top: 10px; display: inline-block;">{{ priority | upper }} PRIORITY</span>
                {% endif %}
            </div>

            <div style="background: #ffffff; padding: 40px; border: 1px solid #e0e0e0; border-top: none; border-radius: 0 0 10px 10px;">
                <p>Hello {{ staff_name }},</p>

                <div style="background: #f5f5f5; padding: 20px; border-radius: 8px; margin: 20px 0;">
                    {{ message | replace('\n', '<br>') | safe }}
                </div>

                <p style="color: #666; font-size: 14px;">From: {{ sender_name }}</p>
            </div>
        </body>
        </html>
        """)

        text_template = Template("""
        {{ email_subject }}
        {% if priority in ['high', 'urgent'] %}[{{ priority | upper }} PRIORITY]{% endif %}

        Hello {{ staff_name }},

        {{ message }}

        From: {{ sender_name }}
        """)

        html_body = html_template.render(
            email_subject=subject,
            staff_name=staff_name,
            message=message,
            priority=priority,
            color=color,
            sender_name=sender_name,
        )
        text_body = text_template.render(
            email_subject=subject,
            staff_name=staff_name,
            message=message,
            priority=priority,
            sender_name=sender_name,
        )

        full_subject = f"{'[URGENT] ' if priority == 'urgent' else ''}{subject} - Glimmora Hotel"
        return self.send_email(to_email, full_subject, html_body, text_body)

    def send_task_assignment_email(
        self,
        to_email: str,
        staff_name: str,
        task_type: str,
        room_number: str,
        priority: str = "normal",
        notes: Optional[str] = None,
    ) -> bool:
        """Send task assignment notification to staff"""
        subject = f"New Task Assigned: {task_type.capitalize()} - Room {room_number}"

        priority_colors = {
            "low": "#4E5840",
            "normal": "#A57865",
            "high": "#CDB261",
            "urgent": "#d32f2f",
        }
        color = priority_colors.get(priority, "#A57865")

        html_template = Template("""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, {{ color }} 0%, {{ color }}dd 100%); padding: 30px; text-align: center; border-radius: 10px 10px 0 0;">
                <h1 style="color: white; margin: 0; font-size: 24px;">New Task Assigned</h1>
                {% if priority in ['high', 'urgent'] %}
                <span style="background: white; color: {{ color }}; padding: 4px 12px; border-radius: 12px; font-size: 12px; font-weight: bold; margin-top: 10px; display: inline-block;">{{ priority | upper }} PRIORITY</span>
                {% endif %}
            </div>

            <div style="background: #ffffff; padding: 40px; border: 1px solid #e0e0e0; border-top: none; border-radius: 0 0 10px 10px;">
                <p>Hello {{ staff_name }},</p>

                <p>You have been assigned a new task:</p>

                <div style="background: #f0f9ff; border-left: 4px solid {{ color }}; padding: 20px; margin: 20px 0;">
                    <p style="margin: 5px 0;"><strong>📋 Task:</strong> {{ task_type | capitalize }}</p>
                    <p style="margin: 5px 0;"><strong>🚪 Room:</strong> {{ room_number }}</p>
                    <p style="margin: 5px 0;"><strong>⚡ Priority:</strong> {{ priority | capitalize }}</p>
                    {% if notes %}
                    <p style="margin: 10px 0 5px 0;"><strong>📝 Notes:</strong></p>
                    <p style="margin: 5px 0; color: #666;">{{ notes }}</p>
                    {% endif %}
                </div>

                <p>Please complete this task as soon as possible.</p>
            </div>
        </body>
        </html>
        """)

        text_template = Template("""
        New Task Assigned - Glimmora Hotel

        Hello {{ staff_name }},

        You have been assigned a new task:

        Task: {{ task_type | capitalize }}
        Room: {{ room_number }}
        Priority: {{ priority | capitalize }}
        {% if notes %}
        Notes: {{ notes }}
        {% endif %}

        Please complete this task as soon as possible.
        """)

        html_body = html_template.render(
            staff_name=staff_name,
            task_type=task_type,
            room_number=room_number,
            priority=priority,
            color=color,
            notes=notes,
        )
        text_body = text_template.render(
            staff_name=staff_name,
            task_type=task_type,
            room_number=room_number,
            priority=priority,
            notes=notes,
        )

        return self.send_email(to_email, subject, html_body, text_body)

    def send_checkout_reminder_email(
        self,
        to_email: str,
        guest_name: str,
        booking_number: str,
        checkout_date: str,
        checkout_time: str = "11:00 AM",
        room_number: str = "",
    ) -> bool:
        """Send checkout reminder to guest"""
        subject = f"Checkout Reminder - {checkout_date} - Glimmora Hotel"

        html_template = Template("""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, #A57865 0%, #8E6554 100%); padding: 30px; text-align: center; border-radius: 10px 10px 0 0;">
                <h1 style="color: white; margin: 0; font-size: 28px;">Checkout Reminder</h1>
            </div>

            <div style="background: #ffffff; padding: 40px; border: 1px solid #e0e0e0; border-top: none; border-radius: 0 0 10px 10px;">
                <p>Dear {{ guest_name }},</p>

                <p>This is a friendly reminder that your checkout is scheduled for tomorrow.</p>

                <div style="background: #f0f9ff; border-left: 4px solid #A57865; padding: 20px; margin: 20px 0;">
                    <p style="margin: 5px 0;"><strong>📅 Checkout Date:</strong> {{ checkout_date }}</p>
                    <p style="margin: 5px 0;"><strong>⏰ Checkout Time:</strong> {{ checkout_time }}</p>
                    {% if room_number %}
                    <p style="margin: 5px 0;"><strong>🚪 Room:</strong> {{ room_number }}</p>
                    {% endif %}
                    <p style="margin: 5px 0;"><strong>📋 Booking:</strong> {{ booking_number }}</p>
                </div>

                <h3 style="color: #A57865;">Before You Leave</h3>
                <ul style="color: #666;">
                    <li>Please ensure all personal belongings are collected</li>
                    <li>Return room key cards to the front desk</li>
                    <li>Settle any outstanding charges</li>
                    <li>Late checkout may be available upon request</li>
                </ul>

                <p>We hope you enjoyed your stay at Glimmora Hotel. Thank you for choosing us!</p>

                <p style="color: #999; font-size: 12px; margin-top: 30px;">
                    If you need a late checkout or have any questions, please contact our front desk.
                </p>
            </div>
        </body>
        </html>
        """)

        text_template = Template("""
        Checkout Reminder - Glimmora Hotel

        Dear {{ guest_name }},

        This is a friendly reminder that your checkout is scheduled for tomorrow.

        Checkout Date: {{ checkout_date }}
        Checkout Time: {{ checkout_time }}
        {% if room_number %}Room: {{ room_number }}{% endif %}
        Booking: {{ booking_number }}

        Before You Leave:
        - Please ensure all personal belongings are collected
        - Return room key cards to the front desk
        - Settle any outstanding charges
        - Late checkout may be available upon request

        We hope you enjoyed your stay at Glimmora Hotel. Thank you for choosing us!

        If you need a late checkout or have any questions, please contact our front desk.
        """)

        html_body = html_template.render(
            guest_name=guest_name,
            booking_number=booking_number,
            checkout_date=checkout_date,
            checkout_time=checkout_time,
            room_number=room_number,
        )
        text_body = text_template.render(
            guest_name=guest_name,
            booking_number=booking_number,
            checkout_date=checkout_date,
            checkout_time=checkout_time,
            room_number=room_number,
        )

        return self.send_email(to_email, subject, html_body, text_body)

    def send_feedback_request_email(
        self,
        to_email: str,
        guest_name: str,
        booking_number: str,
        feedback_url: str,
    ) -> bool:
        """Send feedback request after checkout"""
        subject = "How Was Your Stay? - Glimmora Hotel"

        html_template = Template("""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, #A57865 0%, #8E6554 100%); padding: 30px; text-align: center; border-radius: 10px 10px 0 0;">
                <h1 style="color: white; margin: 0; font-size: 28px;">We'd Love Your Feedback!</h1>
            </div>

            <div style="background: #ffffff; padding: 40px; border: 1px solid #e0e0e0; border-top: none; border-radius: 0 0 10px 10px;">
                <p>Dear {{ guest_name }},</p>

                <p>Thank you for staying with us at Glimmora Hotel! We hope you had a wonderful experience.</p>

                <p>Your feedback is incredibly valuable to us. It helps us improve our services and ensure that every guest has an exceptional stay.</p>

                <div style="text-align: center; margin: 30px 0;">
                    <a href="{{ feedback_url }}"
                       style="background-color: #A57865; color: white; padding: 14px 28px; text-decoration: none; border-radius: 6px; display: inline-block; font-weight: bold; font-size: 16px;">
                        Share Your Feedback
                    </a>
                </div>

                <p style="text-align: center; color: #666; font-size: 14px;">It only takes a few minutes!</p>

                <hr style="border: none; border-top: 1px solid #e0e0e0; margin: 30px 0;">

                <p style="color: #666; font-size: 14px;">
                    Booking Reference: {{ booking_number }}<br>
                    We hope to welcome you back soon!
                </p>
            </div>
        </body>
        </html>
        """)

        text_template = Template("""
        We'd Love Your Feedback! - Glimmora Hotel

        Dear {{ guest_name }},

        Thank you for staying with us at Glimmora Hotel! We hope you had a wonderful experience.

        Your feedback is incredibly valuable to us. It helps us improve our services and ensure that every guest has an exceptional stay.

        Share Your Feedback: {{ feedback_url }}

        It only takes a few minutes!

        Booking Reference: {{ booking_number }}
        We hope to welcome you back soon!
        """)

        html_body = html_template.render(
            guest_name=guest_name,
            booking_number=booking_number,
            feedback_url=feedback_url,
        )
        text_body = text_template.render(
            guest_name=guest_name,
            booking_number=booking_number,
            feedback_url=feedback_url,
        )

        return self.send_email(to_email, subject, html_body, text_body)

    def send_precheckin_confirmation_email(
        self,
        to_email: str,
        guest_name: str,
        booking_number: str,
        room_number: str,
        room_type: str,
        check_in_date: str,
        check_out_date: str,
        digital_key_id: str,
        qr_code: str,
        qr_image_base64: Optional[str] = None,
    ) -> bool:
        """Send pre-check-in confirmation email with digital key and QR code image"""
        subject = f"Pre-Check-In Complete - Your Digital Key is Ready - Glimmora Hotel"

        # Build QR code display based on whether we have an image
        if qr_image_base64:
            qr_display = f'''
                    <div style="background: white; padding: 20px; border-radius: 12px; display: inline-block; margin-bottom: 15px;">
                        <img src="data:image/png;base64,{qr_image_base64}" alt="Digital Key QR Code" style="width: 200px; height: 200px; display: block; margin: 0 auto;">
                    </div>
                    <p style="margin: 10px 0 0 0; font-size: 14px; color: white; font-weight: bold;">Scan this QR code to verify your booking</p>
                    <div style="background: white; padding: 10px 15px; border-radius: 8px; display: inline-block; margin-top: 10px;">
                        <p style="margin: 0; font-size: 14px; color: #666;">Key ID: <strong style="color: #A57865; font-family: 'Courier New', monospace;">{digital_key_id}</strong></p>
                    </div>'''
        else:
            qr_display = f'''
                    <div style="background: white; padding: 15px; border-radius: 8px; display: inline-block;">
                        <p style="margin: 0 0 10px 0; font-size: 12px; color: #666;">Key ID</p>
                        <p style="margin: 0; font-size: 18px; font-weight: bold; color: #A57865; font-family: 'Courier New', monospace;">{digital_key_id}</p>
                    </div>
                    <p style="color: rgba(255,255,255,0.9); font-size: 12px; margin: 15px 0 0 0;">
                        QR Code: {qr_code}
                    </p>'''

        html_template = Template("""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, #A57865 0%, #8E6554 100%); padding: 30px; text-align: center; border-radius: 10px 10px 0 0;">
                <h1 style="color: white; margin: 0; font-size: 28px;">Glimmora Hotel</h1>
                <p style="color: rgba(255,255,255,0.9); margin: 10px 0 0 0; font-size: 16px;">Pre-Check-In Complete!</p>
            </div>

            <div style="background: #ffffff; padding: 40px; border: 1px solid #e0e0e0; border-top: none; border-radius: 0 0 10px 10px;">
                <div style="background: #f0fff4; border-left: 4px solid #38a169; padding: 15px; margin-bottom: 30px;">
                    <p style="margin: 0; font-size: 18px; font-weight: bold; color: #276749;">
                        ✓ Your digital key is ready!
                    </p>
                </div>

                <p>Dear {{ guest_name }},</p>

                <p>Thank you for completing your pre-check-in! Your room is ready and waiting for you.</p>

                <h3 style="color: #A57865; margin-top: 30px; margin-bottom: 15px;">Your Stay Details</h3>
                <table style="width: 100%; border-collapse: collapse; margin-bottom: 20px;">
                    <tr>
                        <td style="padding: 8px 0; border-bottom: 1px solid #e0e0e0; font-weight: bold; width: 40%;">Booking Number:</td>
                        <td style="padding: 8px 0; border-bottom: 1px solid #e0e0e0;">{{ booking_number }}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; border-bottom: 1px solid #e0e0e0; font-weight: bold;">Room:</td>
                        <td style="padding: 8px 0; border-bottom: 1px solid #e0e0e0;">{{ room_number }} ({{ room_type }})</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; border-bottom: 1px solid #e0e0e0; font-weight: bold;">Check-in:</td>
                        <td style="padding: 8px 0; border-bottom: 1px solid #e0e0e0;">{{ check_in_date }}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; border-bottom: 1px solid #e0e0e0; font-weight: bold;">Check-out:</td>
                        <td style="padding: 8px 0; border-bottom: 1px solid #e0e0e0;">{{ check_out_date }}</td>
                    </tr>
                </table>

                <div style="background: linear-gradient(135deg, #A57865 0%, #8E6554 100%); padding: 25px; border-radius: 12px; margin: 30px 0; text-align: center;">
                    <h3 style="color: white; margin: 0 0 15px 0; font-size: 18px;">🔑 Your Digital Key</h3>
                    {{ qr_display }}
                </div>

                <div style="background: #e8f4f8; padding: 15px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #3182ce;">
                    <p style="margin: 0; font-size: 14px; color: #2c5282;">
                        <strong>🔒 Security Note:</strong> Housekeeping staff may scan this QR code to verify your booking. This ensures only authorized rooms are serviced during your stay.
                    </p>
                </div>

                <h3 style="color: #A57865; margin-top: 30px; margin-bottom: 15px;">What's Next?</h3>
                <ol style="color: #666; padding-left: 20px;">
                    <li style="margin-bottom: 10px;"><strong>Skip the front desk</strong> - Go directly to your room upon arrival</li>
                    <li style="margin-bottom: 10px;"><strong>Use your digital key</strong> - Show this QR code at your room door or to staff</li>
                    <li style="margin-bottom: 10px;"><strong>Enjoy your stay!</strong> - We've prepared everything based on your preferences</li>
                </ol>

                <div style="background: #fff9e6; padding: 15px; border-radius: 8px; margin: 20px 0;">
                    <p style="margin: 0; font-size: 14px; color: #856404;">
                        <strong>💡 Tip:</strong> Take a screenshot of your digital key for easy access when you arrive!
                    </p>
                </div>

                <hr style="border: none; border-top: 1px solid #e0e0e0; margin: 30px 0;">

                <p style="color: #999; font-size: 12px; margin: 0;">
                    If you have any questions or need assistance, please contact our concierge team.<br>
                    We look forward to welcoming you!
                </p>
            </div>
        </body>
        </html>
        """)

        text_template = Template("""
        Pre-Check-In Complete - Glimmora Hotel

        Dear {{ guest_name }},

        Thank you for completing your pre-check-in! Your room is ready and waiting for you.

        YOUR STAY DETAILS
        -----------------
        Booking Number: {{ booking_number }}
        Room: {{ room_number }} ({{ room_type }})
        Check-in: {{ check_in_date }}
        Check-out: {{ check_out_date }}

        YOUR DIGITAL KEY
        ----------------
        Key ID: {{ digital_key_id }}
        QR Code: {{ qr_code }}

        WHAT'S NEXT?
        ------------
        1. Skip the front desk - Go directly to your room upon arrival
        2. Use your digital key - Show this email or use the QR code at your room door
        3. Enjoy your stay! - We've prepared everything based on your preferences

        Tip: Take a screenshot of your digital key for easy access when you arrive!

        If you have any questions or need assistance, please contact our concierge team.
        We look forward to welcoming you!
        """)

        html_body = html_template.render(
            guest_name=guest_name,
            booking_number=booking_number,
            room_number=room_number,
            room_type=room_type,
            check_in_date=check_in_date,
            check_out_date=check_out_date,
            digital_key_id=digital_key_id,
            qr_code=qr_code,
            qr_display=qr_display,
        )
        text_body = text_template.render(
            guest_name=guest_name,
            booking_number=booking_number,
            room_number=room_number,
            room_type=room_type,
            check_in_date=check_in_date,
            check_out_date=check_out_date,
            digital_key_id=digital_key_id,
            qr_code=qr_code,
        )

        return self.send_email(to_email, subject, html_body, text_body)

    def send_checkin_welcome_email(
        self,
        to_email: str,
        guest_name: str,
        booking_number: str,
        room_number: str,
        room_type: str,
        check_in_date: str,
        check_out_date: str,
        nights: int,
        wifi_password: Optional[str] = None,
        amenities: Optional[List[str]] = None,
    ) -> bool:
        """
        Send welcome email when guest checks in at the hotel

        Args:
            to_email: Recipient email address
            guest_name: Guest's full name
            booking_number: Booking confirmation code
            room_number: Assigned room number
            room_type: Type of room
            check_in_date: Check-in date
            check_out_date: Check-out date
            nights: Number of nights staying
            wifi_password: WiFi password (optional)
            amenities: List of amenities available (optional)

        Returns:
            bool: True if email sent successfully, False otherwise
        """
        subject = f"Welcome to Glimmora Hotel, {guest_name.split()[0]}!"

        first_name = guest_name.split()[0] if guest_name else "Valued Guest"

        # WiFi info section
        wifi_section = ""
        if wifi_password:
            wifi_section = f"""
            <div style="background: #e8f4f8; padding: 15px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #3182ce;">
                <p style="margin: 0; font-size: 14px; color: #2c5282;">
                    <strong>WiFi Access</strong><br>
                    Network: Glimmora-Guest<br>
                    Password: <strong style="font-family: 'Courier New', monospace;">{wifi_password}</strong>
                </p>
            </div>
            """

        # Amenities section
        amenities_section = ""
        if amenities:
            amenities_list = "".join([f"<li style='margin-bottom: 5px;'>{a}</li>" for a in amenities])
            amenities_section = f"""
            <div style="margin: 20px 0;">
                <h3 style="color: #A57865; margin-bottom: 10px;">Available Amenities</h3>
                <ul style="color: #666; padding-left: 20px;">{amenities_list}</ul>
            </div>
            """

        html_template = Template("""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, #A57865 0%, #8E6554 100%); padding: 30px; text-align: center; border-radius: 10px 10px 0 0;">
                <h1 style="color: white; margin: 0; font-size: 28px;">Glimmora Hotel</h1>
                <p style="color: rgba(255,255,255,0.9); margin: 10px 0 0 0; font-size: 16px;">Welcome, {{ first_name }}!</p>
            </div>

            <div style="background: #ffffff; padding: 40px; border: 1px solid #e0e0e0; border-top: none; border-radius: 0 0 10px 10px;">
                <div style="background: #f0fff4; border-left: 4px solid #38a169; padding: 15px; margin-bottom: 30px;">
                    <p style="margin: 0; font-size: 18px; font-weight: bold; color: #276749;">
                        You're all checked in!
                    </p>
                </div>

                <p>Dear {{ guest_name }},</p>

                <p>Welcome to Glimmora Hotel! We're delighted to have you with us. Your room is ready and we hope you enjoy your stay.</p>

                <h3 style="color: #A57865; margin-top: 30px; margin-bottom: 15px;">Your Stay Details</h3>
                <table style="width: 100%; border-collapse: collapse; margin-bottom: 20px;">
                    <tr>
                        <td style="padding: 8px 0; border-bottom: 1px solid #e0e0e0; font-weight: bold; width: 40%;">Confirmation:</td>
                        <td style="padding: 8px 0; border-bottom: 1px solid #e0e0e0;">{{ booking_number }}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; border-bottom: 1px solid #e0e0e0; font-weight: bold;">Room:</td>
                        <td style="padding: 8px 0; border-bottom: 1px solid #e0e0e0;">{{ room_number }} ({{ room_type }})</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; border-bottom: 1px solid #e0e0e0; font-weight: bold;">Check-in:</td>
                        <td style="padding: 8px 0; border-bottom: 1px solid #e0e0e0;">{{ check_in_date }}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; border-bottom: 1px solid #e0e0e0; font-weight: bold;">Check-out:</td>
                        <td style="padding: 8px 0; border-bottom: 1px solid #e0e0e0;">{{ check_out_date }}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; border-bottom: 1px solid #e0e0e0; font-weight: bold;">Duration:</td>
                        <td style="padding: 8px 0; border-bottom: 1px solid #e0e0e0;">{{ nights }} night{% if nights > 1 %}s{% endif %}</td>
                    </tr>
                </table>

                {{ wifi_section }}

                {{ amenities_section }}

                <h3 style="color: #A57865; margin-top: 30px; margin-bottom: 15px;">Hotel Services</h3>
                <ul style="color: #666; padding-left: 20px;">
                    <li style="margin-bottom: 8px;"><strong>Front Desk:</strong> Available 24/7 for any assistance</li>
                    <li style="margin-bottom: 8px;"><strong>Room Service:</strong> Dial 0 from your room phone</li>
                    <li style="margin-bottom: 8px;"><strong>Housekeeping:</strong> Daily service between 9 AM - 4 PM</li>
                    <li style="margin-bottom: 8px;"><strong>Concierge:</strong> For dining, tours, and local recommendations</li>
                </ul>

                <div style="background: #fff9e6; padding: 15px; border-radius: 8px; margin: 25px 0;">
                    <p style="margin: 0; font-size: 14px; color: #856404;">
                        <strong>Need anything?</strong> Our team is here to make your stay exceptional. Don't hesitate to reach out!
                    </p>
                </div>

                <hr style="border: none; border-top: 1px solid #e0e0e0; margin: 30px 0;">

                <p style="color: #999; font-size: 12px; margin: 0; text-align: center;">
                    Wishing you a wonderful stay!<br>
                    <strong>The Glimmora Team</strong>
                </p>
            </div>
        </body>
        </html>
        """)

        text_template = Template("""
        Welcome to Glimmora Hotel, {{ first_name }}!

        Dear {{ guest_name }},

        Welcome to Glimmora Hotel! We're delighted to have you with us. Your room is ready and we hope you enjoy your stay.

        YOUR STAY DETAILS
        -----------------
        Confirmation: {{ booking_number }}
        Room: {{ room_number }} ({{ room_type }})
        Check-in: {{ check_in_date }}
        Check-out: {{ check_out_date }}
        Duration: {{ nights }} night{% if nights > 1 %}s{% endif %}

        {% if wifi_password %}
        WIFI ACCESS
        -----------
        Network: Glimmora-Guest
        Password: {{ wifi_password }}
        {% endif %}

        HOTEL SERVICES
        --------------
        - Front Desk: Available 24/7 for any assistance
        - Room Service: Dial 0 from your room phone
        - Housekeeping: Daily service between 9 AM - 4 PM
        - Concierge: For dining, tours, and local recommendations

        Need anything? Our team is here to make your stay exceptional!

        Wishing you a wonderful stay!
        The Glimmora Team
        """)

        html_body = html_template.render(
            first_name=first_name,
            guest_name=guest_name,
            booking_number=booking_number,
            room_number=room_number,
            room_type=room_type,
            check_in_date=check_in_date,
            check_out_date=check_out_date,
            nights=nights,
            wifi_section=wifi_section,
            amenities_section=amenities_section,
        )
        text_body = text_template.render(
            first_name=first_name,
            guest_name=guest_name,
            booking_number=booking_number,
            room_number=room_number,
            room_type=room_type,
            check_in_date=check_in_date,
            check_out_date=check_out_date,
            nights=nights,
            wifi_password=wifi_password,
        )

        return self.send_email(to_email, subject, html_body, text_body)

    def send_checkout_thank_you_email(
        self,
        to_email: str,
        guest_name: str,
        booking_number: str,
        room_number: str,
        room_type: str,
        check_in_date: str,
        check_out_date: str,
        nights_stayed: int,
        total_spent: float,
        currency: str = "INR",
        loyalty_points_earned: int = 0,
        is_vip: bool = False,
        feedback_url: Optional[str] = None,
    ) -> bool:
        """
        Send heartwarming thank you email after guest checkout

        Args:
            to_email: Recipient email address
            guest_name: Guest's full name
            booking_number: Booking confirmation code
            room_number: Room they stayed in
            room_type: Type of room
            check_in_date: Check-in date
            check_out_date: Check-out date
            nights_stayed: Number of nights stayed
            total_spent: Total amount spent
            currency: Currency code
            loyalty_points_earned: Loyalty points earned from this stay
            is_vip: Whether guest is VIP
            feedback_url: URL for leaving feedback

        Returns:
            bool: True if email sent successfully, False otherwise
        """
        subject = f"Thank You for Staying with Us, {guest_name.split()[0]}! 💛 - Glimmora Hotel"

        # Get first name
        first_name = guest_name.split()[0] if guest_name else "Valued Guest"

        # VIP special message
        vip_message = ""
        if is_vip:
            vip_message = """
            <div style="background: linear-gradient(135deg, #FFD700 0%, #FFA500 100%); padding: 20px; border-radius: 10px; margin: 20px 0; text-align: center;">
                <p style="color: #333; margin: 0; font-size: 16px; font-weight: bold;">⭐ VIP Guest Recognition ⭐</p>
                <p style="color: #333; margin: 10px 0 0 0;">Thank you for being a valued VIP member of the Glimmora family!</p>
            </div>
            """

        # Loyalty points message
        loyalty_message = ""
        if loyalty_points_earned > 0:
            loyalty_message = f"""
            <div style="background: #f5f0eb; padding: 15px; border-radius: 8px; margin: 20px 0;">
                <p style="margin: 0; color: #A57865; font-weight: bold;">🎁 You earned {loyalty_points_earned:,} loyalty points from this stay!</p>
                <p style="margin: 5px 0 0 0; color: #666; font-size: 14px;">Save them for future rewards and exclusive perks.</p>
            </div>
            """

        html_template = Template("""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Thank You from Glimmora Hotel</title>
        </head>
        <body style="font-family: 'Georgia', serif; line-height: 1.8; color: #333; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #faf9f7;">
            <!-- Header with warm gradient -->
            <div style="background: linear-gradient(135deg, #A57865 0%, #D4A574 50%, #E8C9A8 100%); padding: 40px 30px; text-align: center; border-radius: 15px 15px 0 0;">
                <h1 style="color: white; margin: 0; font-size: 32px; text-shadow: 1px 1px 2px rgba(0,0,0,0.2);">Glimmora Hotel</h1>
                <p style="color: rgba(255,255,255,0.95); margin: 15px 0 0 0; font-size: 18px; font-style: italic;">& Suites</p>
            </div>

            <!-- Main content -->
            <div style="background: #ffffff; padding: 50px 40px; border: 1px solid #e8e0d8; border-top: none; border-radius: 0 0 15px 15px; box-shadow: 0 4px 15px rgba(0,0,0,0.05);">

                <!-- Warm greeting -->
                <div style="text-align: center; margin-bottom: 35px;">
                    <span style="font-size: 48px;">🌟</span>
                    <h2 style="color: #A57865; margin: 15px 0; font-size: 28px; font-weight: normal;">Thank You, {{ first_name }}!</h2>
                </div>

                {{ vip_message }}

                <p style="font-size: 17px; color: #555; text-align: center; margin-bottom: 30px;">
                    As you begin your journey home, we wanted to take a moment to express our heartfelt gratitude for choosing Glimmora Hotel as your home away from home.
                </p>

                <!-- Stay summary in elegant card -->
                <div style="background: linear-gradient(to right, #faf7f4, #f5f0eb); border-radius: 12px; padding: 25px; margin: 30px 0; border-left: 4px solid #A57865;">
                    <h3 style="color: #A57865; margin: 0 0 20px 0; font-weight: normal; font-size: 18px;">Your Stay at a Glance</h3>
                    <table style="width: 100%; color: #666;">
                        <tr>
                            <td style="padding: 8px 0;"><strong>Confirmation:</strong></td>
                            <td style="padding: 8px 0; text-align: right;">{{ booking_number }}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0;"><strong>Room:</strong></td>
                            <td style="padding: 8px 0; text-align: right;">{{ room_type }} (Room {{ room_number }})</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0;"><strong>Dates:</strong></td>
                            <td style="padding: 8px 0; text-align: right;">{{ check_in_date }} - {{ check_out_date }}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0;"><strong>Duration:</strong></td>
                            <td style="padding: 8px 0; text-align: right;">{{ nights_stayed }} wonderful night{% if nights_stayed > 1 %}s{% endif %}</td>
                        </tr>
                    </table>
                </div>

                {{ loyalty_message }}

                <!-- Heartfelt message -->
                <div style="background: #fff9f5; border-radius: 12px; padding: 30px; margin: 30px 0; text-align: center;">
                    <p style="font-size: 18px; color: #A57865; margin: 0; font-style: italic; line-height: 1.8;">
                        "Every guest who walks through our doors becomes part of the Glimmora family. We hope the memories you've made here will stay with you long after you've gone."
                    </p>
                    <p style="color: #999; margin: 15px 0 0 0; font-size: 14px;">— The Glimmora Team</p>
                </div>

                <!-- We'd love your feedback -->
                {% if feedback_url %}
                <div style="text-align: center; margin: 35px 0;">
                    <p style="color: #666; margin-bottom: 20px;">Your feedback means the world to us. It helps us create even more magical experiences for you and future guests.</p>
                    <a href="{{ feedback_url }}"
                       style="background: linear-gradient(135deg, #A57865 0%, #C49A82 100%); color: white; padding: 16px 35px; text-decoration: none; border-radius: 30px; display: inline-block; font-weight: bold; font-size: 16px; box-shadow: 0 4px 15px rgba(165, 120, 101, 0.3);">
                        Share Your Experience ✨
                    </a>
                </div>
                {% endif %}

                <!-- Until we meet again -->
                <div style="border-top: 1px solid #e8e0d8; margin-top: 40px; padding-top: 30px; text-align: center;">
                    <p style="font-size: 20px; color: #A57865; margin: 0 0 15px 0;">Until We Meet Again...</p>
                    <p style="color: #777; margin: 0; font-size: 15px;">
                        Safe travels, {{ first_name }}! We'll be here, ready to welcome you back with open arms whenever your journey brings you our way again.
                    </p>
                    <p style="margin: 25px 0 0 0; font-size: 28px;">🏨 💛 ✈️</p>
                </div>

                <!-- Contact info -->
                <div style="background: #f9f9f9; border-radius: 8px; padding: 20px; margin-top: 35px; text-align: center;">
                    <p style="margin: 0; color: #888; font-size: 14px;">
                        <strong>Glimmora Hotel & Suites</strong><br>
                        123 Luxury Lane, Paradise City<br>
                        📞 +1 (555) 123-4567 | ✉️ hello@glimmora.com<br>
                        <a href="{{ frontend_url }}" style="color: #A57865; text-decoration: none;">{{ frontend_url }}</a>
                    </p>
                </div>
            </div>

            <!-- Footer -->
            <div style="text-align: center; padding: 25px; color: #aaa; font-size: 12px;">
                <p style="margin: 0;">
                    This is an automated message sent with warmth from Glimmora Hotel.<br>
                    © 2025 Glimmora Hotel & Suites. All rights reserved.
                </p>
            </div>
        </body>
        </html>
        """)

        # Plain text version
        text_template = Template("""
        ═══════════════════════════════════════════════════
                      GLIMMORA HOTEL & SUITES
        ═══════════════════════════════════════════════════

        Thank You, {{ first_name }}! 🌟

        As you begin your journey home, we wanted to take a moment to express our
        heartfelt gratitude for choosing Glimmora Hotel as your home away from home.

        ─────────────────────────────────────────────────
        YOUR STAY AT A GLANCE
        ─────────────────────────────────────────────────
        Confirmation: {{ booking_number }}
        Room: {{ room_type }} (Room {{ room_number }})
        Dates: {{ check_in_date }} - {{ check_out_date }}
        Duration: {{ nights_stayed }} wonderful night{% if nights_stayed > 1 %}s{% endif %}

        {% if loyalty_points_earned > 0 %}
        🎁 You earned {{ loyalty_points_earned }} loyalty points from this stay!
        {% endif %}

        ─────────────────────────────────────────────────

        "Every guest who walks through our doors becomes part of the Glimmora family.
        We hope the memories you've made here will stay with you long after you've gone."

                                        — The Glimmora Team

        {% if feedback_url %}
        ─────────────────────────────────────────────────
        WE'D LOVE YOUR FEEDBACK
        ─────────────────────────────────────────────────
        Share your experience: {{ feedback_url }}
        {% endif %}

        ═══════════════════════════════════════════════════

        Until We Meet Again...

        Safe travels, {{ first_name }}! We'll be here, ready to welcome you back
        with open arms whenever your journey brings you our way again. 🏨💛✈️

        ─────────────────────────────────────────────────
        Glimmora Hotel & Suites
        123 Luxury Lane, Paradise City
        📞 +1 (555) 123-4567 | ✉️ hello@glimmora.com
        🌐 {{ frontend_url }}
        ─────────────────────────────────────────────────
        """)

        html_body = html_template.render(
            first_name=first_name,
            booking_number=booking_number,
            room_number=room_number,
            room_type=room_type,
            check_in_date=check_in_date,
            check_out_date=check_out_date,
            nights_stayed=nights_stayed,
            vip_message=vip_message,
            loyalty_message=loyalty_message,
            feedback_url=feedback_url,
            frontend_url=settings.frontend_url,
        )

        text_body = text_template.render(
            first_name=first_name,
            booking_number=booking_number,
            room_number=room_number,
            room_type=room_type,
            check_in_date=check_in_date,
            check_out_date=check_out_date,
            nights_stayed=nights_stayed,
            loyalty_points_earned=loyalty_points_earned,
            feedback_url=feedback_url,
            frontend_url=settings.frontend_url,
        )

        return self.send_email(to_email, subject, html_body, text_body)

    def send_cancellation_email(
        self,
        to_email: str,
        guest_name: str,
        booking_number: str,
        check_in_date: str,
        check_out_date: str,
        room_type: str,
        cancellation_reason: str = "Guest requested cancellation",
    ) -> bool:
        """
        Send booking cancellation confirmation email.

        Args:
            to_email: Recipient email address
            guest_name: Guest's full name
            booking_number: Booking confirmation code
            check_in_date: Check-in date
            check_out_date: Check-out date
            room_type: Type of room that was booked
            cancellation_reason: Reason for cancellation

        Returns:
            bool: True if email sent successfully, False otherwise
        """
        subject = f"Booking Cancellation Confirmed - {booking_number} - Glimmora Hotel"

        html_template = Template("""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Booking Cancellation</title>
        </head>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, #A57865 0%, #8E6554 100%); padding: 30px; text-align: center; border-radius: 10px 10px 0 0;">
                <h1 style="color: white; margin: 0; font-size: 28px;">Glimmora Hotel</h1>
            </div>

            <div style="background: #ffffff; padding: 40px; border: 1px solid #e0e0e0; border-top: none; border-radius: 0 0 10px 10px;">
                <div style="background: #fff3e0; border-left: 4px solid #ff9800; padding: 15px; margin-bottom: 30px;">
                    <p style="margin: 0; font-size: 16px; color: #e65100;">
                        <strong>Booking Cancelled</strong>
                    </p>
                </div>

                <p>Dear {{ guest_name }},</p>

                <p>This email confirms that your booking has been cancelled.</p>

                <div style="background: #f5f5f5; padding: 20px; border-radius: 8px; margin: 20px 0;">
                    <h3 style="color: #A57865; margin-top: 0;">Cancelled Booking Details</h3>
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr>
                            <td style="padding: 8px 0; color: #666; width: 40%;">Confirmation Number:</td>
                            <td style="padding: 8px 0; font-weight: bold;">{{ booking_number }}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; color: #666;">Room Type:</td>
                            <td style="padding: 8px 0;">{{ room_type }}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; color: #666;">Check-in Date:</td>
                            <td style="padding: 8px 0;">{{ check_in_date }}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; color: #666;">Check-out Date:</td>
                            <td style="padding: 8px 0;">{{ check_out_date }}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; color: #666;">Cancellation Reason:</td>
                            <td style="padding: 8px 0;">{{ cancellation_reason }}</td>
                        </tr>
                    </table>
                </div>

                <p>If you have any questions about this cancellation or would like to make a new reservation, please don't hesitate to contact us.</p>

                <div style="text-align: center; margin: 30px 0;">
                    <a href="{{ frontend_url }}/book"
                       style="background-color: #A57865; color: white; padding: 14px 28px; text-decoration: none; border-radius: 6px; display: inline-block; font-weight: bold;">
                        Book Again
                    </a>
                </div>

                <p>We hope to welcome you at Glimmora Hotel in the future!</p>

                <hr style="border: none; border-top: 1px solid #e0e0e0; margin: 30px 0;">

                <p style="color: #999; font-size: 12px; margin: 0;">
                    If you have any questions, please contact us at hello@glimmora.com or call +1 (555) 123-4567.<br>
                    This is an automated email. Please do not reply to this message.
                </p>
            </div>
        </body>
        </html>
        """)

        text_template = Template("""
        Booking Cancellation Confirmed - Glimmora Hotel

        Dear {{ guest_name }},

        This email confirms that your booking has been cancelled.

        CANCELLED BOOKING DETAILS
        -------------------------
        Confirmation Number: {{ booking_number }}
        Room Type: {{ room_type }}
        Check-in Date: {{ check_in_date }}
        Check-out Date: {{ check_out_date }}
        Cancellation Reason: {{ cancellation_reason }}

        If you have any questions about this cancellation or would like to make a new reservation, please don't hesitate to contact us.

        To make a new booking, visit: {{ frontend_url }}/book

        We hope to welcome you at Glimmora Hotel in the future!

        ─────────────────────────────────────────────────
        Glimmora Hotel & Suites
        Email: hello@glimmora.com
        Phone: +1 (555) 123-4567
        """)

        html_body = html_template.render(
            guest_name=guest_name,
            booking_number=booking_number,
            room_type=room_type,
            check_in_date=check_in_date,
            check_out_date=check_out_date,
            cancellation_reason=cancellation_reason,
            frontend_url=settings.frontend_url,
        )

        text_body = text_template.render(
            guest_name=guest_name,
            booking_number=booking_number,
            room_type=room_type,
            check_in_date=check_in_date,
            check_out_date=check_out_date,
            cancellation_reason=cancellation_reason,
            frontend_url=settings.frontend_url,
        )

        return self.send_email(to_email, subject, html_body, text_body)

    def send_auto_cancellation_email(
        self,
        to_email: str,
        guest_name: str,
        booking_number: str,
        arrival_date: str,
        refund_amount: float,
        refund_percentage: int = 50,
        currency: str = "INR",
    ) -> bool:
        """
        Send auto-cancellation notification with refund information.

        Args:
            to_email: Recipient email address
            guest_name: Guest's full name
            booking_number: Booking confirmation number
            arrival_date: Scheduled arrival date
            refund_amount: Amount being refunded
            refund_percentage: Percentage of original payment refunded
            currency: Currency code

        Returns:
            bool: True if email sent successfully, False otherwise
        """
        subject = "Booking Cancelled - Glimmora Hotel"

        # HTML email template
        html_template = Template("""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Booking Cancelled</title>
        </head>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, #A57865 0%, #8E6554 100%); padding: 30px; text-align: center; border-radius: 10px 10px 0 0;">
                <h1 style="color: white; margin: 0; font-size: 28px;">Glimmora Hotel</h1>
            </div>

            <div style="background: #ffffff; padding: 40px; border: 1px solid #e0e0e0; border-top: none; border-radius: 0 0 10px 10px;">
                <h2 style="color: #d32f2f; margin-top: 0;">Booking Cancelled</h2>

                <p>Dear {{ guest_name }},</p>

                <p>We regret to inform you that your booking has been automatically cancelled because pre-check-in was not completed before the check-in date.</p>

                <div style="background: #f5f5f5; padding: 20px; border-radius: 8px; margin: 20px 0;">
                    <h3 style="color: #A57865; margin-top: 0;">Cancelled Booking Details</h3>
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr>
                            <td style="padding: 8px 0; color: #666;">Confirmation Number:</td>
                            <td style="padding: 8px 0; font-weight: bold;">{{ booking_number }}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; color: #666;">Scheduled Arrival:</td>
                            <td style="padding: 8px 0;">{{ arrival_date }}</td>
                        </tr>
                    </table>
                </div>

                {% if refund_amount > 0 %}
                <div style="background: #e8f5e9; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #4caf50;">
                    <h3 style="color: #2e7d32; margin-top: 0;">Refund Processed</h3>
                    <p style="margin-bottom: 0;">A {{ refund_percentage }}% refund has been processed:</p>
                    <p style="font-size: 24px; font-weight: bold; color: #2e7d32; margin: 10px 0;">
                        {{ currency }} {{ "%.2f"|format(refund_amount) }}
                    </p>
                    <p style="color: #666; font-size: 14px; margin-bottom: 0;">
                        Please allow 5-10 business days for the refund to appear in your account.
                    </p>
                </div>
                {% else %}
                <div style="background: #fff3e0; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #ff9800;">
                    <p style="margin: 0; color: #e65100;">No payment was recorded for this booking, so no refund is applicable.</p>
                </div>
                {% endif %}

                <p>We understand that plans can change, and we'd love to welcome you at Glimmora Hotel in the future.</p>

                <div style="text-align: center; margin: 30px 0;">
                    <a href="{{ frontend_url }}/book"
                       style="background-color: #A57865; color: white; padding: 14px 28px; text-decoration: none; border-radius: 6px; display: inline-block; font-weight: bold;">
                        Book Again
                    </a>
                </div>

                <hr style="border: none; border-top: 1px solid #e0e0e0; margin: 30px 0;">

                <p style="color: #999; font-size: 12px; margin: 0;">
                    If you have any questions about this cancellation or your refund, please contact us at hello@glimmora.com or call +1 (555) 123-4567.
                </p>
            </div>
        </body>
        </html>
        """)

        # Plain text version
        text_template = Template("""
        Booking Cancelled - Glimmora Hotel

        Dear {{ guest_name }},

        We regret to inform you that your booking has been automatically cancelled because pre-check-in was not completed before the check-in date.

        CANCELLED BOOKING DETAILS
        -------------------------
        Confirmation Number: {{ booking_number }}
        Scheduled Arrival: {{ arrival_date }}

        {% if refund_amount > 0 %}
        REFUND PROCESSED
        ----------------
        A {{ refund_percentage }}% refund of {{ currency }} {{ "%.2f"|format(refund_amount) }} has been processed.
        Please allow 5-10 business days for the refund to appear in your account.
        {% else %}
        No payment was recorded for this booking, so no refund is applicable.
        {% endif %}

        We understand that plans can change, and we'd love to welcome you at Glimmora Hotel in the future.

        To make a new booking, visit: {{ frontend_url }}/book

        If you have any questions, please contact us:
        Email: hello@glimmora.com
        Phone: +1 (555) 123-4567

        ─────────────────────────────────────────────────
        Glimmora Hotel & Suites
        """)

        html_body = html_template.render(
            guest_name=guest_name,
            booking_number=booking_number,
            arrival_date=arrival_date,
            refund_amount=refund_amount,
            refund_percentage=refund_percentage,
            currency=currency,
            frontend_url=settings.frontend_url,
        )

        text_body = text_template.render(
            guest_name=guest_name,
            booking_number=booking_number,
            arrival_date=arrival_date,
            refund_amount=refund_amount,
            refund_percentage=refund_percentage,
            currency=currency,
            frontend_url=settings.frontend_url,
        )

        return self.send_email(to_email, subject, html_body, text_body)


    def send_task_accepted_email(
        self,
        to_email: str,
        admin_name: str,
        staff_name: str,
        task_id: int,
        task_type: str,
        room_number: str,
        accepted_at: str,
    ) -> bool:
        """
        Send notification email to admin/supervisor when staff accepts a task.

        Args:
            to_email: Admin/supervisor email
            admin_name: Admin's name
            staff_name: Name of staff who accepted
            task_id: Task ID
            task_type: Type of task
            room_number: Room number
            accepted_at: Time of acceptance
        """
        subject = f"Task #{task_id} Accepted - {task_type.capitalize()} - Room {room_number}"

        html_template = Template("""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, #4E5840 0%, #3d4632 100%); padding: 30px; text-align: center; border-radius: 10px 10px 0 0;">
                <h1 style="color: white; margin: 0; font-size: 24px;">Task Accepted ✓</h1>
            </div>

            <div style="background: #ffffff; padding: 40px; border: 1px solid #e0e0e0; border-top: none; border-radius: 0 0 10px 10px;">
                <p>Hello {{ admin_name }},</p>

                <p>A task has been <strong style="color: #4E5840;">accepted</strong> by a staff member:</p>

                <div style="background: #e8f5e9; border-left: 4px solid #4E5840; padding: 20px; margin: 20px 0;">
                    <p style="margin: 5px 0;"><strong>📋 Task ID:</strong> #{{ task_id }}</p>
                    <p style="margin: 5px 0;"><strong>🔧 Task Type:</strong> {{ task_type | capitalize }}</p>
                    <p style="margin: 5px 0;"><strong>🚪 Room:</strong> {{ room_number }}</p>
                    <p style="margin: 5px 0;"><strong>👤 Accepted By:</strong> {{ staff_name }}</p>
                    <p style="margin: 5px 0;"><strong>⏰ Accepted At:</strong> {{ accepted_at }}</p>
                </div>

                <p>The staff member is now working on this task.</p>
            </div>
        </body>
        </html>
        """)

        text_template = Template("""
        Task Accepted - Glimmora Hotel

        Hello {{ admin_name }},

        A task has been accepted by a staff member:

        Task ID: #{{ task_id }}
        Task Type: {{ task_type | capitalize }}
        Room: {{ room_number }}
        Accepted By: {{ staff_name }}
        Accepted At: {{ accepted_at }}

        The staff member is now working on this task.
        """)

        html_body = html_template.render(
            admin_name=admin_name,
            staff_name=staff_name,
            task_id=task_id,
            task_type=task_type,
            room_number=room_number,
            accepted_at=accepted_at,
        )
        text_body = text_template.render(
            admin_name=admin_name,
            staff_name=staff_name,
            task_id=task_id,
            task_type=task_type,
            room_number=room_number,
            accepted_at=accepted_at,
        )

        return self.send_email(to_email, subject, html_body, text_body)

    def send_task_declined_email(
        self,
        to_email: str,
        admin_name: str,
        staff_name: str,
        task_id: int,
        task_type: str,
        room_number: str,
        decline_reason: str,
        declined_at: str,
        priority: str = "normal",
    ) -> bool:
        """
        Send notification email to admin/supervisor when staff declines a task.

        Args:
            to_email: Admin/supervisor email
            admin_name: Admin's name
            staff_name: Name of staff who declined
            task_id: Task ID
            task_type: Type of task
            room_number: Room number
            decline_reason: Reason for declining
            declined_at: Time of decline
            priority: Task priority
        """
        priority_colors = {
            "low": "#4E5840",
            "normal": "#A57865",
            "high": "#CDB261",
            "urgent": "#d32f2f",
        }
        color = priority_colors.get(priority, "#d32f2f")

        subject = f"[ACTION REQUIRED] Task #{task_id} Declined - {task_type.capitalize()} - Room {room_number}"

        html_template = Template("""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, #d32f2f 0%, #b71c1c 100%); padding: 30px; text-align: center; border-radius: 10px 10px 0 0;">
                <h1 style="color: white; margin: 0; font-size: 24px;">Task Declined ✗</h1>
                <span style="background: white; color: #d32f2f; padding: 4px 12px; border-radius: 12px; font-size: 12px; font-weight: bold; margin-top: 10px; display: inline-block;">ACTION REQUIRED</span>
            </div>

            <div style="background: #ffffff; padding: 40px; border: 1px solid #e0e0e0; border-top: none; border-radius: 0 0 10px 10px;">
                <p>Hello {{ admin_name }},</p>

                <p>A task has been <strong style="color: #d32f2f;">declined</strong> by a staff member and needs to be reassigned:</p>

                <div style="background: #ffebee; border-left: 4px solid #d32f2f; padding: 20px; margin: 20px 0;">
                    <p style="margin: 5px 0;"><strong>📋 Task ID:</strong> #{{ task_id }}</p>
                    <p style="margin: 5px 0;"><strong>🔧 Task Type:</strong> {{ task_type | capitalize }}</p>
                    <p style="margin: 5px 0;"><strong>🚪 Room:</strong> {{ room_number }}</p>
                    <p style="margin: 5px 0;"><strong>⚡ Priority:</strong> <span style="color: {{ color }}; font-weight: bold;">{{ priority | upper }}</span></p>
                    <p style="margin: 5px 0;"><strong>👤 Declined By:</strong> {{ staff_name }}</p>
                    <p style="margin: 5px 0;"><strong>⏰ Declined At:</strong> {{ declined_at }}</p>
                </div>

                <div style="background: #fff3e0; padding: 15px; border-radius: 8px; margin: 20px 0;">
                    <p style="margin: 0; font-weight: bold; color: #e65100;">📝 Reason for Decline:</p>
                    <p style="margin: 10px 0 0 0; color: #666;">{{ decline_reason }}</p>
                </div>

                <p style="font-weight: bold; color: #d32f2f;">This task has been returned to pending status and needs to be reassigned to another staff member.</p>

                <p>Please log in to the admin panel to reassign this task.</p>
            </div>
        </body>
        </html>
        """)

        text_template = Template("""
        [ACTION REQUIRED] Task Declined - Glimmora Hotel

        Hello {{ admin_name }},

        A task has been DECLINED by a staff member and needs to be reassigned:

        Task ID: #{{ task_id }}
        Task Type: {{ task_type | capitalize }}
        Room: {{ room_number }}
        Priority: {{ priority | upper }}
        Declined By: {{ staff_name }}
        Declined At: {{ declined_at }}

        Reason for Decline:
        {{ decline_reason }}

        This task has been returned to pending status and needs to be reassigned to another staff member.

        Please log in to the admin panel to reassign this task.
        """)

        html_body = html_template.render(
            admin_name=admin_name,
            staff_name=staff_name,
            task_id=task_id,
            task_type=task_type,
            room_number=room_number,
            decline_reason=decline_reason,
            declined_at=declined_at,
            priority=priority,
            color=color,
        )
        text_body = text_template.render(
            admin_name=admin_name,
            staff_name=staff_name,
            task_id=task_id,
            task_type=task_type,
            room_number=room_number,
            decline_reason=decline_reason,
            declined_at=declined_at,
            priority=priority,
        )

        return self.send_email(to_email, subject, html_body, text_body)

    def send_booking_modification_email(
        self,
        to_email: str,
        guest_name: str,
        booking_number: str,
        room_type: str,
        original_check_in: str,
        original_check_out: str,
        new_check_in: str,
        new_check_out: str,
        original_total: float,
        new_total: float,
        balance_amount: float,
        currency: str = "INR",
    ) -> bool:
        """
        Send booking modification confirmation email.

        Args:
            to_email: Recipient email address
            guest_name: Guest's full name
            booking_number: Booking confirmation code
            room_type: Type of room booked
            original_check_in: Original check-in date
            original_check_out: Original check-out date
            new_check_in: New check-in date
            new_check_out: New check-out date
            original_total: Original total amount
            new_total: New total amount
            balance_amount: Balance due (positive) or refund (negative)
            currency: Currency code

        Returns:
            bool: True if email sent successfully, False otherwise
        """
        subject = f"Booking Modified - {booking_number} - Glimmora Hotel"

        # Determine balance message
        if balance_amount > 0:
            balance_message = f"<span style='color: #e65100; font-weight: bold;'>Additional payment of {currency} {balance_amount:.2f} required</span>"
            balance_text = f"Additional payment of {currency} {balance_amount:.2f} required"
        elif balance_amount < 0:
            balance_message = f"<span style='color: #2e7d32; font-weight: bold;'>Refund of {currency} {abs(balance_amount):.2f} will be processed</span>"
            balance_text = f"Refund of {currency} {abs(balance_amount):.2f} will be processed"
        else:
            balance_message = "<span style='color: #666;'>No balance change</span>"
            balance_text = "No balance change"

        html_template = Template("""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Booking Modified</title>
        </head>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, #A57865 0%, #8E6554 100%); padding: 30px; text-align: center; border-radius: 10px 10px 0 0;">
                <h1 style="color: white; margin: 0; font-size: 28px;">Glimmora Hotel</h1>
            </div>

            <div style="background: #ffffff; padding: 40px; border: 1px solid #e0e0e0; border-top: none; border-radius: 0 0 10px 10px;">
                <div style="background: #e3f2fd; border-left: 4px solid #2196f3; padding: 15px; margin-bottom: 30px;">
                    <p style="margin: 0; font-size: 16px; color: #1565c0;">
                        <strong>Booking Successfully Modified</strong>
                    </p>
                </div>

                <p>Dear {{ guest_name }},</p>

                <p>Your booking has been successfully modified. Please review the changes below:</p>

                <div style="background: #f5f5f5; padding: 20px; border-radius: 8px; margin: 20px 0;">
                    <h3 style="color: #A57865; margin-top: 0;">Booking Details</h3>
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr>
                            <td style="padding: 8px 0; color: #666; width: 40%;">Confirmation Number:</td>
                            <td style="padding: 8px 0; font-weight: bold;">{{ booking_number }}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; color: #666;">Room Type:</td>
                            <td style="padding: 8px 0;">{{ room_type }}</td>
                        </tr>
                    </table>
                </div>

                <div style="display: flex; gap: 20px; margin: 20px 0;">
                    <div style="flex: 1; background: #ffebee; padding: 15px; border-radius: 8px;">
                        <h4 style="color: #c62828; margin: 0 0 10px 0;">Original Dates</h4>
                        <p style="margin: 5px 0; font-size: 14px;"><strong>Check-in:</strong> {{ original_check_in }}</p>
                        <p style="margin: 5px 0; font-size: 14px;"><strong>Check-out:</strong> {{ original_check_out }}</p>
                        <p style="margin: 10px 0 0 0; font-size: 14px;"><strong>Total:</strong> {{ currency }} {{ original_total }}</p>
                    </div>
                </div>

                <div style="margin: 20px 0;">
                    <div style="background: #e8f5e9; padding: 15px; border-radius: 8px;">
                        <h4 style="color: #2e7d32; margin: 0 0 10px 0;">New Dates</h4>
                        <p style="margin: 5px 0; font-size: 14px;"><strong>Check-in:</strong> {{ new_check_in }}</p>
                        <p style="margin: 5px 0; font-size: 14px;"><strong>Check-out:</strong> {{ new_check_out }}</p>
                        <p style="margin: 10px 0 0 0; font-size: 14px;"><strong>New Total:</strong> {{ currency }} {{ new_total }}</p>
                    </div>
                </div>

                <div style="background: #fff8e1; padding: 20px; border-radius: 8px; margin: 20px 0; text-align: center;">
                    <h3 style="color: #f57c00; margin: 0 0 10px 0;">Balance Summary</h3>
                    <p style="margin: 0; font-size: 18px;">{{ balance_message }}</p>
                </div>

                <p>If you have any questions about these changes, please don't hesitate to contact us.</p>

                <div style="text-align: center; margin: 30px 0;">
                    <a href="{{ frontend_url }}/dashboard"
                       style="background-color: #A57865; color: white; padding: 14px 28px; text-decoration: none; border-radius: 6px; display: inline-block; font-weight: bold;">
                        View My Bookings
                    </a>
                </div>

                <p>We look forward to welcoming you at Glimmora Hotel!</p>

                <hr style="border: none; border-top: 1px solid #e0e0e0; margin: 30px 0;">

                <p style="color: #999; font-size: 12px; margin: 0;">
                    If you have any questions, please contact us at hello@glimmora.com or call +1 (555) 123-4567.<br>
                    This is an automated email. Please do not reply to this message.
                </p>
            </div>
        </body>
        </html>
        """)

        text_template = Template("""
        Booking Modified - Glimmora Hotel

        Dear {{ guest_name }},

        Your booking has been successfully modified. Please review the changes below:

        BOOKING DETAILS
        ---------------
        Confirmation Number: {{ booking_number }}
        Room Type: {{ room_type }}

        ORIGINAL DATES
        Check-in: {{ original_check_in }}
        Check-out: {{ original_check_out }}
        Total: {{ currency }} {{ original_total }}

        NEW DATES
        Check-in: {{ new_check_in }}
        Check-out: {{ new_check_out }}
        New Total: {{ currency }} {{ new_total }}

        BALANCE SUMMARY
        {{ balance_text }}

        If you have any questions about these changes, please don't hesitate to contact us.

        View your bookings at: {{ frontend_url }}/dashboard

        We look forward to welcoming you at Glimmora Hotel!

        ─────────────────────────────────────────────────
        Glimmora Hotel & Suites
        Email: hello@glimmora.com
        Phone: +1 (555) 123-4567
        """)

        html_body = html_template.render(
            guest_name=guest_name,
            booking_number=booking_number,
            room_type=room_type,
            original_check_in=original_check_in,
            original_check_out=original_check_out,
            new_check_in=new_check_in,
            new_check_out=new_check_out,
            original_total=f"{original_total:.2f}",
            new_total=f"{new_total:.2f}",
            balance_message=balance_message,
            currency=currency,
            frontend_url=settings.frontend_url,
        )

        text_body = text_template.render(
            guest_name=guest_name,
            booking_number=booking_number,
            room_type=room_type,
            original_check_in=original_check_in,
            original_check_out=original_check_out,
            new_check_in=new_check_in,
            new_check_out=new_check_out,
            original_total=f"{original_total:.2f}",
            new_total=f"{new_total:.2f}",
            balance_text=balance_text,
            currency=currency,
            frontend_url=settings.frontend_url,
        )

        return self.send_email(to_email, subject, html_body, text_body)


# Global email service instance (will be initialized in main.py)
email_service: Optional[EmailService] = None


def get_email_service() -> EmailService:
    """Get the global email service instance"""
    if email_service is None:
        raise RuntimeError("Email service not initialized. Call init_email_service() first.")
    return email_service


def init_email_service(
    smtp_server: str = "smtp.gmail.com",
    smtp_port: int = 587,
    sender_email: str = "",
    sender_password: str = "",
    use_tls: bool = True,
    resend_api_key: str = "",
    use_resend: bool = False,
    resend_from_email: str = "onboarding@resend.dev",
    brevo_api_key: str = "",
    use_brevo: bool = False,
    brevo_from_email: str = "",
    brevo_from_name: str = "Glimmora Hotel",
):
    """Initialize the global email service"""
    global email_service
    email_service = EmailService(
        smtp_server=smtp_server,
        smtp_port=smtp_port,
        sender_email=sender_email,
        sender_password=sender_password,
        use_tls=use_tls,
        resend_api_key=resend_api_key,
        use_resend=use_resend,
        resend_from_email=resend_from_email,
        brevo_api_key=brevo_api_key,
        use_brevo=use_brevo,
        brevo_from_email=brevo_from_email,
        brevo_from_name=brevo_from_name,
    )
    logger.info("Email service initialized")

