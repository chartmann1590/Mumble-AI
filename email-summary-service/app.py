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
        else:
            logger.error("Failed to send daily summary")

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
