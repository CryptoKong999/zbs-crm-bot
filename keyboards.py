"""
ZBS CRM Bot — Keyboards
All inline keyboards and reply keyboards
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database import (
    UserRole, DealStatus, ContentStatus, ContentType, 
    Platform, TaskPriority, TaskStatus, FinanceType
)


# ==================== MAIN MENU ====================

def main_menu_kb(role: UserRole = UserRole.MEMBER) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📅 Контент", callback_data="menu:content"),
        InlineKeyboardButton(text="👥 Клиенты", callback_data="menu:clients"),
    )
    builder.row(
        InlineKeyboardButton(text="📋 Задачи", callback_data="menu:tasks"),
        InlineKeyboardButton(text="💰 Финансы", callback_data="menu:finance"),
    )
    builder.row(
        InlineKeyboardButton(text="📊 Отчёт дня", callback_data="menu:report"),
    )
    if role in (UserRole.ADMIN, UserRole.MANAGER):
        builder.row(
            InlineKeyboardButton(text="⚙️ Управление", callback_data="menu:admin"),
        )
    return builder.as_markup()


def back_to_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Главное меню", callback_data="menu:main")]
    ])


# ==================== CONTENT CALENDAR ====================

def content_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📆 Сегодня", callback_data="content:today"),
        InlineKeyboardButton(text="📅 Неделя", callback_data="content:week"),
    )
    builder.row(
        InlineKeyboardButton(text="📝 Мой контент", callback_data="content:my"),
        InlineKeyboardButton(text="➕ Добавить", callback_data="content:add"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="menu:main"),
    )
    return builder.as_markup()


def content_type_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    types = [
        ("🎙 Подкаст", ContentType.PODCAST.value),
        ("🎬 Видео", ContentType.VIDEO.value),
        ("📱 Reels", ContentType.REEL.value),
        ("📰 Пост", ContentType.POST.value),
        ("⭕ Кружок", ContentType.CIRCLE.value),
        ("📰 Новость", ContentType.NEWS.value),
        ("🎬 Shorts", ContentType.SHORTS.value),
        ("📸 Stories", ContentType.STORY.value),
    ]
    for i in range(0, len(types), 2):
        row = [InlineKeyboardButton(text=t[0], callback_data=f"ctype:{t[1]}") for t in types[i:i+2]]
        builder.row(*row)
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="content:cancel"))
    return builder.as_markup()


def platform_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    platforms = [
        ("📸 Instagram", Platform.INSTAGRAM.value),
        ("▶️ YouTube", Platform.YOUTUBE.value),
        ("✈️ Telegram", Platform.TELEGRAM.value),
        ("🎵 TikTok", Platform.TIKTOK.value),
    ]
    for i in range(0, len(platforms), 2):
        row = [InlineKeyboardButton(text=p[0], callback_data=f"platform:{p[1]}") for p in platforms[i:i+2]]
        builder.row(*row)
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="content:cancel"))
    return builder.as_markup()


def content_status_kb(content_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    statuses = [
        ("📝 План", ContentStatus.PLANNED.value),
        ("🔄 В работе", ContentStatus.IN_PROGRESS.value),
        ("👀 Проверка", ContentStatus.REVIEW.value),
        ("✅ Опубликовано", ContentStatus.PUBLISHED.value),
        ("❌ Отменено", ContentStatus.CANCELLED.value),
    ]
    for s in statuses:
        builder.row(InlineKeyboardButton(text=s[0], callback_data=f"cstatus:{content_id}:{s[1]}"))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="content:today"))
    return builder.as_markup()


# ==================== CRM / CLIENTS ====================

def clients_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📋 Все клиенты", callback_data="clients:list"),
        InlineKeyboardButton(text="➕ Новый клиент", callback_data="clients:add"),
    )
    builder.row(
        InlineKeyboardButton(text="💼 Сделки", callback_data="deals:list"),
        InlineKeyboardButton(text="➕ Новая сделка", callback_data="deals:add"),
    )
    builder.row(
        InlineKeyboardButton(text="📊 Pipeline", callback_data="deals:pipeline"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="menu:main"),
    )
    return builder.as_markup()


def deal_status_kb(deal_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    statuses = [
        ("🔵 Лид", DealStatus.LEAD.value),
        ("🟡 Переговоры", DealStatus.NEGOTIATION.value),
        ("📄 КП отправлено", DealStatus.PROPOSAL.value),
        ("📝 Договор", DealStatus.CONTRACT.value),
        ("🟢 В работе", DealStatus.ACTIVE.value),
        ("✅ Завершено", DealStatus.COMPLETED.value),
        ("🔴 Потеряно", DealStatus.LOST.value),
    ]
    for s in statuses:
        builder.row(InlineKeyboardButton(text=s[0], callback_data=f"dstatus:{deal_id}:{s[1]}"))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="deals:list"))
    return builder.as_markup()


def client_select_kb(clients: list, action: str = "deal_client") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for c in clients:
        builder.row(InlineKeyboardButton(text=c.name, callback_data=f"{action}:{c.id}"))
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="menu:clients"))
    return builder.as_markup()


# ==================== TASKS ====================

def tasks_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📋 Мои задачи", callback_data="tasks:my"),
        InlineKeyboardButton(text="📋 Все задачи", callback_data="tasks:all"),
    )
    builder.row(
        InlineKeyboardButton(text="➕ Создать", callback_data="tasks:add"),
        InlineKeyboardButton(text="🔥 Срочные", callback_data="tasks:urgent"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="menu:main"),
    )
    return builder.as_markup()


def task_priority_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    priorities = [
        ("🟢 Низкий", TaskPriority.LOW.value),
        ("🟡 Средний", TaskPriority.MEDIUM.value),
        ("🟠 Высокий", TaskPriority.HIGH.value),
        ("🔴 Срочно", TaskPriority.URGENT.value),
    ]
    for p in priorities:
        builder.row(InlineKeyboardButton(text=p[0], callback_data=f"tpriority:{p[1]}"))
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="tasks:cancel"))
    return builder.as_markup()


def task_action_kb(task_id: int, is_assignee: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if is_assignee:
        builder.row(
            InlineKeyboardButton(text="▶️ В работу", callback_data=f"tstatus:{task_id}:progress"),
            InlineKeyboardButton(text="✅ Готово", callback_data=f"tstatus:{task_id}:done"),
        )
    builder.row(
        InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"tedit:{task_id}"),
        InlineKeyboardButton(text="❌ Отменить", callback_data=f"tstatus:{task_id}:cancelled"),
    )
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="tasks:my"))
    return builder.as_markup()


def user_select_kb(users: list, action: str = "task_assign") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for u in users:
        label = f"{u.full_name}"
        if u.username:
            label += f" (@{u.username})"
        builder.row(InlineKeyboardButton(text=label, callback_data=f"{action}:{u.id}"))
    builder.row(InlineKeyboardButton(text="⏭ Пропустить", callback_data=f"{action}:skip"))
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="tasks:cancel"))
    return builder.as_markup()


# ==================== FINANCE ====================

def finance_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="💵 Приход", callback_data="fin:add_income"),
        InlineKeyboardButton(text="💸 Расход", callback_data="fin:add_expense"),
    )
    builder.row(
        InlineKeyboardButton(text="📊 За месяц", callback_data="fin:month"),
        InlineKeyboardButton(text="📋 По проектам", callback_data="fin:by_project"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="menu:main"),
    )
    return builder.as_markup()


# ==================== PROJECTS ====================

def project_select_kb(projects: list, action: str = "project") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for p in projects:
        builder.row(InlineKeyboardButton(text=f"{p.emoji} {p.name}", callback_data=f"{action}:{p.id}"))
    builder.row(InlineKeyboardButton(text="⏭ Без проекта", callback_data=f"{action}:skip"))
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel"))
    return builder.as_markup()


# ==================== ADMIN ====================

def admin_menu_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="👥 Команда", callback_data="admin:team"),
        InlineKeyboardButton(text="📁 Проекты", callback_data="admin:projects"),
    )
    builder.row(
        InlineKeyboardButton(text="📊 Статистика", callback_data="admin:stats"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="menu:main"),
    )
    return builder.as_markup()


def user_role_kb(user_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="👤 Участник", callback_data=f"setrole:{user_id}:member"),
        InlineKeyboardButton(text="📋 Менеджер", callback_data=f"setrole:{user_id}:manager"),
        InlineKeyboardButton(text="👑 Админ", callback_data=f"setrole:{user_id}:admin"),
    )
    return builder.as_markup()


# ==================== CONFIRM ====================

def confirm_kb(action: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да", callback_data=f"confirm:{action}"),
            InlineKeyboardButton(text="❌ Нет", callback_data=f"cancel:{action}"),
        ]
    ])


# ==================== SKIP ====================

def skip_kb(callback: str = "skip") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Пропустить", callback_data=callback)]
    ])
