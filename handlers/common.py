"""
ZBS CRM Bot — Common Handlers
Start, registration, main menu
"""

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from sqlalchemy import select

from database import async_session, User, UserRole, Project
from keyboards import main_menu_kb, admin_menu_kb, back_to_menu_kb

router = Router()

# Admin Telegram IDs (Robert + Susanna)
ADMIN_IDS = set()  # Will be populated from env


async def get_or_create_user(telegram_id: int, username: str = None, full_name: str = "Unknown") -> User:
    """Get existing user or create new one. Auto-links pre-seeded team members."""
    async with async_session() as session:
        # 1. Try by telegram_id
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()
        
        if user:
            if username and user.username != username:
                user.username = username
                await session.commit()
            return user
        
        # 2. Try to link pre-seeded user by username
        if username:
            result = await session.execute(
                select(User).where(User.username == username, User.telegram_id == 0)
            )
            user = result.scalar_one_or_none()
            if user:
                user.telegram_id = telegram_id
                user.full_name = full_name  # update to real TG name
                await session.commit()
                return user
        
        # 3. Create new user
        role = UserRole.ADMIN if telegram_id in ADMIN_IDS else UserRole.MEMBER
        user = User(
            telegram_id=telegram_id,
            username=username,
            full_name=full_name,
            role=role,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


# ==================== /start ====================

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    user = await get_or_create_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        full_name=message.from_user.full_name,
    )
    
    role_text = {
        UserRole.ADMIN: "👑 Админ",
        UserRole.MANAGER: "📋 Менеджер",
        UserRole.MEMBER: "👤 Участник",
    }
    
    welcome = (
        f"👋 Привет, {user.full_name}!\n\n"
        f"Это CRM-бот ZBS Media.\n"
        f"Роль: {role_text.get(user.role, '👤 Участник')}\n\n"
        f"Выбери раздел:"
    )
    await message.answer(welcome, reply_markup=main_menu_kb(user.role, user.username or ""), parse_mode="HTML")


# ==================== Main Menu ====================

@router.callback_query(F.data == "menu:main")
async def menu_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user = await get_or_create_user(
        telegram_id=callback.from_user.id,
        username=callback.from_user.username,
        full_name=callback.from_user.full_name,
    )
    await callback.message.edit_text(
        "🏠 Главное меню ZBS CRM\n\nВыбери раздел:",
        reply_markup=main_menu_kb(user.role, user.username or "")
    )
    await callback.answer()


# ==================== /menu ====================

@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext):
    await state.clear()
    user = await get_or_create_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        full_name=message.from_user.full_name,
    )
    await message.answer("🏠 Главное меню:", reply_markup=main_menu_kb(user.role, user.username or ""))


# ==================== /help ====================

@router.message(Command("help"))
async def cmd_help(message: Message):
    text = (
        "📖 <b>Команды ZBS CRM Bot</b>\n\n"
        "/start — Запуск бота\n"
        "/menu — Главное меню\n"
        "/today — Расписание на сегодня\n"
        "/mytasks — Мои задачи\n"
        "/addtask — Добавить задачу\n"
        "/report — Отчёт дня\n"
        "/help — Эта справка\n"
    )
    await message.answer(text, parse_mode="HTML")


# ==================== Admin Menu ====================

@router.callback_query(F.data == "menu:admin")
async def menu_admin(callback: CallbackQuery):
    user = await get_or_create_user(
        telegram_id=callback.from_user.id,
        username=callback.from_user.username,
        full_name=callback.from_user.full_name,
    )
    if user.role not in (UserRole.ADMIN, UserRole.MANAGER):
        await callback.answer("⛔ Нет доступа")
        return
    
    await callback.message.edit_text(
        "⚙️ <b>Управление</b>\n\nВыбери раздел:",
        reply_markup=admin_menu_kb(),
        parse_mode="HTML"
    )
    await callback.answer()


# ==================== Admin: Team ====================

@router.callback_query(F.data == "admin:team")
async def admin_team(callback: CallbackQuery):
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.is_active == True).order_by(User.role, User.full_name)
        )
        users = result.scalars().all()
    
    role_emoji = {
        UserRole.ADMIN: "👑",
        UserRole.MANAGER: "📋",
        UserRole.MEMBER: "👤",
    }
    
    lines = ["👥 <b>Команда ZBS</b>\n"]
    for u in users:
        emoji = role_emoji.get(u.role, "👤")
        username = f" @{u.username}" if u.username else ""
        lines.append(f"{emoji} {u.full_name}{username}")
    
    lines.append(f"\n📊 Всего: {len(users)} человек")
    
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=back_to_menu_kb(),
        parse_mode="HTML"
    )
    await callback.answer()


# ==================== Admin: Projects ====================

@router.callback_query(F.data == "admin:projects")
async def admin_projects(callback: CallbackQuery):
    async with async_session() as session:
        result = await session.execute(
            select(Project).where(Project.is_active == True).order_by(Project.name)
        )
        projects = result.scalars().all()
    
    lines = ["📁 <b>Проекты ZBS</b>\n"]
    for p in projects:
        lines.append(f"{p.emoji} {p.name}")
        if p.description:
            lines.append(f"   <i>{p.description[:50]}</i>")
    
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="➕ Новый проект", callback_data="admin:add_project"))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="menu:admin"))
    
    await callback.message.edit_text("\n".join(lines), reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()


from aiogram.fsm.state import State, StatesGroup as SG

class AddProject(SG):
    name = State()
    emoji = State()


@router.callback_query(F.data == "admin:add_project")
async def admin_add_project(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AddProject.name)
    await callback.message.edit_text("📁 Название нового проекта:")
    await callback.answer()


@router.message(AddProject.name)
async def admin_project_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(AddProject.emoji)
    
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    emojis = ["📁", "🎙", "📰", "🎬", "🎵", "📸", "💼", "🏔", "🍌", "⚡"]
    builder = InlineKeyboardBuilder()
    for i in range(0, len(emojis), 5):
        row = [InlineKeyboardButton(text=e, callback_data=f"projemoji:{e}") for e in emojis[i:i+5]]
        builder.row(*row)
    
    await message.answer("Выбери иконку:", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("projemoji:"), AddProject.emoji)
async def admin_project_emoji(callback: CallbackQuery, state: FSMContext):
    emoji = callback.data.split(":", 1)[1]
    data = await state.get_data()
    await state.clear()
    
    async with async_session() as session:
        project = Project(name=data["name"], emoji=emoji)
        session.add(project)
        await session.commit()
    
    await callback.answer(f"✅ Проект {emoji} {data['name']} создан!")
    await admin_projects(callback)

@router.callback_query(F.data == "admin:stats")
async def admin_stats(callback: CallbackQuery):
    from sqlalchemy import func
    from database import ContentPlan, Deal, Finance, ContentStatus, DealStatus, FinanceType
    from datetime import date
    
    today = date.today()
    month_start = today.replace(day=1)
    
    try:
        async with async_session() as session:
            ct = (await session.execute(select(func.count(ContentPlan.id)).where(ContentPlan.scheduled_date >= month_start))).scalar() or 0
            cp = (await session.execute(select(func.count(ContentPlan.id)).where(ContentPlan.scheduled_date >= month_start, ContentPlan.status == ContentStatus.PUBLISHED))).scalar() or 0
            
            open_tasks = (await session.execute(select(func.count(ContentPlan.id)).where(ContentPlan.status.in_([ContentStatus.PLANNED, ContentStatus.IN_PROGRESS])))).scalar() or 0
            
            ad = (await session.execute(select(func.count(Deal.id)).where(Deal.status.in_([DealStatus.LEAD, DealStatus.NEGOTIATION, DealStatus.PROPOSAL, DealStatus.CONTRACT, DealStatus.ACTIVE])))).scalar() or 0
            ds = (await session.execute(select(func.coalesce(func.sum(Deal.amount), 0)).where(Deal.status.in_([DealStatus.ACTIVE, DealStatus.CONTRACT])))).scalar() or 0
            
            inc = (await session.execute(select(func.coalesce(func.sum(Finance.amount), 0)).where(Finance.type == FinanceType.INCOME, Finance.record_date >= month_start))).scalar() or 0
            exp = (await session.execute(select(func.coalesce(func.sum(Finance.amount), 0)).where(Finance.type == FinanceType.EXPENSE, Finance.record_date >= month_start))).scalar() or 0
        
        text_msg = (
            f"📊 <b>Статистика ZBS — {today.strftime('%B %Y')}</b>\n\n"
            f"📅 <b>Расписание:</b>\n"
            f"   Запланировано: {ct}\n"
            f"   Выполнено: {cp} ({round(cp/ct*100) if ct else 0}%)\n"
            f"   Открытых: {open_tasks}\n\n"
            f"💼 <b>Сделки:</b>\n"
            f"   Активных: {ad}\n"
            f"   В работе на: ${ds:,.0f}\n\n"
            f"💰 <b>Финансы:</b>\n"
            f"   Приход: ${inc:,.0f}\n"
            f"   Расход: ${exp:,.0f}\n"
            f"   Баланс: ${inc - exp:,.0f}"
        )
    except Exception as e:
        text_msg = f"❌ Ошибка:\n<code>{str(e)[:200]}</code>"
    
    await callback.message.edit_text(text_msg, reply_markup=back_to_menu_kb(), parse_mode="HTML")
    await callback.answer()
