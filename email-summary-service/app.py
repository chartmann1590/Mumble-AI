#!/usr/bin/env python3
"""
Email Summary Service for Mumble AI
Sends daily conversation summaries via email at scheduled times.
"""

import os
import sys
import time
import logging
import smtplib
import psycopg2
import requests
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formatdate
import pytz
from typing import List, Dict, Optional, Tuple

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Environment variables
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = os.getenv('DB_PORT', '5432')
DB_NAME = os.getenv('DB_NAME', 'mumble_ai')
DB_USER = os.getenv('DB_USER', 'mumbleai')
DB_PASSWORD = os.getenv('DB_PASSWORD', 'mumbleai123')
OLLAMA_URL = os.getenv('OLLAMA_URL', 'http://host.docker.internal:11434')

# Check interval (how often to check if we should send email)
CHECK_INTERVAL_SECONDS = int(os.getenv('CHECK_INTERVAL_SECONDS', '60'))  # Check every minute


class EmailSummaryService:
    """Service that sends daily conversation summaries via email"""

    def __init__(self):
        self.db_conn = None
        self.last_check_date = None
        self.connect_db()

    def connect_db(self):
        """Connect to PostgreSQL database"""
        try:
            self.db_conn = psycopg2.connect(
                host=DB_HOST,
                port=DB_PORT,
                dbname=DB_NAME,
                user=DB_USER,
                password=DB_PASSWORD
            )
            logger.info("Connected to database successfully")
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            raise

    def get_db_connection(self):
        """Get database connection, reconnect if necessary"""
        try:
            # Test connection
            with self.db_conn.cursor() as cursor:
                cursor.execute("SELECT 1")
        except (psycopg2.OperationalError, psycopg2.InterfaceError, AttributeError):
            logger.info("Database connection lost, reconnecting...")
            self.connect_db()
        return self.db_conn

    def get_email_settings(self) -> Optional[Dict]:
        """Retrieve email settings from database"""
        try:
            conn = self.get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT smtp_host, smtp_port, smtp_username, smtp_password,
                           smtp_use_tls, smtp_use_ssl, from_email, recipient_email,
                           daily_summary_enabled, summary_time, timezone, last_sent
                    FROM email_settings
                    WHERE id = 1
                """)
                row = cursor.fetchone()

                if not row:
                    logger.warning("No email settings found in database")
                    return None

                return {
                    'smtp_host': row[0],
                    'smtp_port': row[1],
                    'smtp_username': row[2],
                    'smtp_password': row[3],
                    'smtp_use_tls': row[4],
                    'smtp_use_ssl': row[5],
                    'from_email': row[6],
                    'recipient_email': row[7],
                    'daily_summary_enabled': row[8],
                    'summary_time': row[9],
                    'timezone': row[10],
                    'last_sent': row[11]
                }
        except Exception as e:
            logger.error(f"Error getting email settings: {e}")
            return None

    def update_last_sent(self):
        """Update the last_sent timestamp in database"""
        try:
            conn = self.get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE email_settings
                    SET last_sent = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = 1
                """, (datetime.now(),))
            conn.commit()
            logger.info("Updated last_sent timestamp")
        except Exception as e:
            logger.error(f"Error updating last_sent: {e}")
            conn.rollback()

    def should_send_summary(self, settings: Dict) -> bool:
        """Determine if we should send a summary email now"""
        if not settings['daily_summary_enabled']:
            return False

        if not settings['recipient_email']:
            logger.warning("Daily summaries enabled but no recipient email configured")
            return False

        # Get current time in configured timezone
        tz = pytz.timezone(settings['timezone'])
        now = datetime.now(tz)

        # Get the target time today
        target_time = settings['summary_time']
        target_datetime = now.replace(
            hour=target_time.hour,
            minute=target_time.minute,
            second=0,
            microsecond=0
        )

        # Check if we're within the window (current minute matches target minute)
        time_matches = (now.hour == target_time.hour and now.minute == target_time.minute)

        if not time_matches:
            return False

        # Check if we already sent today
        if settings['last_sent']:
            last_sent_date = settings['last_sent'].date()
            today_date = now.date()

            if last_sent_date >= today_date:
                logger.debug("Already sent summary today")
                return False

        logger.info(f"Time to send daily summary! Current time: {now.strftime('%Y-%m-%d %H:%M %Z')}")
        return True

    def get_conversation_history(self, hours: int = 24) -> List[Dict]:
        """Get conversation history from the last N hours"""
        try:
            conn = self.get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT user_name, role, message, timestamp, message_type
                    FROM conversation_history
                    WHERE timestamp >= NOW() - INTERVAL '%s hours'
                    ORDER BY timestamp ASC
                """, (hours,))

                rows = cursor.fetchall()

                conversations = []
                for row in rows:
                    conversations.append({
                        'user_name': row[0],
                        'role': row[1],
                        'message': row[2],
                        'timestamp': row[3],
                        'message_type': row[4]
                    })

                logger.info(f"Retrieved {len(conversations)} messages from last {hours} hours")
                return conversations
        except Exception as e:
            logger.error(f"Error getting conversation history: {e}")
            return []

    def generate_summary_with_ollama(self, conversations: List[Dict]) -> str:
        """Generate a conversation summary using Ollama"""
        if not conversations:
            return "No conversations occurred in the last 24 hours."

        # Format conversations for Ollama
        conversation_text = ""
        for conv in conversations:
            timestamp_str = conv['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
            role = "User" if conv['role'] == 'user' else "Assistant"
            conversation_text += f"[{timestamp_str}] {role} ({conv['user_name']}): {conv['message']}\n\n"

        # Create summary prompt
        summary_prompt = f"""You are summarizing a day's worth of conversations from a Mumble AI voice assistant. Below are all the conversations from the last 24 hours.

Please create a well-organized summary with the following sections:

1. **Overview**: Brief summary of overall activity (number of conversations, unique users, topics discussed)
2. **Key Conversations**: Highlight the most important or interesting exchanges
3. **Persistent Information**: List any schedules, tasks, facts, or preferences that were discussed
4. **Statistics**: Conversation count, most active users, time distribution

Conversations:
{conversation_text}

Generate a comprehensive but concise summary in markdown format:"""

        try:
            logger.info("Generating summary with Ollama...")

            # Get Ollama model from database
            conn = self.get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute("SELECT value FROM bot_config WHERE key = 'ollama_model'")
                row = cursor.fetchone()
                ollama_model = row[0] if row else 'llama3.2:latest'

            response = requests.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    'model': ollama_model,
                    'prompt': summary_prompt,
                    'stream': False,
                    'options': {
                        'temperature': 0.5,
                        'num_predict': 1000
                    }
                },
                timeout=120
            )

            if response.status_code == 200:
                result = response.json()
                summary = result.get('response', '').strip()
                logger.info("Summary generated successfully")
                return summary
            else:
                logger.error(f"Ollama request failed with status {response.status_code}")
                return self._generate_fallback_summary(conversations)

        except Exception as e:
            logger.error(f"Error generating summary with Ollama: {e}")
            return self._generate_fallback_summary(conversations)

    def _generate_fallback_summary(self, conversations: List[Dict]) -> str:
        """Generate a basic summary without Ollama"""
        total_messages = len(conversations)
        users = set(conv['user_name'] for conv in conversations)
        user_count = len(users)

        summary = f"""# Daily Conversation Summary

## Overview
- **Total Messages**: {total_messages}
- **Unique Users**: {user_count}
- **Users**: {', '.join(users)}

## Recent Conversations
"""

        # Show last 10 exchanges
        recent = conversations[-20:] if len(conversations) > 20 else conversations
        for conv in recent:
            timestamp_str = conv['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
            role = "👤 User" if conv['role'] == 'user' else "🤖 Assistant"
            summary += f"\n**[{timestamp_str}] {role} ({conv['user_name']})**:\n{conv['message']}\n"

        return summary

    def format_html_email(self, summary: str, date_range: str) -> str:
        """Convert markdown summary to HTML email"""
        # Simple markdown to HTML conversion
        html = summary

        # Convert headers
        html = html.replace('# ', '<h1>').replace('\n## ', '</h1>\n<h2>').replace('\n### ', '</h2>\n<h3>')

        # Bold
        import re
        html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)

        # Lists
        html = re.sub(r'^\- (.+)$', r'<li>\1</li>', html, flags=re.MULTILINE)

        # Line breaks
        html = html.replace('\n\n', '</p><p>')

        # Wrap in HTML template
        html_email = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{
            font-family: Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f4f4f4;
        }}
        .email-container {{
            background-color: white;
            border-radius: 8px;
            padding: 30px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #2c3e50;
            border-bottom: 3px solid #3498db;
            padding-bottom: 10px;
        }}
        h2 {{
            color: #34495e;
            margin-top: 25px;
            border-bottom: 1px solid #ecf0f1;
            padding-bottom: 5px;
        }}
        h3 {{
            color: #7f8c8d;
        }}
        p {{
            margin: 10px 0;
        }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 8px 8px 0 0;
            margin: -30px -30px 20px -30px;
        }}
        .footer {{
            margin-top: 30px;
            padding-top: 20px;
            border-top: 1px solid #ecf0f1;
            color: #7f8c8d;
            font-size: 0.9em;
            text-align: center;
        }}
        .stats {{
            background-color: #ecf0f1;
            padding: 15px;
            border-radius: 5px;
            margin: 15px 0;
        }}
        strong {{
            color: #2c3e50;
        }}
    </style>
</head>
<body>
    <div class="email-container">
        <div class="header">
            <h1 style="margin: 0; border: none; color: white;">🤖 Mumble AI Daily Summary</h1>
            <p style="margin: 5px 0 0 0; opacity: 0.9;">{date_range}</p>
        </div>

        {html}

        <div class="footer">
            <p>This is an automated summary from your Mumble AI assistant.</p>
            <p>You can manage email settings at your <a href="http://localhost:5002">Web Control Panel</a></p>
        </div>
    </div>
</body>
</html>
"""
        return html_email

    def send_email(self, settings: Dict, subject: str, html_content: str, plain_content: str) -> bool:
        """Send email via SMTP"""
        try:
            # Create message
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = settings['from_email']
            msg['To'] = settings['recipient_email']
            msg['Date'] = formatdate(localtime=True)

            # Attach plain text and HTML versions
            part1 = MIMEText(plain_content, 'plain', 'utf-8')
            part2 = MIMEText(html_content, 'html', 'utf-8')
            msg.attach(part1)
            msg.attach(part2)

            # Connect to SMTP server
            logger.info(f"Connecting to SMTP server {settings['smtp_host']}:{settings['smtp_port']}")

            if settings['smtp_use_ssl']:
                smtp = smtplib.SMTP_SSL(settings['smtp_host'], settings['smtp_port'], timeout=30)
            else:
                smtp = smtplib.SMTP(settings['smtp_host'], settings['smtp_port'], timeout=30)
                if settings['smtp_use_tls']:
                    smtp.starttls()

            # Login if credentials provided
            if settings['smtp_username'] and settings['smtp_password']:
                logger.info(f"Logging in as {settings['smtp_username']}")
                smtp.login(settings['smtp_username'], settings['smtp_password'])

            # Send email
            smtp.send_message(msg)
            smtp.quit()

            logger.info(f"Email sent successfully to {settings['recipient_email']}")
            return True

        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False

    def send_daily_summary(self, settings: Dict):
        """Generate and send daily summary email"""
        logger.info("Starting daily summary generation...")

        # Get conversation history
        conversations = self.get_conversation_history(hours=24)

        # Generate summary
        summary = self.generate_summary_with_ollama(conversations)

        # Format date range
        now = datetime.now(pytz.timezone(settings['timezone']))
        yesterday = now - timedelta(days=1)
        date_range = f"{yesterday.strftime('%B %d, %Y')} - {now.strftime('%B %d, %Y')}"

        # Create email content
        subject = f"Mumble AI Daily Summary - {now.strftime('%B %d, %Y')}"
        html_content = self.format_html_email(summary, date_range)
        plain_content = f"Mumble AI Daily Summary\n{date_range}\n\n{summary}"

        # Send email
        success = self.send_email(settings, subject, html_content, plain_content)

        if success:
            # Update last_sent timestamp
            self.update_last_sent()
            logger.info("Daily summary completed successfully")
        else:
            logger.error("Failed to send daily summary")

    def send_test_email(self, settings: Dict) -> bool:
        """Send a test email"""
        logger.info("Sending test email...")

        # Get a few recent conversations for the test
        conversations = self.get_conversation_history(hours=24)

        if conversations:
            summary = f"# Test Email Summary\n\nThis is a test email from Mumble AI.\n\n**Recent activity**: {len(conversations)} messages in the last 24 hours."
        else:
            summary = "# Test Email Summary\n\nThis is a test email from Mumble AI.\n\nNo recent conversations to display."

        date_range = datetime.now(pytz.timezone(settings['timezone'])).strftime('%B %d, %Y')
        subject = f"[TEST] Mumble AI Summary - {date_range}"
        html_content = self.format_html_email(summary, date_range)
        plain_content = f"Test Email from Mumble AI\n\n{summary}"

        return self.send_email(settings, subject, html_content, plain_content)

    def run(self):
        """Main service loop"""
        logger.info("Email Summary Service started")
        logger.info(f"Checking every {CHECK_INTERVAL_SECONDS} seconds for scheduled emails")

        while True:
            try:
                # Get email settings
                settings = self.get_email_settings()

                if settings and self.should_send_summary(settings):
                    self.send_daily_summary(settings)

                # Sleep before next check
                time.sleep(CHECK_INTERVAL_SECONDS)

            except KeyboardInterrupt:
                logger.info("Service stopped by user")
                break
            except Exception as e:
                logger.error(f"Error in main loop: {e}", exc_info=True)
                time.sleep(CHECK_INTERVAL_SECONDS)

        # Close database connection
        if self.db_conn:
            self.db_conn.close()
            logger.info("Database connection closed")


if __name__ == '__main__':
    service = EmailSummaryService()
    service.run()
