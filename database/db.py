"""
database/db.py — SQLite database models and helpers using SQLAlchemy
"""

import os
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Text
from sqlalchemy.orm import DeclarativeBase, Session

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "mhtcet.db")
engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)


class Base(DeclarativeBase):
    pass


class CheckLog(Base):
    """Stores every single check attempt."""
    __tablename__ = "check_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    login_status = Column(String(20), nullable=False)   # "success" | "failed" | "error"
    pcm_found = Column(Boolean, default=False, nullable=False)
    error_message = Column(Text, nullable=True)
    screenshot_path = Column(String(500), nullable=True)
    page_title = Column(String(300), nullable=True)


class NotificationLog(Base):
    """Tracks every notification sent to avoid spam."""
    __tablename__ = "notification_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    notif_type = Column(String(30), nullable=False)     # "call" | "whatsapp_found" | "whatsapp_error"
    success = Column(Boolean, default=False, nullable=False)
    message = Column(Text, nullable=True)
    error = Column(Text, nullable=True)


class AppStatus(Base):
    """Single-row live status of the checker."""
    __tablename__ = "app_status"

    id = Column(Integer, primary_key=True, default=1)
    checker_running = Column(Boolean, default=False)
    pcm_found = Column(Boolean, default=False)
    alert_sent = Column(Boolean, default=False)
    last_checked = Column(DateTime, nullable=True)
    next_check = Column(DateTime, nullable=True)
    last_login_status = Column(String(20), nullable=True)
    last_error = Column(Text, nullable=True)
    total_checks = Column(Integer, default=0)
    consecutive_errors = Column(Integer, default=0)


def init_db():
    """Create tables and ensure AppStatus row exists."""
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        status = session.get(AppStatus, 1)
        if not status:
            session.add(AppStatus(id=1))
            session.commit()


def get_status() -> AppStatus:
    with Session(engine) as session:
        return session.get(AppStatus, 1)


def update_status(**kwargs):
    with Session(engine) as session:
        status = session.get(AppStatus, 1)
        for key, val in kwargs.items():
            setattr(status, key, val)
        session.commit()


def log_check(login_status: str, pcm_found: bool, error_message=None,
              screenshot_path=None, page_title=None):
    with Session(engine) as session:
        log = CheckLog(
            login_status=login_status,
            pcm_found=pcm_found,
            error_message=error_message,
            screenshot_path=screenshot_path,
            page_title=page_title
        )
        session.add(log)

        status = session.get(AppStatus, 1)
        status.last_checked = datetime.utcnow()
        status.last_login_status = login_status
        status.total_checks = (status.total_checks or 0) + 1
        if error_message:
            status.consecutive_errors = (status.consecutive_errors or 0) + 1
            status.last_error = error_message
        else:
            status.consecutive_errors = 0
            status.last_error = None
        if pcm_found:
            status.pcm_found = True
        session.commit()


def log_notification(notif_type: str, success: bool, message=None, error=None):
    with Session(engine) as session:
        notif = NotificationLog(
            notif_type=notif_type,
            success=success,
            message=message,
            error=error
        )
        session.add(notif)
        if notif_type in ("call", "whatsapp_found") and success:
            status = session.get(AppStatus, 1)
            status.alert_sent = True
        session.commit()


def get_recent_logs(limit=25):
    with Session(engine) as session:
        logs = session.query(CheckLog).order_by(CheckLog.id.desc()).limit(limit).all()
        return [
            {
                "id": l.id,
                "timestamp": l.timestamp.strftime("%Y-%m-%d %H:%M:%S") if l.timestamp else "—",
                "login_status": l.login_status,
                "pcm_found": l.pcm_found,
                "error_message": l.error_message or "",
                "page_title": l.page_title or "",
                "screenshot_path": l.screenshot_path or ""
            }
            for l in logs
        ]


def reset_alert():
    """Manually reset the alert flag (for testing)."""
    update_status(alert_sent=False, pcm_found=False)
