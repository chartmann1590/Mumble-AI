#!/usr/bin/env python3
"""
Email Summary Service for Mumble AI
Sends daily conversation summaries via email at scheduled times.
Receives and replies to emails using AI.
"""

import os
import sys
import time
import logging
import smtplib
import psycopg2
import requests
import imaplib
import email
from email import policy
from email.parser import BytesParser
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formatdate, parseaddr
import pytz
from typing import List, Dict, Optional, Tuple
import re
import threading

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
                           daily_summary_enabled, summary_time, timezone, last_sent,
                           imap_enabled, imap_host, imap_port, imap_username, imap_password,
                           imap_use_ssl, imap_mailbox, auto_reply_enabled, reply_signature,
                           check_interval_seconds, last_checked
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
                    'last_sent': row[11],
                    'imap_enabled': row[12],
                    'imap_host': row[13],
                    'imap_port': row[14],
                    'imap_username': row[15],
                    'imap_password': row[16],
                    'imap_use_ssl': row[17],
                    'imap_mailbox': row[18] or 'INBOX',
                    'auto_reply_enabled': row[19],
                    'reply_signature': row[20] or '',
                    'check_interval_seconds': row[21] or 300,
                    'last_checked': row[22]
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

    def get_schedule_events(self, days_ahead: int = 7) -> List[Dict]:
        """Get upcoming schedule events"""
        try:
            conn = self.get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT user_name, title, event_date, event_time, description, importance, created_at
                    FROM schedule_events
                    WHERE active = TRUE
                      AND event_date >= CURRENT_DATE
                      AND event_date <= CURRENT_DATE + INTERVAL '%s days'
                    ORDER BY event_date, event_time
                """, (days_ahead,))

                rows = cursor.fetchall()

                events = []
                for row in rows:
                    events.append({
                        'user_name': row[0],
                        'title': row[1],
                        'event_date': row[2],
                        'event_time': row[3],
                        'description': row[4],
                        'importance': row[5],
                        'created_at': row[6]
                    })

                logger.info(f"Retrieved {len(events)} upcoming events")
                return events
        except Exception as e:
            logger.error(f"Error getting schedule events: {e}")
            return []

    def get_schedule_changes(self, hours: int = 24) -> List[Dict]:
        """Get schedule events created or modified in the last N hours"""
        try:
            conn = self.get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT user_name, title, event_date, event_time, description, importance, created_at
                    FROM schedule_events
                    WHERE active = TRUE
                      AND created_at >= NOW() - INTERVAL '%s hours'
                    ORDER BY created_at DESC
                """, (hours,))

                rows = cursor.fetchall()

                changes = []
                for row in rows:
                    changes.append({
                        'user_name': row[0],
                        'title': row[1],
                        'event_date': row[2],
                        'event_time': row[3],
                        'description': row[4],
                        'importance': row[5],
                        'created_at': row[6]
                    })

                logger.info(f"Retrieved {len(changes)} schedule changes from last {hours} hours")
                return changes
        except Exception as e:
            logger.error(f"Error getting schedule changes: {e}")
            return []

    def get_recent_memories(self, hours: int = 24) -> List[Dict]:
        """Get persistent memories created in the last N hours"""
        try:
            conn = self.get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT user_name, category, content, importance, extracted_at, event_date, event_time
                    FROM persistent_memories
                    WHERE active = TRUE
                      AND extracted_at >= NOW() - INTERVAL '%s hours'
                    ORDER BY importance DESC, extracted_at DESC
                """, (hours,))

                rows = cursor.fetchall()

                memories = []
                for row in rows:
                    memories.append({
                        'user_name': row[0],
                        'category': row[1],
                        'content': row[2],
                        'importance': row[3],
                        'extracted_at': row[4],
                        'event_date': row[5],
                        'event_time': row[6]
                    })

                logger.info(f"Retrieved {len(memories)} memories from last {hours} hours")
                return memories
        except Exception as e:
            logger.error(f"Error getting recent memories: {e}")
            return []

    def generate_summary_with_ollama(self, conversations: List[Dict], schedule_events: List[Dict],
                                     schedule_changes: List[Dict], memories: List[Dict]) -> str:
        """Generate a conversation summary using Ollama"""
        if not conversations and not schedule_changes and not memories:
            return "No activity in the last 24 hours."

        # Format conversations for Ollama
        conversation_text = ""
        if conversations:
            for conv in conversations:
                timestamp_str = conv['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
                role = "User" if conv['role'] == 'user' else "Assistant"
                conversation_text += f"[{timestamp_str}] {role} ({conv['user_name']}): {conv['message']}\n\n"
        else:
            conversation_text = "No conversations in the last 24 hours.\n\n"

        # Format schedule changes
        schedule_text = ""
        if schedule_changes:
            schedule_text = "**Schedule Changes Made:**\n"
            for event in schedule_changes:
                date_str = event['event_date'].strftime('%A, %B %d, %Y')
                time_str = event['event_time'].strftime('%I:%M %p') if event['event_time'] else 'All day'
                schedule_text += f"- {event['title']} - {date_str} at {time_str} (Added by {event['user_name']})\n"
            schedule_text += "\n"

        # Format upcoming events
        upcoming_text = ""
        if schedule_events:
            upcoming_text = "**Upcoming Events (Next 7 Days):**\n"
            for event in schedule_events:
                date_str = event['event_date'].strftime('%A, %B %d, %Y')
                time_str = event['event_time'].strftime('%I:%M %p') if event['event_time'] else 'All day'
                upcoming_text += f"- {event['title']} - {date_str} at {time_str} ({event['user_name']})\n"
            upcoming_text += "\n"

        # Format memories
        memory_text = ""
        if memories:
            memory_text = "**New Memories Extracted:**\n"
            category_icons = {'schedule': '📅', 'fact': '💡', 'task': '✓', 'preference': '❤️', 'reminder': '⏰', 'other': '📌'}
            for mem in memories:
                icon = category_icons.get(mem['category'], '📌')
                memory_text += f"- {icon} [{mem['category'].upper()}] {mem['content']} ({mem['user_name']})\n"
            memory_text += "\n"

        # Create summary prompt
        summary_prompt = f"""You are summarizing a day's worth of activity from a Mumble AI voice assistant. Create a well-organized, friendly summary.

{schedule_text}{upcoming_text}{memory_text}

Conversations from the last 24 hours:
{conversation_text}

Create a comprehensive summary with these sections:
1. **Overview**: Brief summary of overall activity
2. **Highlights**: Most important conversations or events
3. **New Information**: Any new schedules, tasks, facts, or preferences learned

Keep it concise and friendly. Use markdown formatting:"""

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

    def format_html_email(self, summary: str, date_range: str, schedule_events: List[Dict],
                          schedule_changes: List[Dict], memories: List[Dict]) -> str:
        """Convert markdown summary to HTML email"""
        import re

        # Convert markdown to HTML
        html = summary
        html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
        html = re.sub(r'^# (.+)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
        html = re.sub(r'^## (.+)$', r'<h3>\1</h3>', html, flags=re.MULTILINE)
        html = re.sub(r'^\- (.+)$', r'<li>\1</li>', html, flags=re.MULTILINE)
        html = html.replace('\n\n', '</p><p>')
        html = f'<p>{html}</p>'

        # Build schedule events HTML
        schedule_html = ""
        if schedule_events:
            schedule_html = '<div class="section-card schedule-section">'
            schedule_html += '<h2 class="section-title">📅 Upcoming Events (Next 7 Days)</h2>'
            schedule_html += '<div class="events-grid">'

            for event in schedule_events:
                date_str = event['event_date'].strftime('%A, %b %d')
                time_str = event['event_time'].strftime('%I:%M %p') if event['event_time'] else 'All day'
                importance = event['importance']

                # Color code by importance
                if importance >= 8:
                    badge_class = "badge-critical"
                elif importance >= 6:
                    badge_class = "badge-high"
                else:
                    badge_class = "badge-normal"

                schedule_html += f'''
                <div class="event-card">
                    <div class="event-header">
                        <span class="event-title">{event['title']}</span>
                        <span class="importance-badge {badge_class}">{importance}</span>
                    </div>
                    <div class="event-details">
                        <div class="event-date">📆 {date_str}</div>
                        <div class="event-time">🕐 {time_str}</div>
                        <div class="event-user">👤 {event['user_name']}</div>
                    </div>
                </div>
                '''

            schedule_html += '</div></div>'

        # Build schedule changes HTML
        changes_html = ""
        if schedule_changes:
            changes_html = '<div class="section-card changes-section">'
            changes_html += '<h2 class="section-title">✨ Schedule Changes (Last 24 Hours)</h2>'
            changes_html += '<ul class="changes-list">'

            for change in schedule_changes:
                date_str = change['event_date'].strftime('%a, %b %d')
                time_str = change['event_time'].strftime('%I:%M %p') if change['event_time'] else 'All day'
                changes_html += f'''
                <li class="change-item">
                    <strong>{change['title']}</strong> - {date_str} at {time_str}
                    <span class="change-meta">Added by {change['user_name']}</span>
                </li>
                '''

            changes_html += '</ul></div>'

        # Build memories HTML
        memories_html = ""
        if memories:
            memories_html = '<div class="section-card memories-section">'
            memories_html += '<h2 class="section-title">🧠 New Memories (Last 24 Hours)</h2>'
            memories_html += '<div class="memories-grid">'

            category_icons = {
                'schedule': '📅',
                'fact': '💡',
                'task': '✓',
                'preference': '❤️',
                'reminder': '⏰',
                'other': '📌'
            }
            category_colors = {
                'schedule': '#3498db',
                'fact': '#2ecc71',
                'task': '#e74c3c',
                'preference': '#e91e63',
                'reminder': '#f39c12',
                'other': '#95a5a6'
            }

            for mem in memories:
                icon = category_icons.get(mem['category'], '📌')
                color = category_colors.get(mem['category'], '#95a5a6')

                memories_html += f'''
                <div class="memory-card" style="border-left-color: {color}">
                    <div class="memory-header">
                        <span class="memory-icon">{icon}</span>
                        <span class="memory-category">{mem['category'].upper()}</span>
                        <span class="memory-importance">{mem['importance']}/10</span>
                    </div>
                    <div class="memory-content">{mem['content']}</div>
                    <div class="memory-meta">👤 {mem['user_name']}</div>
                </div>
                '''

            memories_html += '</div></div>'

        # Complete HTML email
        html_email = f'''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            margin: 0;
            padding: 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        }}
        .email-container {{
            max-width: 800px;
            margin: 0 auto;
            background-color: #ffffff;
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
        }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 40px 30px;
            text-align: center;
        }}
        .header h1 {{
            margin: 0;
            font-size: 28px;
            font-weight: 600;
        }}
        .header p {{
            margin: 10px 0 0 0;
            opacity: 0.95;
            font-size: 16px;
        }}
        .content {{
            padding: 30px;
        }}
        .section-card {{
            background: #f8f9fa;
            border-radius: 8px;
            padding: 20px;
            margin: 20px 0;
            border: 1px solid #e9ecef;
        }}
        .section-title {{
            margin: 0 0 20px 0;
            color: #2c3e50;
            font-size: 20px;
            font-weight: 600;
        }}
        .events-grid {{
            display: grid;
            gap: 15px;
        }}
        .event-card {{
            background: white;
            border-radius: 8px;
            padding: 15px;
            border-left: 4px solid #3498db;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        }}
        .event-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
        }}
        .event-title {{
            font-weight: 600;
            color: #2c3e50;
            font-size: 16px;
        }}
        .importance-badge {{
            padding: 3px 8px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 600;
            color: white;
        }}
        .badge-critical {{ background: #e74c3c; }}
        .badge-high {{ background: #f39c12; }}
        .badge-normal {{ background: #3498db; }}
        .event-details {{
            display: flex;
            gap: 15px;
            flex-wrap: wrap;
            font-size: 14px;
            color: #7f8c8d;
        }}
        .changes-list {{
            list-style: none;
            padding: 0;
            margin: 0;
        }}
        .change-item {{
            background: white;
            padding: 12px 15px;
            margin: 8px 0;
            border-radius: 6px;
            border-left: 3px solid #2ecc71;
        }}
        .change-meta {{
            display: block;
            font-size: 13px;
            color: #7f8c8d;
            margin-top: 4px;
        }}
        .memories-grid {{
            display: grid;
            gap: 12px;
        }}
        .memory-card {{
            background: white;
            border-radius: 8px;
            padding: 15px;
            border-left: 4px solid #95a5a6;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        }}
        .memory-header {{
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 8px;
        }}
        .memory-icon {{
            font-size: 18px;
        }}
        .memory-category {{
            font-size: 11px;
            font-weight: 600;
            color: #7f8c8d;
            background: #ecf0f1;
            padding: 2px 8px;
            border-radius: 10px;
        }}
        .memory-importance {{
            margin-left: auto;
            font-size: 12px;
            color: #95a5a6;
            font-weight: 600;
        }}
        .memory-content {{
            color: #2c3e50;
            margin: 8px 0;
            line-height: 1.5;
        }}
        .memory-meta {{
            font-size: 12px;
            color: #7f8c8d;
        }}
        .summary-section {{
            background: white;
            border-radius: 8px;
            padding: 20px;
            margin: 20px 0;
        }}
        .summary-section h2 {{
            color: #2c3e50;
            margin-top: 0;
        }}
        .summary-section h3 {{
            color: #34495e;
            margin-top: 20px;
        }}
        .summary-section p {{
            color: #555;
            margin: 10px 0;
        }}
        .summary-section li {{
            margin: 5px 0;
            color: #555;
        }}
        .footer {{
            background: #f8f9fa;
            padding: 25px 30px;
            text-align: center;
            border-top: 1px solid #e9ecef;
            color: #7f8c8d;
            font-size: 14px;
        }}
        .footer a {{
            color: #667eea;
            text-decoration: none;
            font-weight: 600;
        }}
        @media only screen and (max-width: 600px) {{
            .email-container {{
                border-radius: 0;
            }}
            .content {{
                padding: 20px;
            }}
            .event-details {{
                flex-direction: column;
                gap: 5px;
            }}
        }}
    </style>
</head>
<body>
    <div class="email-container">
        <div class="header">
            <h1>🤖 Mumble AI Daily Summary</h1>
            <p>{date_range}</p>
        </div>

        <div class="content">
            {schedule_html}
            {changes_html}
            {memories_html}

            <div class="summary-section">
                {html}
            </div>
        </div>

        <div class="footer">
            <p><strong>This is your automated daily summary from Mumble AI</strong></p>
            <p>Manage your settings at the <a href="http://localhost:5002">Web Control Panel</a></p>
        </div>
    </div>
</body>
</html>
'''
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

        # Get all data
        conversations = self.get_conversation_history(hours=24)
        schedule_events = self.get_schedule_events(days_ahead=7)
        schedule_changes = self.get_schedule_changes(hours=24)
        memories = self.get_recent_memories(hours=24)

        # Generate summary with all context
        summary = self.generate_summary_with_ollama(conversations, schedule_events, schedule_changes, memories)

        # Format date range
        now = datetime.now(pytz.timezone(settings['timezone']))
        yesterday = now - timedelta(days=1)
        date_range = f"{yesterday.strftime('%B %d, %Y')} - {now.strftime('%B %d, %Y')}"

        # Create email content
        subject = f"Mumble AI Daily Summary - {now.strftime('%B %d, %Y')}"
        html_content = self.format_html_email(summary, date_range, schedule_events, schedule_changes, memories)
        plain_content = f"Mumble AI Daily Summary\n{date_range}\n\n{summary}"

        # Send email
        success = self.send_email(settings, subject, html_content, plain_content)

        if success:
            # Update last_sent timestamp
            self.update_last_sent()
            logger.info("Daily summary completed successfully")

            # Log successful send
            self.log_email(
                direction='sent',
                email_type='summary',
                from_email=settings['from_email'],
                to_email=settings['recipient_email'],
                subject=subject,
                body=plain_content,
                status='success'
            )
        else:
            logger.error("Failed to send daily summary")

            # Log failed send
            self.log_email(
                direction='sent',
                email_type='summary',
                from_email=settings['from_email'],
                to_email=settings['recipient_email'],
                subject=subject,
                body=plain_content,
                status='error',
                error_message='Failed to send email via SMTP'
            )

    def send_test_email(self, settings: Dict) -> bool:
        """Send a test email"""
        logger.info("Sending test email...")

        # Get recent data for the test
        conversations = self.get_conversation_history(hours=24)
        schedule_events = self.get_schedule_events(days_ahead=7)
        schedule_changes = self.get_schedule_changes(hours=24)
        memories = self.get_recent_memories(hours=24)

        # Generate summary with all data
        if conversations or schedule_changes or memories:
            summary = self.generate_summary_with_ollama(conversations, schedule_events, schedule_changes, memories)
        else:
            summary = "This is a test email from Mumble AI.\n\nNo recent activity to display."

        date_range = datetime.now(pytz.timezone(settings['timezone'])).strftime('%B %d, %Y')
        subject = f"[TEST] Mumble AI Summary - {date_range}"
        html_content = self.format_html_email(summary, date_range, schedule_events, schedule_changes, memories)
        plain_content = f"Test Email from Mumble AI\n\n{summary}"

        success = self.send_email(settings, subject, html_content, plain_content)

        # Log test email
        self.log_email(
            direction='sent',
            email_type='test',
            from_email=settings['from_email'],
            to_email=settings['recipient_email'],
            subject=subject,
            body=plain_content,
            status='success' if success else 'error',
            error_message=None if success else 'Failed to send email via SMTP'
        )

        return success

    def update_last_checked(self):
        """Update the last_checked timestamp in database"""
        try:
            conn = self.get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute("""
                    UPDATE email_settings
                    SET last_checked = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = 1
                """, (datetime.now(),))
            conn.commit()
            logger.debug("Updated last_checked timestamp")
        except Exception as e:
            logger.error(f"Error updating last_checked: {e}")
            conn.rollback()

    def log_email(self, direction: str, email_type: str, from_email: str, to_email: str,
                  subject: str = None, body: str = None, status: str = 'success',
                  error_message: str = None, mapped_user: str = None):
        """Log email activity to database"""
        try:
            conn = self.get_db_connection()
            with conn.cursor() as cursor:
                # Create body preview (first 500 chars)
                body_preview = body[:500] if body else None

                cursor.execute("""
                    INSERT INTO email_logs (
                        direction, email_type, from_email, to_email, subject,
                        body_preview, full_body, status, error_message, mapped_user,
                        timestamp, created_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                """, (
                    direction, email_type, from_email, to_email, subject,
                    body_preview, body, status, error_message, mapped_user
                ))
            conn.commit()
            logger.debug(f"Logged {direction} email: {email_type} from {from_email} to {to_email}")
        except Exception as e:
            logger.error(f"Error logging email activity: {e}")
            conn.rollback()

    def save_persistent_memory(self, user_name: str, category: str, content: str, session_id: str = None,
                              importance: int = 5, tags: List[str] = None, event_date: str = None,
                              event_time: str = None):
        """Save a persistent memory to the database (with deduplication)"""
        conn = None
        try:
            conn = self.get_db_connection()
            cursor = conn.cursor()

            # Check for duplicates based on category type
            if category == 'schedule' and event_date:
                # For schedule memories, check user, category, event_date, and event_time
                cursor.execute(
                    """
                    SELECT id, content, importance
                    FROM persistent_memories
                    WHERE user_name = %s AND category = %s AND event_date = %s
                    AND event_time IS NOT DISTINCT FROM %s AND active = TRUE
                    """,
                    (user_name, category, event_date, event_time)
                )
            else:
                # For non-schedule memories, check for exact content match
                cursor.execute(
                    """
                    SELECT id, importance
                    FROM persistent_memories
                    WHERE user_name = %s AND category = %s AND content = %s AND active = TRUE
                    """,
                    (user_name, category, content)
                )

            existing = cursor.fetchone()

            if existing:
                if category == 'schedule':
                    existing_id, existing_content, existing_importance = existing
                    logger.info(f"Duplicate schedule memory detected for {user_name} on {event_date}. Skipping. Existing ID: {existing_id}")
                else:
                    existing_id, existing_importance = existing
                    logger.info(f"Duplicate {category} memory detected for {user_name}: '{content[:50]}...'. Skipping. Existing ID: {existing_id}")

                # If new importance is higher, update it
                if importance > existing_importance:
                    cursor.execute(
                        "UPDATE persistent_memories SET importance = %s WHERE id = %s",
                        (importance, existing_id)
                    )
                    conn.commit()
                    logger.info(f"Updated importance of existing memory ID {existing_id} from {existing_importance} to {importance}")

                cursor.close()
                return

            # No duplicate found, insert new memory
            cursor.execute(
                """
                INSERT INTO persistent_memories
                (user_name, category, content, session_id, importance, tags, event_date, event_time)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (user_name, category, content, session_id, importance, tags or [], event_date, event_time)
            )
            conn.commit()
            cursor.close()
            logger.info(f"Saved new {category} memory for {user_name}")
        except Exception as e:
            logger.error(f"Error saving persistent memory: {e}")
            if conn:
                conn.rollback()
        finally:
            if conn:
                pass  # Email service manages its own connection

    def extract_and_save_memory(self, user_message: str, assistant_response: str, user_name: str, session_id: str = None):
        """Extract important information from conversation and save as persistent memory"""
        try:
            # Get current date for context
            from zoneinfo import ZoneInfo
            ny_tz = ZoneInfo("America/New_York")
            current_datetime = datetime.now(ny_tz)
            current_date_str = current_datetime.strftime("%Y-%m-%d (%A, %B %d, %Y)")

            # Get Ollama model from database
            conn = self.get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute("SELECT value FROM bot_config WHERE key = 'ollama_model'")
                row = cursor.fetchone()
                ollama_model = row[0] if row else 'llama3.2:latest'

            # Prompt to extract important information with stricter JSON format requirements
            extraction_prompt = f"""Analyze this conversation and extract important information to remember.

CURRENT DATE: {current_date_str}

User: "{user_message}"
Assistant: "{assistant_response}"

Categories:
- schedule: appointments, meetings, events with dates/times
- fact: personal information, preferences, relationships, details
- task: things to do, reminders, action items
- preference: likes, dislikes, habits
- other: other important information

CRITICAL RULES:
1. ONLY extract information that is actually mentioned and important
2. Do NOT create entries with empty content
3. If there's nothing important to remember, return an empty array: []
4. You MUST respond with ONLY valid JSON, nothing else
5. DO NOT extract schedule memories when the user is just ASKING or QUERYING about their schedule
6. ONLY extract schedule memories when the user is TELLING you about NEW events or appointments
7. If the user asks "what's on my schedule", "tell me my calendar", "do I have anything", etc., return []

IMPORTANT: Query questions should return empty array. Examples:
- "What's on my schedule?" → []
- "Tell me about my calendar" → []
- "Do I have anything tomorrow?" → []
- "What do I have next week?" → []

For SCHEDULE category memories:
- Extract the date expression as spoken: "next Friday", "tomorrow", "October 15", etc.
- Use date_expression field for the raw expression
- Use HH:MM format (24-hour) for event_time, or null if no specific time
- Include description in content field

Format (return empty array if nothing important):
[
  {{"category": "schedule", "content": "Haircut appointment", "importance": 6, "date_expression": "next Friday", "event_time": "09:30"}},
  {{"category": "fact", "content": "Likes tea over coffee", "importance": 4}}
]

Valid categories: schedule, fact, task, preference, other
Importance: 1-10 (1=low, 10=critical)

JSON:"""

            response = requests.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    'model': ollama_model,
                    'prompt': extraction_prompt,
                    'stream': False,
                    'options': {
                        'temperature': 0.2,  # Very low temp for consistent JSON
                        'num_predict': 500   # Limit response length
                    }
                },
                timeout=30
            )

            if response.status_code == 200:
                result = response.json().get('response', '').strip()
                logger.debug(f"Memory extraction raw response: {result[:200]}...")

                # Try to parse and save memories
                memories = self._parse_memory_json(result)
                if memories is not None:
                    # Filter out memories with empty or whitespace-only content
                    valid_memories = []
                    for mem in memories:
                        if isinstance(mem, dict) and 'content' in mem:
                            content = mem.get('content', '')
                            # Skip if content is not a string or is empty/whitespace
                            if isinstance(content, str) and content.strip():
                                valid_memories.append(mem)
                            else:
                                # Debug level for expected LLM artifacts
                                logger.debug(f"Filtered out empty memory: category={mem.get('category')}, importance={mem.get('importance')}")

                    saved_count = 0
                    for memory in valid_memories:
                        if self._validate_memory(memory):
                            # Parse date expression for schedule memories
                            event_date = None
                            event_time = memory.get('event_time')

                            if memory.get('category') == 'schedule':
                                date_expression = memory.get('date_expression') or memory.get('event_date')
                                if date_expression:
                                    event_date = self.parse_date_expression(date_expression)

                            self.save_persistent_memory(
                                user_name=user_name,
                                category=memory.get('category', 'other'),
                                content=memory['content'],
                                session_id=session_id,
                                importance=memory.get('importance', 5),
                                event_date=event_date,
                                event_time=event_time
                            )
                            if event_date:
                                logger.info(f"Extracted memory for {user_name}: [{memory.get('category')}] {memory['content']} on {event_date} at {event_time or 'all day'}")
                            else:
                                logger.info(f"Extracted memory for {user_name}: [{memory.get('category')}] {memory['content']}")
                            saved_count += 1
                        else:
                            # Only warn if content exists but other validation failed
                            logger.warning(f"Skipping invalid memory (failed validation): {memory}")

                    if saved_count == 0 and len(memories) == 0:
                        logger.debug(f"No important memories found in conversation with {user_name}")
                else:
                    logger.warning(f"Failed to extract valid JSON from memory extraction response")

        except requests.exceptions.RequestException as e:
            logger.error(f"Network error during memory extraction: {e}")
        except Exception as e:
            logger.error(f"Error extracting memory: {e}", exc_info=True)

    def _parse_memory_json(self, text: str) -> Optional[List[Dict]]:
        """Parse JSON from LLM response with multiple fallback strategies"""
        import json
        import re

        # Strategy 1: Try direct JSON parsing
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return parsed
            logger.warning("Parsed JSON is not a list, trying extraction...")
        except json.JSONDecodeError:
            pass

        # Strategy 2: Extract JSON array with regex
        try:
            # Look for JSON array, being more careful about matching
            json_match = re.search(r'\[\s*(?:\{.*?\}\s*,?\s*)*\]', text, re.DOTALL)
            if json_match:
                json_str = json_match.group()
                parsed = json.loads(json_str)
                if isinstance(parsed, list):
                    return parsed
        except (json.JSONDecodeError, AttributeError):
            pass

        # Strategy 3: Clean common issues and retry
        try:
            # Remove common text before/after JSON
            cleaned = text

            # Remove markdown code blocks
            cleaned = re.sub(r'```json\s*', '', cleaned)
            cleaned = re.sub(r'```\s*', '', cleaned)

            # Find content between first [ and last ]
            start_idx = cleaned.find('[')
            end_idx = cleaned.rfind(']')

            if start_idx != -1 and end_idx != -1 and start_idx < end_idx:
                json_str = cleaned[start_idx:end_idx + 1]

                # Try to fix common JSON issues
                json_str = re.sub(r',(\s*[}\]])', r'\1', json_str)  # Remove trailing commas

                parsed = json.loads(json_str)
                if isinstance(parsed, list):
                    return parsed
        except (json.JSONDecodeError, AttributeError, ValueError):
            pass

        # Strategy 4: Return empty list if response suggests nothing to remember
        if any(phrase in text.lower() for phrase in ['nothing important', 'no important', 'empty array', '[]']):
            logger.debug("LLM indicated no important memories")
            return []

        # All strategies failed
        logger.error(f"Could not parse JSON from memory extraction. Response: {text[:500]}")
        return None

    def _validate_memory(self, memory: Dict) -> bool:
        """Validate a memory object has required fields and valid values"""
        if not isinstance(memory, dict):
            return False

        # Must have content and category
        if 'content' not in memory or 'category' not in memory:
            return False

        # Content must be non-empty string
        if not isinstance(memory['content'], str) or not memory['content'].strip():
            return False

        # Category must be valid
        valid_categories = ['schedule', 'fact', 'task', 'preference', 'other']
        if memory['category'] not in valid_categories:
            logger.warning(f"Invalid category '{memory['category']}', defaulting to 'other'")
            memory['category'] = 'other'

        # Importance should be 1-10 if present
        if 'importance' in memory:
            try:
                importance = int(memory['importance'])
                if importance < 1 or importance > 10:
                    logger.warning(f"Importance {importance} out of range, clamping to 1-10")
                    memory['importance'] = max(1, min(10, importance))
            except (ValueError, TypeError):
                logger.warning(f"Invalid importance value, defaulting to 5")
                memory['importance'] = 5

        return True

    def add_schedule_event(self, user_name: str, title: str, event_date: str, event_time: str = None,
                          description: str = None, importance: int = 5) -> int:
        """Add a new schedule event (with deduplication)"""
        conn = None
        try:
            conn = self.get_db_connection()
            cursor = conn.cursor()

            # Check for duplicate: same user, title, and date
            cursor.execute(
                """
                SELECT id, event_time, description, importance
                FROM schedule_events
                WHERE user_name = %s AND title = %s AND event_date = %s AND active = TRUE
                """,
                (user_name, title, event_date)
            )

            existing = cursor.fetchone()

            if existing:
                existing_id, existing_time, existing_desc, existing_importance = existing
                logger.info(f"Duplicate schedule event detected for {user_name}: '{title}' on {event_date}. Using existing ID {existing_id}")

                # If new info is more detailed, update the existing event
                should_update = False
                updates = []
                params = []

                if event_time and not existing_time:
                    updates.append("event_time = %s")
                    params.append(event_time)
                    should_update = True

                if description and not existing_desc:
                    updates.append("description = %s")
                    params.append(description)
                    should_update = True

                if importance and importance > existing_importance:
                    updates.append("importance = %s")
                    params.append(importance)
                    should_update = True

                if should_update:
                    params.append(existing_id)
                    update_query = f"UPDATE schedule_events SET {', '.join(updates)} WHERE id = %s"
                    cursor.execute(update_query, params)
                    conn.commit()
                    logger.info(f"Updated existing schedule event ID {existing_id} with new details")

                cursor.close()
                return existing_id

            # No duplicate found, create new event
            cursor.execute(
                """
                INSERT INTO schedule_events (user_name, title, event_date, event_time, description, importance)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (user_name, title, event_date, event_time, description, importance)
            )

            event_id = cursor.fetchone()[0]
            conn.commit()
            cursor.close()

            logger.info(f"Added schedule event ID {event_id} for {user_name}: {title} on {event_date}")
            return event_id

        except Exception as e:
            logger.error(f"Error adding schedule event: {e}")
            if conn:
                conn.rollback()
            return None
        finally:
            if conn:
                pass  # Email service manages its own connection

    def update_schedule_event(self, event_id: int, title: str = None, event_date: str = None,
                             event_time: str = None, description: str = None, importance: int = None) -> bool:
        """Update an existing schedule event"""
        conn = None
        try:
            conn = self.get_db_connection()
            cursor = conn.cursor()

            # Build update query dynamically
            updates = []
            params = []

            if title is not None:
                updates.append("title = %s")
                params.append(title)
            if event_date is not None:
                updates.append("event_date = %s")
                params.append(event_date)
            if event_time is not None:
                updates.append("event_time = %s")
                params.append(event_time)
            if description is not None:
                updates.append("description = %s")
                params.append(description)
            if importance is not None:
                updates.append("importance = %s")
                params.append(importance)

            if not updates:
                return False

            updates.append("updated_at = CURRENT_TIMESTAMP")
            params.append(event_id)

            query = f"UPDATE schedule_events SET {', '.join(updates)} WHERE id = %s AND active = TRUE"
            cursor.execute(query, params)

            affected = cursor.rowcount
            conn.commit()
            cursor.close()

            logger.info(f"Updated schedule event ID {event_id}, affected rows: {affected}")
            return affected > 0

        except Exception as e:
            logger.error(f"Error updating schedule event: {e}")
            if conn:
                conn.rollback()
            return False
        finally:
            if conn:
                pass  # Email service manages its own connection

    def delete_schedule_event(self, event_id: int) -> bool:
        """Delete (deactivate) a schedule event"""
        conn = None
        try:
            conn = self.get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE schedule_events
                SET active = FALSE, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (event_id,)
            )

            affected = cursor.rowcount
            conn.commit()
            cursor.close()

            logger.info(f"Deleted schedule event ID {event_id}, affected rows: {affected}")
            return affected > 0

        except Exception as e:
            logger.error(f"Error deleting schedule event: {e}")
            if conn:
                conn.rollback()
            return False
        finally:
            if conn:
                pass  # Email service manages its own connection

    def parse_date_expression(self, date_expr: str, reference_date: datetime = None) -> Optional[str]:
        """Parse natural language date expressions into YYYY-MM-DD format"""
        if not date_expr or date_expr == "null":
            return None

        from zoneinfo import ZoneInfo
        import re

        ny_tz = ZoneInfo("America/New_York")
        if reference_date is None:
            reference_date = datetime.now(ny_tz)

        date_expr = date_expr.lower().strip()

        # Already in YYYY-MM-DD format
        if re.match(r'^\d{4}-\d{2}-\d{2}$', date_expr):
            return date_expr

        # Handle "tomorrow"
        if date_expr == "tomorrow":
            result_date = reference_date + timedelta(days=1)
            return result_date.strftime('%Y-%m-%d')

        # Handle "today"
        if date_expr == "today":
            return reference_date.strftime('%Y-%m-%d')

        # Handle "in X days/weeks/months"
        in_match = re.match(r'in (\d+) (day|days|week|weeks|month|months)', date_expr)
        if in_match:
            count = int(in_match.group(1))
            unit = in_match.group(2)
            if 'day' in unit:
                result_date = reference_date + timedelta(days=count)
            elif 'week' in unit:
                result_date = reference_date + timedelta(weeks=count)
            elif 'month' in unit:
                result_date = reference_date + timedelta(days=count * 30)  # Approximate
            return result_date.strftime('%Y-%m-%d')

        # Handle day names: "this Monday", "next Friday", "Monday", etc.
        day_names = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']

        for i, day_name in enumerate(day_names):
            if day_name in date_expr:
                current_weekday = reference_date.weekday()  # Monday is 0
                target_weekday = i

                # Determine if "this" or "next"
                if 'next' in date_expr:
                    # "next Friday" means next week's Friday
                    days_ahead = (target_weekday - current_weekday) % 7
                    if days_ahead == 0:
                        days_ahead = 7  # If today is Friday, "next Friday" is 7 days away
                    else:
                        days_ahead += 7  # Always go to next week
                elif 'this' in date_expr:
                    # "this Friday" means this week's Friday
                    days_ahead = (target_weekday - current_weekday) % 7
                    if days_ahead == 0:
                        days_ahead = 7  # If today is Friday, "this Friday" might mean next occurrence
                else:
                    # Just "Friday" - means upcoming Friday (could be this week or next)
                    days_ahead = (target_weekday - current_weekday) % 7
                    if days_ahead == 0:
                        days_ahead = 7  # If today is Friday, assume next Friday

                result_date = reference_date + timedelta(days=days_ahead)
                return result_date.strftime('%Y-%m-%d')

        # Try parsing common date formats
        try:
            from dateutil import parser
            parsed_date = parser.parse(date_expr, fuzzy=True)
            return parsed_date.strftime('%Y-%m-%d')
        except:
            pass

        logger.warning(f"Could not parse date expression: {date_expr}")
        return None

    def extract_and_manage_schedule(self, user_message: str, assistant_response: str, user_name: str):
        """Extract scheduling information from conversation and manage schedule events"""
        try:
            # Get current date for context
            from zoneinfo import ZoneInfo
            ny_tz = ZoneInfo("America/New_York")
            current_datetime = datetime.now(ny_tz)
            current_date_str = current_datetime.strftime("%Y-%m-%d (%A, %B %d, %Y)")

            # Get Ollama model from database
            conn = self.get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute("SELECT value FROM bot_config WHERE key = 'ollama_model'")
                row = cursor.fetchone()
                ollama_model = row[0] if row else 'llama3.2:latest'

            extraction_prompt = f"""You are a scheduling assistant analyzing a conversation to manage calendar events.

CURRENT DATE: {current_date_str}

Conversation:
User: {user_message}
Assistant: {assistant_response}

Analyze this conversation and determine if the user wants to:
1. ADD a new event to their schedule
2. UPDATE an existing event
3. DELETE/CANCEL an event
4. NOTHING - just asking about schedule or casual conversation

If scheduling action is needed, extract:
- Action: ADD, UPDATE, DELETE, or NOTHING
- Event title (brief description)
- Date expression (use these formats):
  * Specific date: "2025-10-15" or "October 15" or "Oct 15"
  * Relative: "tomorrow", "next Monday", "next Friday", "in 3 days"
- Time (HH:MM format in 24-hour, or null if not specified)
- Description (optional additional details)
- Importance (1-10, default 5)
- Event ID (if updating/deleting - look for "that event", "the appointment", etc.)

CRITICAL INSTRUCTIONS:
- ONLY use action "ADD" if the user is CREATING or SCHEDULING a NEW event
- If the user is ASKING, QUERYING, READING, or CHECKING their schedule, ALWAYS use action "NOTHING"
- DO NOT create events when the user asks "what's on my calendar", "tell me my schedule", "what do I have", "do I have anything", etc.
- When in doubt, use "NOTHING" - it's better to not create than to create a duplicate

IMPORTANT: For relative dates like "next Friday", just return "next Friday" - do NOT calculate the actual date.

Respond ONLY with a JSON object (no markdown, no extra text):
{{"action": "ADD|UPDATE|DELETE|NOTHING", "title": "...", "date_expression": "next Friday", "time": "HH:MM or null", "description": "...", "importance": 5, "event_id": null}}

Examples:
User: "I have a dentist appointment tomorrow at 3pm"
{{"action": "ADD", "title": "Dentist appointment", "date_expression": "tomorrow", "time": "15:00", "description": null, "importance": 7, "event_id": null}}

User: "Schedule me for next Friday at 9:30am for my haircut"
{{"action": "ADD", "title": "haircut", "date_expression": "next Friday", "time": "09:30", "description": null, "importance": 5, "event_id": null}}

User: "Cancel my meeting on Monday"
{{"action": "DELETE", "title": "meeting", "date_expression": null, "time": null, "description": null, "importance": 5, "event_id": null}}

User: "What's on my schedule?"
{{"action": "NOTHING", "title": null, "date_expression": null, "time": null, "description": null, "importance": 5, "event_id": null}}

User: "Tell me about my calendar"
{{"action": "NOTHING", "title": null, "date_expression": null, "time": null, "description": null, "importance": 5, "event_id": null}}

User: "Do I have anything tomorrow?"
{{"action": "NOTHING", "title": null, "date_expression": null, "time": null, "description": null, "importance": 5, "event_id": null}}

User: "What do I have next week?"
{{"action": "NOTHING", "title": null, "date_expression": null, "time": null, "description": null, "importance": 5, "event_id": null}}
"""

            response = requests.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    'model': ollama_model,
                    'prompt': extraction_prompt,
                    'stream': False,
                    'temperature': 0.1
                },
                timeout=30
            )

            if response.status_code == 200:
                import json
                result_text = response.json().get('response', '').strip()

                # Parse JSON response
                try:
                    result = json.loads(result_text)
                    action = result.get('action', 'NOTHING')

                    if action == 'ADD':
                        # Parse the date expression into YYYY-MM-DD format
                        date_expression = result.get('date_expression') or result.get('date')
                        parsed_date = self.parse_date_expression(date_expression, current_datetime)

                        event_id = self.add_schedule_event(
                            user_name=user_name,
                            title=result.get('title', 'Untitled Event'),
                            event_date=parsed_date,
                            event_time=result.get('time'),
                            description=result.get('description'),
                            importance=result.get('importance', 5)
                        )
                        if event_id:
                            logger.info(f"Added schedule event {event_id} for {user_name}: {result.get('title')} on {parsed_date}")

                    elif action == 'UPDATE' and result.get('event_id'):
                        # Parse the date expression if present
                        date_expression = result.get('date_expression') or result.get('date')
                        parsed_date = self.parse_date_expression(date_expression, current_datetime) if date_expression else None

                        success = self.update_schedule_event(
                            event_id=result.get('event_id'),
                            title=result.get('title'),
                            event_date=parsed_date,
                            event_time=result.get('time'),
                            description=result.get('description'),
                            importance=result.get('importance')
                        )
                        if success:
                            logger.info(f"Updated schedule event {result.get('event_id')} for {user_name}")

                    elif action == 'DELETE':
                        # Find and delete matching events
                        title_search = result.get('title', '')
                        if title_search:
                            events = self.get_schedule_events(days_ahead=365)  # Get all events for user
                            # Filter by user
                            user_events = [e for e in events if e['user_name'] == user_name]
                            for event in user_events:
                                if title_search.lower() in event['title'].lower():
                                    self.delete_schedule_event(event['id'])
                                    logger.info(f"Deleted schedule event {event['id']} for {user_name}")
                                    break

                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse schedule extraction result: {result_text}")

        except Exception as e:
            logger.error(f"Error in schedule extraction: {e}")
            import traceback
            traceback.print_exc()

    def connect_imap(self, settings: Dict):
        """Connect to IMAP server"""
        try:
            if settings['imap_use_ssl']:
                imap = imaplib.IMAP4_SSL(settings['imap_host'], settings['imap_port'])
            else:
                imap = imaplib.IMAP4(settings['imap_host'], settings['imap_port'])

            imap.login(settings['imap_username'], settings['imap_password'])
            logger.info(f"Connected to IMAP server {settings['imap_host']}:{settings['imap_port']}")
            return imap
        except Exception as e:
            logger.error(f"Failed to connect to IMAP server: {e}")
            return None

    def get_email_body(self, msg) -> Tuple[str, str]:
        """Extract plain text and HTML body from email message"""
        plain_text = ""
        html_text = ""

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition", ""))

                # Skip attachments
                if "attachment" in content_disposition:
                    continue

                if content_type == "text/plain":
                    try:
                        plain_text = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                    except:
                        pass
                elif content_type == "text/html":
                    try:
                        html_text = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                    except:
                        pass
        else:
            content_type = msg.get_content_type()
            if content_type == "text/plain":
                try:
                    plain_text = msg.get_payload(decode=True).decode('utf-8', errors='ignore')
                except:
                    pass
            elif content_type == "text/html":
                try:
                    html_text = msg.get_payload(decode=True).decode('utf-8', errors='ignore')
                except:
                    pass

        # Prefer plain text, fall back to HTML (strip tags)
        body = plain_text if plain_text else self.strip_html_tags(html_text)
        return body.strip(), html_text.strip()

    def strip_html_tags(self, html: str) -> str:
        """Remove HTML tags from text"""
        if not html:
            return ""
        # Simple HTML tag removal
        text = re.sub(r'<[^>]+>', '', html)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    def get_user_from_email(self, email_address: str) -> Optional[str]:
        """Look up the user name associated with an email address"""
        try:
            conn = self.get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT user_name
                    FROM email_user_mappings
                    WHERE LOWER(email_address) = LOWER(%s)
                """, (email_address,))

                row = cursor.fetchone()
                if row:
                    user_name = row[0]
                    logger.info(f"Mapped email {email_address} to user: {user_name}")
                    return user_name
                else:
                    logger.debug(f"No mapping found for email: {email_address}")
                    return None
        except Exception as e:
            logger.error(f"Error looking up email mapping: {e}")
            return None

    def get_user_memories(self, user_name: str = None, limit: int = 10) -> List[Dict]:
        """Get persistent memories for context (user-specific or general)"""
        try:
            conn = self.get_db_connection()
            with conn.cursor() as cursor:
                # Get memories for specific user or general memories
                if user_name:
                    cursor.execute("""
                        SELECT category, content, importance, extracted_at, event_date, event_time
                        FROM persistent_memories
                        WHERE active = TRUE
                          AND (user_name = %s OR user_name = 'general')
                        ORDER BY importance DESC, extracted_at DESC
                        LIMIT %s
                    """, (user_name, limit))
                else:
                    cursor.execute("""
                        SELECT category, content, importance, extracted_at, event_date, event_time
                        FROM persistent_memories
                        WHERE active = TRUE
                        ORDER BY importance DESC, extracted_at DESC
                        LIMIT %s
                    """, (limit,))

                rows = cursor.fetchall()
                memories = []
                for row in rows:
                    memories.append({
                        'category': row[0],
                        'content': row[1],
                        'importance': row[2],
                        'extracted_at': row[3],
                        'event_date': row[4],
                        'event_time': row[5]
                    })

                logger.debug(f"Retrieved {len(memories)} memories for user '{user_name}'" if user_name else f"Retrieved {len(memories)} general memories")
                return memories
        except Exception as e:
            logger.error(f"Error getting memories: {e}")
            return []

    def get_upcoming_schedule(self, user_name: str = None, days_ahead: int = 30) -> List[Dict]:
        """Get upcoming schedule events for email context (user-specific or all)"""
        try:
            conn = self.get_db_connection()
            with conn.cursor() as cursor:
                if user_name:
                    cursor.execute("""
                        SELECT user_name, title, event_date, event_time, description, importance
                        FROM schedule_events
                        WHERE active = TRUE
                          AND user_name = %s
                          AND event_date >= CURRENT_DATE
                          AND event_date <= CURRENT_DATE + INTERVAL '%s days'
                        ORDER BY event_date, event_time
                    """, (user_name, days_ahead))
                else:
                    cursor.execute("""
                        SELECT user_name, title, event_date, event_time, description, importance
                        FROM schedule_events
                        WHERE active = TRUE
                          AND event_date >= CURRENT_DATE
                          AND event_date <= CURRENT_DATE + INTERVAL '%s days'
                        ORDER BY event_date, event_time
                    """, (days_ahead,))

                rows = cursor.fetchall()
                events = []
                for row in rows:
                    events.append({
                        'user_name': row[0],
                        'title': row[1],
                        'event_date': row[2],
                        'event_time': row[3],
                        'description': row[4],
                        'importance': row[5]
                    })

                logger.debug(f"Retrieved {len(events)} schedule events for user '{user_name}'" if user_name else f"Retrieved {len(events)} schedule events")
                return events
        except Exception as e:
            logger.error(f"Error getting schedule: {e}")
            return []

    def generate_ai_reply(self, sender: str, subject: str, body: str, settings: Dict) -> str:
        """Generate AI reply to email using Ollama with full context (memories, schedule, persona)"""
        try:
            logger.info(f"Generating AI reply for email from {sender}")

            # Look up user mapping from email address
            mapped_user = self.get_user_from_email(sender)
            if mapped_user:
                logger.info(f"Using data for user: {mapped_user}")
            else:
                logger.info(f"No mapping found, using general/all data")

            # Get bot persona and model
            conn = self.get_db_connection()
            with conn.cursor() as cursor:
                cursor.execute("SELECT value FROM bot_config WHERE key = 'bot_persona'")
                row = cursor.fetchone()
                bot_persona = row[0] if row else "a helpful AI assistant"

                cursor.execute("SELECT value FROM bot_config WHERE key = 'ollama_model'")
                row = cursor.fetchone()
                ollama_model = row[0] if row else 'llama3.2:latest'

            # Get memories and schedule for context (user-specific if mapped)
            memories = self.get_user_memories(mapped_user, limit=10)
            schedule_events = self.get_upcoming_schedule(mapped_user, days_ahead=30)

            # Build context sections
            current_datetime = datetime.now(pytz.timezone(settings.get('timezone', 'America/New_York')))

            # Memories section
            memory_context = ""
            if memories:
                memory_context = "\n📝 RELEVANT MEMORIES:\n"
                category_icons = {'schedule': '📅', 'fact': '💡', 'task': '✓', 'preference': '❤️', 'reminder': '⏰', 'other': '📌'}
                for mem in memories:
                    icon = category_icons.get(mem['category'], '📌')
                    memory_context += f"{icon} [{mem['category'].upper()}] {mem['content']}\n"
                memory_context += "\n"

            # Schedule section
            schedule_context = ""
            if schedule_events:
                schedule_context = f"\n📅 UPCOMING SCHEDULE (next 30 days from {current_datetime.strftime('%A, %B %d, %Y')}):\n"
                for event in schedule_events:
                    event_date_str = event['event_date'].strftime('%A, %B %d, %Y') if hasattr(event['event_date'], 'strftime') else str(event['event_date'])
                    event_time_str = str(event['event_time']) if event['event_time'] else "All day"
                    importance_emoji = "🔴" if event['importance'] >= 9 else "🟠" if event['importance'] >= 7 else "🔵"
                    schedule_context += f"{importance_emoji} {event['title']} - {event_date_str} at {event_time_str}\n"
                    if event['description']:
                        schedule_context += f"   Details: {event['description']}\n"
                schedule_context += "\n"
            else:
                schedule_context = f"\n📅 SCHEDULE: No upcoming events scheduled\n\n"

            # Create comprehensive prompt matching mumble-bot style
            reply_prompt = f"""You are {bot_persona}.

You are an AI assistant responding to an email from {mapped_user if mapped_user else sender}.

IMPORTANT CONTEXT ABOUT THE EMAIL SENDER ({mapped_user if mapped_user else sender}):
{memory_context}{schedule_context}
RECEIVED EMAIL:
From: {sender}
Subject: {subject}

Message:
{body}

---

CRITICAL INSTRUCTIONS:
- The schedule and memories shown above belong to THE EMAIL SENDER ({mapped_user if mapped_user else sender}), NOT to you
- When referring to their schedule, use "you" or "your", NEVER "I" or "my"
- Example: "You have a haircut on Friday" NOT "I have a haircut"
- You are an AI assistant helping THEM, not a person with your own schedule

RESPONSE GUIDELINES:
Generate a professional, helpful, and personalized email reply. Use the memories and schedule information above to provide relevant context in your response.

- Stay in character based on your persona, but remember you are an AI assistant
- Reference relevant memories or schedule events that belong to THE SENDER
- Be professional but conversational and friendly
- Address the sender's questions or concerns directly
- If asked about schedule/calendar, use ONLY the information shown above and refer to it as THEIR schedule
- If you don't have enough information, acknowledge it politely
- Keep the reply concise (under 250 words)
- Do not include email headers, signatures, or formatting - just the body text
- Do not make up information not provided in the context
- ALWAYS use "you/your" when talking about the sender's schedule, NEVER "I/my"

Your reply:"""

            response = requests.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    'model': ollama_model,
                    'prompt': reply_prompt,
                    'stream': False,
                    'options': {
                        'temperature': 0.7,
                        'num_predict': 500
                    }
                },
                timeout=120
            )

            if response.status_code == 200:
                result = response.json()
                reply_text = result.get('response', '').strip()

                # Add signature if configured
                if settings['reply_signature']:
                    reply_text += f"\n\n{settings['reply_signature']}"

                logger.info("AI reply generated successfully")
                return reply_text
            else:
                logger.error(f"Ollama request failed with status {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"Error generating AI reply: {e}")
            return None

    def send_reply_email(self, settings: Dict, to_email: str, subject: str, reply_body: str,
                         in_reply_to: str = None, references: str = None, mapped_user: str = None) -> bool:
        """Send reply email via SMTP"""
        try:
            # Create message
            msg = MIMEMultipart('alternative')

            # Add "Re:" prefix if not already present
            if not subject.lower().startswith('re:'):
                subject = f"Re: {subject}"

            msg['Subject'] = subject
            msg['From'] = settings['from_email']
            msg['To'] = to_email
            msg['Date'] = formatdate(localtime=True)

            # Add threading headers for proper email threading
            if in_reply_to:
                msg['In-Reply-To'] = in_reply_to
            if references:
                msg['References'] = references

            # Create plain text and HTML versions
            plain_text = reply_body
            # Convert newlines to HTML breaks for HTML version
            html_body_content = reply_body.replace('\n', '<br>')
            html_text = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            padding: 20px;
        }}
        .reply-body {{
            white-space: pre-wrap;
        }}
    </style>
</head>
<body>
    <div class="reply-body">{html_body_content}</div>
</body>
</html>
"""

            # Attach plain text and HTML versions
            part1 = MIMEText(plain_text, 'plain', 'utf-8')
            part2 = MIMEText(html_text, 'html', 'utf-8')
            msg.attach(part1)
            msg.attach(part2)

            # Connect to SMTP server and send
            logger.info(f"Sending reply to {to_email}")

            if settings['smtp_use_ssl']:
                smtp = smtplib.SMTP_SSL(settings['smtp_host'], settings['smtp_port'], timeout=30)
            else:
                smtp = smtplib.SMTP(settings['smtp_host'], settings['smtp_port'], timeout=30)
                if settings['smtp_use_tls']:
                    smtp.starttls()

            if settings['smtp_username'] and settings['smtp_password']:
                smtp.login(settings['smtp_username'], settings['smtp_password'])

            smtp.send_message(msg)
            smtp.quit()

            logger.info(f"Reply sent successfully to {to_email}")

            # Log successful send
            self.log_email(
                direction='sent',
                email_type='reply',
                from_email=settings['from_email'],
                to_email=to_email,
                subject=subject,
                body=reply_body,
                status='success',
                mapped_user=mapped_user
            )

            return True

        except Exception as e:
            logger.error(f"Failed to send reply email: {e}")

            # Log failed send
            self.log_email(
                direction='sent',
                email_type='reply',
                from_email=settings['from_email'],
                to_email=to_email,
                subject=subject,
                body=reply_body,
                status='error',
                error_message=str(e),
                mapped_user=mapped_user
            )

            return False

    def check_and_reply_to_emails(self, settings: Dict):
        """Check for new emails and send AI-generated replies"""
        if not settings['imap_enabled']:
            return

        if not settings['auto_reply_enabled']:
            logger.debug("Auto-reply is disabled")
            return

        logger.info("Checking for new emails...")

        imap = self.connect_imap(settings)
        if not imap:
            return

        try:
            # Select mailbox
            mailbox = settings['imap_mailbox']
            imap.select(mailbox)

            # Search for unseen emails
            status, messages = imap.search(None, 'UNSEEN')

            if status != 'OK':
                logger.error("Failed to search for emails")
                return

            email_ids = messages[0].split()

            if not email_ids:
                logger.debug("No new emails found")
                self.update_last_checked()
                return

            logger.info(f"Found {len(email_ids)} new email(s)")

            for email_id in email_ids:
                try:
                    # Fetch email
                    status, msg_data = imap.fetch(email_id, '(RFC822)')

                    if status != 'OK':
                        logger.error(f"Failed to fetch email {email_id}")
                        continue

                    # Parse email
                    raw_email = msg_data[0][1]
                    msg = BytesParser(policy=policy.default).parsebytes(raw_email)

                    # Extract email details
                    from_header = msg.get('From', '')
                    sender_name, sender_email = parseaddr(from_header)
                    subject = msg.get('Subject', 'No Subject')
                    message_id = msg.get('Message-ID', '')
                    references = msg.get('References', '')

                    # Get email body
                    body, html_body = self.get_email_body(msg)

                    logger.info(f"Processing email from {sender_email}: {subject}")

                    # Look up user mapping for logging
                    mapped_user = self.get_user_from_email(sender_email)

                    # Log received email
                    self.log_email(
                        direction='received',
                        email_type='other',
                        from_email=sender_email,
                        to_email=settings['imap_username'],
                        subject=subject,
                        body=body,
                        status='success',
                        mapped_user=mapped_user
                    )

                    # Generate AI reply
                    reply_text = self.generate_ai_reply(sender_email, subject, body, settings)

                    if reply_text:
                        # Send reply (will be logged inside send_reply_email)
                        success = self.send_reply_email(
                            settings,
                            sender_email,
                            subject,
                            reply_text,
                            in_reply_to=message_id,
                            references=f"{references} {message_id}".strip(),
                            mapped_user=mapped_user
                        )

                        if success:
                            logger.info(f"Successfully replied to {sender_email}")

                            # Extract and save memories in background (non-blocking)
                            threading.Thread(
                                target=self.extract_and_save_memory,
                                args=(body, reply_text, mapped_user or sender_email, None),
                                daemon=True
                            ).start()

                            # Extract and manage schedule in background (non-blocking)
                            threading.Thread(
                                target=self.extract_and_manage_schedule,
                                args=(body, reply_text, mapped_user or sender_email),
                                daemon=True
                            ).start()
                        else:
                            logger.error(f"Failed to send reply to {sender_email}")
                    else:
                        logger.error(f"Failed to generate reply for email from {sender_email}")

                except Exception as e:
                    logger.error(f"Error processing email {email_id}: {e}", exc_info=True)

            # Update last checked timestamp
            self.update_last_checked()

        except Exception as e:
            logger.error(f"Error checking emails: {e}", exc_info=True)
        finally:
            try:
                imap.close()
                imap.logout()
            except:
                pass

    def run(self):
        """Main service loop"""
        logger.info("Email Summary Service started")
        logger.info(f"Checking every {CHECK_INTERVAL_SECONDS} seconds for scheduled emails")

        last_email_check = datetime.now()

        while True:
            try:
                # Get email settings
                settings = self.get_email_settings()

                if settings:
                    # Check if we should send daily summary
                    if self.should_send_summary(settings):
                        self.send_daily_summary(settings)

                    # Check for incoming emails and send AI replies
                    if settings['imap_enabled'] and settings['auto_reply_enabled']:
                        # Use the configured check interval for IMAP
                        check_interval = settings['check_interval_seconds']
                        time_since_last_check = (datetime.now() - last_email_check).total_seconds()

                        if time_since_last_check >= check_interval:
                            self.check_and_reply_to_emails(settings)
                            last_email_check = datetime.now()

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
