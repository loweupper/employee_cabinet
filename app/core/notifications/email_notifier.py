"""
Email notification system for security alerts
Sends emails for HIGH and CRITICAL alerts with rate limiting
"""
import asyncio
from typing import List, Dict, Optional
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
import aiosmtplib
import logging
from collections import defaultdict

from core.monitoring.alerts import Alert, AlertSeverity, AlertType

logger = logging.getLogger("app")


class EmailNotifier:
    """
    Email notification system for security alerts
    Includes rate limiting to avoid spam
    """
    
    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        username: str,
        password: str,
        from_email: str,
        from_name: str = "Employee Cabinet Security"
    ):
        """
        Initialize email notifier
        
        Args:
            smtp_host: SMTP server hostname
            smtp_port: SMTP server port
            username: SMTP username
            password: SMTP password
            from_email: From email address
            from_name: From name
        """
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.from_email = from_email
        self.from_name = from_name
        
        # Rate limiting: track last send time per alert type
        self._last_sent: Dict[str, datetime] = {}
        self._rate_limit_minutes = 10
        
        # Failed email queue for retry
        self._failed_queue: List[tuple] = []
        
        logger.info(f"EmailNotifier initialized: {smtp_host}:{smtp_port}")
    
    async def send_alert(self, alert: Alert, recipients: List[str]) -> bool:
        """
        Send alert via email with rate limiting
        
        Args:
            alert: Alert to send
            recipients: List of recipient email addresses
            
        Returns:
            True if sent successfully, False otherwise
        """
        # Check severity - only send HIGH and CRITICAL
        if alert.severity not in [AlertSeverity.HIGH, AlertSeverity.CRITICAL]:
            logger.debug(f"Skipping email for {alert.severity.value} severity alert")
            return True
        
        # Check rate limiting
        if not self._should_send(alert.type.value):
            logger.info(f"Rate limit: Skipping email for {alert.type.value} (sent recently)")
            return True
        
        try:
            # Create email
            message = self._create_message(alert, recipients)
            
            # Send email
            await self._send_email(message)
            
            # Update rate limit tracker
            self._last_sent[alert.type.value] = datetime.utcnow()
            
            logger.info({
                "event": "alert_email_sent",
                "alert_id": alert.id,
                "alert_type": alert.type.value,
                "recipients": len(recipients),
                "severity": alert.severity.value
            })
            
            return True
            
        except Exception as e:
            logger.error({
                "event": "alert_email_failed",
                "alert_id": alert.id,
                "error": str(e)
            })
            
            # Queue for retry
            self._failed_queue.append((alert, recipients))
            
            return False
    
    def _should_send(self, alert_type: str) -> bool:
        """
        Check if we should send email based on rate limit
        
        Args:
            alert_type: Type of alert
            
        Returns:
            True if should send, False if rate limited
        """
        last_sent = self._last_sent.get(alert_type)
        
        if not last_sent:
            return True
        
        elapsed = datetime.utcnow() - last_sent
        return elapsed > timedelta(minutes=self._rate_limit_minutes)
    
    def _create_message(self, alert: Alert, recipients: List[str]) -> MIMEMultipart:
        """
        Create email message for alert
        
        Args:
            alert: Alert to format
            recipients: Recipient email addresses
            
        Returns:
            MIME message
        """
        message = MIMEMultipart("alternative")
        message["Subject"] = f"🚨 Security Alert: {alert.type.value.replace('_', ' ').title()}"
        message["From"] = f"{self.from_name} <{self.from_email}>"
        message["To"] = ", ".join(recipients)
        
        # Create HTML and text versions
        text_content = self._format_alert_text(alert)
        html_content = self._format_alert_html(alert)
        
        # Attach parts
        message.attach(MIMEText(text_content, "plain"))
        message.attach(MIMEText(html_content, "html"))
        
        return message
    
    def _format_alert_text(self, alert: Alert) -> str:
        """
        Format alert as plain text email
        
        Args:
            alert: Alert to format
            
        Returns:
            Plain text content
        """
        severity_icon = self._get_severity_icon(alert.severity)
        
        text = f"""
{severity_icon} Security Alert

Severity: {alert.severity.value.upper()}
Type: {alert.type.value.replace('_', ' ').title()}
Time: {alert.timestamp.strftime('%Y-%m-%d %H:%M:%S')} UTC

Message:
{alert.message}

Details:
IP Address: {alert.ip_address}
User ID: {alert.user_id or 'N/A'}
Alert ID: {alert.id}

Additional Information:
"""
        
        for key, value in alert.details.items():
            text += f"  {key}: {value}\n"
        
        text += f"""

---
This is an automated security alert from Employee Cabinet.
Please investigate this incident immediately.
"""
        
        return text
    
    def _format_alert_html(self, alert: Alert) -> str:
        """
        Format alert as HTML email
        
        Args:
            alert: Alert to format
            
        Returns:
            HTML content
        """
        severity_icon = self._get_severity_icon(alert.severity)
        severity_color = self._get_severity_color(alert.severity)
        
        details_html = ""
        for key, value in alert.details.items():
            details_html += f"<tr><td><strong>{key}:</strong></td><td>{value}</td></tr>"
        
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background-color: {severity_color}; color: white; padding: 20px; border-radius: 5px 5px 0 0; }}
        .content {{ background-color: #f9f9f9; padding: 20px; border: 1px solid #ddd; border-radius: 0 0 5px 5px; }}
        .alert-info {{ background-color: white; padding: 15px; margin: 10px 0; border-left: 4px solid {severity_color}; }}
        .details {{ margin-top: 15px; }}
        table {{ width: 100%; border-collapse: collapse; }}
        td {{ padding: 5px; }}
        .footer {{ text-align: center; margin-top: 20px; font-size: 12px; color: #666; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>{severity_icon} Security Alert</h1>
            <p style="margin: 0; font-size: 14px;">Severity: {alert.severity.value.upper()}</p>
        </div>
        <div class="content">
            <div class="alert-info">
                <h2>{alert.type.value.replace('_', ' ').title()}</h2>
                <p><strong>Time:</strong> {alert.timestamp.strftime('%Y-%m-%d %H:%M:%S')} UTC</p>
                <p><strong>Message:</strong> {alert.message}</p>
            </div>
            
            <div class="details">
                <h3>Details</h3>
                <table>
                    <tr><td><strong>IP Address:</strong></td><td>{alert.ip_address}</td></tr>
                    <tr><td><strong>User ID:</strong></td><td>{alert.user_id or 'N/A'}</td></tr>
                    <tr><td><strong>Alert ID:</strong></td><td>{alert.id}</td></tr>
                    {details_html}
                </table>
            </div>
        </div>
        <div class="footer">
            <p>This is an automated security alert from Employee Cabinet.<br>
            Please investigate this incident immediately.</p>
        </div>
    </div>
</body>
</html>
"""
        return html
    
    def _get_severity_icon(self, severity: AlertSeverity) -> str:
        """Get emoji icon for severity"""
        icons = {
            AlertSeverity.LOW: "🟢",
            AlertSeverity.MEDIUM: "🟡",
            AlertSeverity.HIGH: "🟠",
            AlertSeverity.CRITICAL: "🔴"
        }
        return icons.get(severity, "⚠️")
    
    def _get_severity_color(self, severity: AlertSeverity) -> str:
        """Get color for severity"""
        colors = {
            AlertSeverity.LOW: "#28a745",
            AlertSeverity.MEDIUM: "#ffc107",
            AlertSeverity.HIGH: "#fd7e14",
            AlertSeverity.CRITICAL: "#dc3545"
        }
        return colors.get(severity, "#6c757d")
    
    async def _send_email(self, message: MIMEMultipart):
        """
        Send email via SMTP
        
        Args:
            message: MIME message to send
        """
        async with aiosmtplib.SMTP(
            hostname=self.smtp_host,
            port=self.smtp_port,
            use_tls=False,
            start_tls=True
        ) as smtp:
            await smtp.login(self.username, self.password)
            await smtp.send_message(message)
    
    async def retry_failed(self) -> int:
        """
        Retry sending failed emails
        
        Returns:
            Number of successfully retried emails
        """
        if not self._failed_queue:
            return 0
        
        retry_count = 0
        failed_again = []
        
        for alert, recipients in self._failed_queue:
            try:
                message = self._create_message(alert, recipients)
                await self._send_email(message)
                retry_count += 1
                
                logger.info({
                    "event": "alert_email_retry_success",
                    "alert_id": alert.id
                })
            except Exception as e:
                logger.error({
                    "event": "alert_email_retry_failed",
                    "alert_id": alert.id,
                    "error": str(e)
                })
                failed_again.append((alert, recipients))
        
        # Update failed queue
        self._failed_queue = failed_again
        
        return retry_count


# Global instance placeholder
email_notifier: Optional[EmailNotifier] = None


def get_email_notifier() -> Optional[EmailNotifier]:
    """Get the global email notifier instance"""
    return email_notifier


async def init_email_notifier(
    smtp_host: str,
    smtp_port: int,
    username: str,
    password: str,
    from_email: str,
    from_name: str = "Employee Cabinet Security"
):
    """Initialize the global email notifier"""
    global email_notifier
    email_notifier = EmailNotifier(
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        username=username,
        password=password,
        from_email=from_email,
        from_name=from_name
    )
    logger.info("Global EmailNotifier initialized")
