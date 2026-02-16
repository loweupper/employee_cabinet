"""
Telegram notification system for security alerts
Sends formatted alerts to Telegram chat/channel
"""
import asyncio
from typing import Optional
from datetime import datetime
import logging

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError

from core.monitoring.alerts import Alert, AlertSeverity, AlertType

logger = logging.getLogger("app")


class TelegramNotifier:
    """
    Telegram notification system for security alerts
    Sends formatted alerts with emoji and inline buttons
    """
    
    def __init__(self, bot_token: str, chat_id: str):
        """
        Initialize Telegram notifier
        
        Args:
            bot_token: Telegram bot token
            chat_id: Target chat/channel ID
        """
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.bot = Bot(token=bot_token)
        
        logger.info(f"TelegramNotifier initialized for chat: {chat_id}")
    
    async def send_alert(self, alert: Alert) -> bool:
        """
        Send alert to Telegram
        
        Args:
            alert: Alert to send
            
        Returns:
            True if sent successfully, False otherwise
        """
        try:
            # Format message
            message = self._format_alert(alert)
            
            # Create inline keyboard with "Mark as resolved" button
            keyboard = self._create_keyboard(alert)
            
            # Send message
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode="HTML",
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
            
            logger.info({
                "event": "telegram_alert_sent",
                "alert_id": alert.id,
                "alert_type": alert.type.value,
                "severity": alert.severity.value
            })
            
            return True
            
        except TelegramError as e:
            logger.error({
                "event": "telegram_alert_failed",
                "alert_id": alert.id,
                "error": str(e)
            })
            return False
        except Exception as e:
            logger.error({
                "event": "telegram_alert_error",
                "alert_id": alert.id,
                "error": str(e),
                "error_type": type(e).__name__
            })
            return False
    
    def _format_alert(self, alert: Alert) -> str:
        """
        Format alert for Telegram message
        
        Args:
            alert: Alert to format
            
        Returns:
            Formatted message string
        """
        # Get severity emoji
        severity_emoji = self._get_severity_emoji(alert.severity)
        
        # Format timestamp
        time_str = alert.timestamp.strftime('%Y-%m-%d %H:%M:%S')
        
        # Build message
        message = f"""
{severity_emoji} <b>Security Alert</b>

<b>Severity:</b> {alert.severity.value.upper()}
<b>Type:</b> {alert.type.value.replace('_', ' ').title()}
<b>Time:</b> {time_str} UTC

<b>Message:</b>
{alert.message}

<b>Details:</b>
• IP Address: <code>{alert.ip_address}</code>
• User ID: {alert.user_id or 'N/A'}
• Alert ID: <code>{alert.id[:8]}</code>
"""
        
        # Add additional details
        if alert.details:
            for key, value in alert.details.items():
                # Truncate long values
                value_str = str(value)
                if len(value_str) > 100:
                    value_str = value_str[:97] + "..."
                
                message += f"• {key}: {value_str}\n"
        
        return message.strip()
    
    def _get_severity_emoji(self, severity: AlertSeverity) -> str:
        """
        Get emoji for severity level
        
        Args:
            severity: Alert severity
            
        Returns:
            Emoji string
        """
        emojis = {
            AlertSeverity.LOW: "🟢",
            AlertSeverity.MEDIUM: "🟡",
            AlertSeverity.HIGH: "🟠",
            AlertSeverity.CRITICAL: "🔴"
        }
        return emojis.get(severity, "⚠️")
    
    def _create_keyboard(self, alert: Alert) -> InlineKeyboardMarkup:
        """
        Create inline keyboard with action buttons
        
        Args:
            alert: Alert object
            
        Returns:
            InlineKeyboardMarkup
        """
        keyboard = [
            [
                InlineKeyboardButton(
                    "✅ Mark as Resolved",
                    callback_data=f"resolve_alert:{alert.id}"
                )
            ]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    async def send_message(self, text: str) -> bool:
        """
        Send a plain text message to Telegram
        
        Args:
            text: Message text
            
        Returns:
            True if sent successfully
        """
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode="HTML"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False
    
    async def test_connection(self) -> bool:
        """
        Test Telegram bot connection
        
        Returns:
            True if connection successful
        """
        try:
            bot_info = await self.bot.get_me()
            logger.info(f"Telegram bot connected: @{bot_info.username}")
            return True
        except Exception as e:
            logger.error(f"Telegram bot connection failed: {e}")
            return False


# Global instance placeholder
telegram_notifier: Optional[TelegramNotifier] = None


def get_telegram_notifier() -> Optional[TelegramNotifier]:
    """Get the global Telegram notifier instance"""
    return telegram_notifier


async def init_telegram_notifier(bot_token: str, chat_id: str):
    """Initialize the global Telegram notifier"""
    global telegram_notifier
    
    if not bot_token or not chat_id:
        logger.warning("Telegram notifier not initialized: missing bot_token or chat_id")
        return
    
    telegram_notifier = TelegramNotifier(bot_token=bot_token, chat_id=chat_id)
    
    # Test connection
    if await telegram_notifier.test_connection():
        logger.info("Global TelegramNotifier initialized and connected")
    else:
        logger.warning("TelegramNotifier initialized but connection test failed")
