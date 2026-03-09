"""
ZBS CRM Bot — Database Models
SQLAlchemy async + PostgreSQL
"""

import os
import asyncio
from datetime import datetime, date, time
from enum import Enum as PyEnum

from sqlalchemy import (
    Column, Integer, BigInteger, String, Text, Float, Boolean,
    DateTime, Date, Time, ForeignKey, Enum, Index, UniqueConstraint,
    create_engine, text
)
from sqlalchemy.orm import relationship, declarative_base, sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.sql import func

Base = declarative_base()

# ==================== ENUMS ====================

class UserRole(PyEnum):
    ADMIN = "admin"          # Robert, Susanna
    MANAGER = "manager"      # Team leads
    MEMBER = "member"        # Team members
    
class DealStatus(PyEnum):
    LEAD = "lead"                # Потенциальный клиент
    NEGOTIATION = "negotiation"  # Переговоры
    PROPOSAL = "proposal"        # КП отправлено
    CONTRACT = "contract"        # Договор
    ACTIVE = "active"            # В работе
    COMPLETED = "completed"      # Завершено
    LOST = "lost"                # Потеряно

class ContentStatus(PyEnum):
    PLANNED = "planned"      # Запланировано
    IN_PROGRESS = "progress" # В работе
    REVIEW = "review"        # На проверке
    PUBLISHED = "published"  # Опубликовано
    CANCELLED = "cancelled"  # Отменено

class ContentType(PyEnum):
    PODCAST = "podcast"
    REEL = "reel"
    VIDEO = "video"
    STORY = "story"
    POST = "post"
    CIRCLE = "circle"       # Telegram кружок
    NEWS = "news"
    SHORTS = "shorts"

class Platform(PyEnum):
    INSTAGRAM = "instagram"
    YOUTUBE = "youtube"
    TELEGRAM = "telegram"
    TIKTOK = "tiktok"

class TaskPriority(PyEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"

class TaskStatus(PyEnum):
    TODO = "todo"
    IN_PROGRESS = "progress"
    DONE = "done"
    CANCELLED = "cancelled"

class FinanceType(PyEnum):
    INCOME = "income"
    EXPENSE = "expense"

# ==================== MODELS ====================

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    username = Column(String(100))
    full_name = Column(String(200), nullable=False)
    role = Column(Enum(UserRole), default=UserRole.MEMBER)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    
    # Relationships
    assigned_content = relationship("ContentPlan", back_populates="assignee", foreign_keys="ContentPlan.assignee_id")
    assigned_tasks = relationship("Task", back_populates="assignee", foreign_keys="Task.assignee_id")
    created_tasks = relationship("Task", back_populates="creator", foreign_keys="Task.creator_id")
    finance_records = relationship("Finance", back_populates="created_by_user")

    def __repr__(self):
        return f"<User {self.full_name} ({self.role.value})>"


class Project(Base):
    """Проекты ZBS: подкаст, новости, Plan Banan и т.д."""
    __tablename__ = "projects"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    emoji = Column(String(10), default="📁")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    
    # Relationships
    content_plans = relationship("ContentPlan", back_populates="project")
    deals = relationship("Deal", back_populates="project")
    tasks = relationship("Task", back_populates="project")
    finances = relationship("Finance", back_populates="project")


class Client(Base):
    """Клиенты: Pepsi, UzAuto, HONOR и т.д."""
    __tablename__ = "clients"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    contact_person = Column(String(200))
    contact_phone = Column(String(50))
    contact_telegram = Column(String(100))
    notes = Column(Text)
    is_active = Column(Boolean, default=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, server_default=func.now())
    
    # Relationships
    deals = relationship("Deal", back_populates="client")
    creator = relationship("User", foreign_keys=[created_by_user_id])


class Deal(Base):
    """Сделки с клиентами"""
    __tablename__ = "deals"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(300), nullable=False)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id"))
    status = Column(Enum(DealStatus), default=DealStatus.LEAD)
    amount = Column(Float, default=0)  # в USD
    currency = Column(String(10), default="USD")
    description = Column(Text)
    deadline = Column(Date)
    created_by_user_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    # Relationships
    client = relationship("Client", back_populates="deals")
    project = relationship("Project", back_populates="deals")
    content_plans = relationship("ContentPlan", back_populates="deal")
    creator = relationship("User", foreign_keys=[created_by_user_id])

    __table_args__ = (
        Index("idx_deal_status", "status"),
    )


class ContentAssignee(Base):
    """Many-to-many: tasks <-> users"""
    __tablename__ = "content_assignees"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    content_id = Column(Integer, ForeignKey("content_plan.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    __table_args__ = (
        UniqueConstraint("content_id", "user_id", name="uq_content_user"),
        Index("idx_ca_content", "content_id"),
        Index("idx_ca_user", "user_id"),
    )


class TaskAttachment(Base):
    """Photos, voice, files attached to tasks"""
    __tablename__ = "task_attachments"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    content_id = Column(Integer, ForeignKey("content_plan.id", ondelete="CASCADE"), nullable=False)
    file_id = Column(String(500), nullable=False)  # Telegram file_id
    file_type = Column(String(20), nullable=False)  # photo, voice, video, document
    caption = Column(Text)
    uploaded_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, server_default=func.now())
    
    # Relationships
    content = relationship("ContentPlan", backref="attachments")
    uploader = relationship("User", foreign_keys=[uploaded_by])
        Index("idx_ca_user", "user_id"),
    )


class ContentPlan(Base):
    """Контент-календарь"""
    __tablename__ = "content_plan"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(300), nullable=False)
    content_type = Column(Enum(ContentType), nullable=False)
    platform = Column(Enum(Platform), nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id"))
    deal_id = Column(Integer, ForeignKey("deals.id"))
    assignee_id = Column(Integer, ForeignKey("users.id"))  # legacy, kept for compat
    created_by_user_id = Column(Integer, ForeignKey("users.id"))
    
    scheduled_date = Column(Date, nullable=False)
    scheduled_time = Column(Time)
    status = Column(Enum(ContentStatus), default=ContentStatus.PLANNED)
    description = Column(Text)
    
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    # Relationships
    project = relationship("Project", back_populates="content_plans")
    deal = relationship("Deal", back_populates="content_plans")
    assignee = relationship("User", back_populates="assigned_content", foreign_keys=[assignee_id])
    creator = relationship("User", foreign_keys=[created_by_user_id])
    assignees = relationship("User", secondary="content_assignees", lazy="selectin")

    __table_args__ = (
        Index("idx_content_date", "scheduled_date"),
        Index("idx_content_assignee", "assignee_id"),
    )


class Task(Base):
    """Задачи команды"""
    __tablename__ = "tasks"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(500), nullable=False)
    description = Column(Text)
    project_id = Column(Integer, ForeignKey("projects.id"))
    assignee_id = Column(Integer, ForeignKey("users.id"))
    creator_id = Column(Integer, ForeignKey("users.id"))
    
    priority = Column(Enum(TaskPriority), default=TaskPriority.MEDIUM)
    status = Column(Enum(TaskStatus), default=TaskStatus.TODO)
    deadline = Column(DateTime)
    completed_at = Column(DateTime)
    
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    # Relationships
    project = relationship("Project", back_populates="tasks")
    assignee = relationship("User", back_populates="assigned_tasks", foreign_keys=[assignee_id])
    creator = relationship("User", back_populates="created_tasks", foreign_keys=[creator_id])

    __table_args__ = (
        Index("idx_task_assignee", "assignee_id"),
        Index("idx_task_deadline", "deadline"),
        Index("idx_task_status", "status"),
    )


class Finance(Base):
    """Финансовые записи"""
    __tablename__ = "finances"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    type = Column(Enum(FinanceType), nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String(10), default="USD")
    category = Column(String(100))
    description = Column(Text)
    project_id = Column(Integer, ForeignKey("projects.id"))
    deal_id = Column(Integer, ForeignKey("deals.id"))
    created_by = Column(Integer, ForeignKey("users.id"))
    
    record_date = Column(Date, nullable=False, server_default=func.current_date())
    created_at = Column(DateTime, server_default=func.now())
    
    # Relationships
    project = relationship("Project", back_populates="finances")
    created_by_user = relationship("User", back_populates="finance_records")

    __table_args__ = (
        Index("idx_finance_date", "record_date"),
        Index("idx_finance_project", "project_id"),
    )


# ==================== DATABASE ENGINE ====================

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/zbs_crm")

# Fix Railway's postgres:// -> postgresql+asyncpg://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(DATABASE_URL, echo=False, pool_size=10, max_overflow=20)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    """Create all tables"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✅ Database tables created")


async def seed_defaults():
    """Seed default projects"""
    async with async_session() as session:
        # Check if projects exist
        result = await session.execute(text("SELECT COUNT(*) FROM projects"))
        count = result.scalar()
        if count > 0:
            return
        
        defaults = [
            Project(name="ZBS Podcast", emoji="🎙", description="Подкасты и интервью"),
            Project(name="ZBS Newz RU", emoji="📰", description="Новости на русском"),
            Project(name="ZBS Newz UZ", emoji="📰", description="Новости на узбекском"),
            Project(name="ZBS YouTube", emoji="🎬", description="YouTube контент"),
            Project(name="Plan Banan", emoji="🍌", description="Детская анимация"),
            Project(name="#SaveCharvak", emoji="🏔", description="Экологический проект"),
            Project(name="Коммерция", emoji="💼", description="Коммерческие проекты"),
        ]
        session.add_all(defaults)
        await session.commit()
        print("✅ Default projects seeded")


async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session
