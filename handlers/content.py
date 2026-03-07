"""
ZBS CRM Bot — Content Calendar Handlers
Create, view, manage content plan
"""

from datetime import date, datetime, timedelta
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload

from database import (
    async_session, ContentPlan, ContentType, ContentStatus, 
    Platform, Project, User
)
from keyboards import (
    content_menu_kb, content_type_kb, platform_kb, content_status_kb,
    project_select_kb, user_select_kb, back_to_menu_kb, skip_kb
)

router = Router()


# ==================== FSM States ====================

class AddContent(StatesGroup):
    title = State()
    content_type = State()
    platform = State()
    project = State()
    assignee = State()
    date = State()
    time = State()
    description = State()


# ==================== Helpers ====================

STATUS_EMOJI = {
    ContentStatus.PLANNED: "📝",
    ContentStatus.IN_PROGRESS: "🔄",
    ContentStatus.REVIEW: "👀",
    ContentStatus.PUBLISHED: "✅",
    ContentStatus.CANCELLED: "❌",
}

TYPE_EMOJI = {
    ContentType.PODCAST: "🎙",
    ContentType.REEL: "📱",
    ContentType.VIDEO: "🎬",
    ContentType.POST: "📰",
    ContentType.CIRCLE: "⭕",
    ContentType.NEWS: "📰",
    ContentType.SHORTS: "🎬",
    ContentType.STORY: "📸",
}

PLATFORM_EMOJI = {
    Platform.INSTAGRAM: "📸",
    Platform.YOUTUBE: "▶️",
    Platform.TELEGRAM: "✈️",
    Platform.TIKTOK: "🎵",
}


def format_content_item(c: ContentPlan, show_assignee: bool = True) -> str:
    """Format a single content plan item"""
    status = STATUS_EMOJI.get(c.status, "❓")
    ctype = TYPE_EMOJI.get(c.content_type, "📄")
    platform = PLATFORM_EMOJI.get(c.platform, "🌐")
    
    time_str = c.scheduled_time.strftime("%H:%M") if c.scheduled_time else ""
    assignee_str = ""
    if show_assignee and c.assignee:
        assignee_str = f" → {c.assignee.full_name}"
    
    project_str = ""
    if c.project:
        project_str = f" [{c.project.emoji} {c.project.name}]"
    
    return f"{status} {time_str} {ctype}{platform} <b>{c.title}</b>{assignee_str}{project_str}"


# ==================== Content Menu ====================

@router.callback_query(F.data == "menu:content")
async def content_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "📅 <b>Контент-календарь</b>\n\nВыбери действие:",
        reply_markup=content_menu_kb(),
        parse_mode="HTML"
    )
    await callback.answer()


# ==================== Today's Content ====================

@router.callback_query(F.data == "content:today")
async def content_today(callback: CallbackQuery):
    today = date.today()
    
    async with async_session() as session:
        result = await session.execute(
            select(ContentPlan)
            .options(selectinload(ContentPlan.assignee), selectinload(ContentPlan.project))
            .where(ContentPlan.scheduled_date == today)
            .order_by(ContentPlan.scheduled_time.asc().nulls_last(), ContentPlan.id)
        )
        items = result.scalars().all()
    
    if not items:
        text = f"📅 <b>Контент на {today.strftime('%d.%m.%Y')}</b>\n\n🤷 Ничего не запланировано"
    else:
        lines = [f"📅 <b>Контент на {today.strftime('%d.%m.%Y')}</b>\n"]
        for c in items:
            lines.append(format_content_item(c))
        
        published = sum(1 for c in items if c.status == ContentStatus.PUBLISHED)
        lines.append(f"\n📊 Готово: {published}/{len(items)}")
        text = "\n".join(lines)
    
    # Add buttons for each item to change status
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    
    builder = InlineKeyboardBuilder()
    for c in items:
        if c.status != ContentStatus.PUBLISHED:
            builder.row(InlineKeyboardButton(
                text=f"✏️ {c.title[:30]}",
                callback_data=f"cedit:{c.id}"
            ))
    builder.row(
        InlineKeyboardButton(text="➕ Добавить", callback_data="content:add"),
        InlineKeyboardButton(text="◀️ Назад", callback_data="menu:content"),
    )
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()


# ==================== /today command ====================

@router.message(Command("today"))
async def cmd_today(message: Message):
    today = date.today()
    
    async with async_session() as session:
        result = await session.execute(
            select(ContentPlan)
            .options(selectinload(ContentPlan.assignee), selectinload(ContentPlan.project))
            .where(ContentPlan.scheduled_date == today)
            .order_by(ContentPlan.scheduled_time.asc().nulls_last(), ContentPlan.id)
        )
        items = result.scalars().all()
    
    if not items:
        await message.answer(f"📅 Сегодня ({today.strftime('%d.%m')}) ничего не запланировано", reply_markup=content_menu_kb())
        return
    
    lines = [f"📅 <b>Контент на сегодня ({today.strftime('%d.%m')})</b>\n"]
    for c in items:
        lines.append(format_content_item(c))
    
    published = sum(1 for c in items if c.status == ContentStatus.PUBLISHED)
    lines.append(f"\n📊 Готово: {published}/{len(items)}")
    
    await message.answer("\n".join(lines), reply_markup=content_menu_kb(), parse_mode="HTML")


# ==================== Week View ====================

@router.callback_query(F.data == "content:week")
async def content_week(callback: CallbackQuery):
    today = date.today()
    week_end = today + timedelta(days=6)
    
    async with async_session() as session:
        result = await session.execute(
            select(ContentPlan)
            .options(selectinload(ContentPlan.assignee), selectinload(ContentPlan.project))
            .where(and_(
                ContentPlan.scheduled_date >= today,
                ContentPlan.scheduled_date <= week_end
            ))
            .order_by(ContentPlan.scheduled_date, ContentPlan.scheduled_time.asc().nulls_last())
        )
        items = result.scalars().all()
    
    if not items:
        text = f"📅 <b>Неделя {today.strftime('%d.%m')} — {week_end.strftime('%d.%m')}</b>\n\n🤷 Ничего не запланировано"
    else:
        days_map = {}
        for c in items:
            d = c.scheduled_date
            if d not in days_map:
                days_map[d] = []
            days_map[d].append(c)
        
        lines = [f"📅 <b>Неделя {today.strftime('%d.%m')} — {week_end.strftime('%d.%m')}</b>\n"]
        
        weekdays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        current = today
        while current <= week_end:
            day_name = weekdays[current.weekday()]
            is_today = " (сегодня)" if current == today else ""
            items_today = days_map.get(current, [])
            
            if items_today:
                lines.append(f"\n<b>📆 {day_name} {current.strftime('%d.%m')}{is_today}</b>")
                for c in items_today:
                    lines.append(f"  {format_content_item(c)}")
            else:
                lines.append(f"\n📆 {day_name} {current.strftime('%d.%m')}{is_today} — пусто")
            
            current += timedelta(days=1)
        
        total = len(items)
        published = sum(1 for c in items if c.status == ContentStatus.PUBLISHED)
        lines.append(f"\n📊 Итого: {total} | Готово: {published}")
        text = "\n".join(lines)
    
    await callback.message.edit_text(text, reply_markup=content_menu_kb(), parse_mode="HTML")
    await callback.answer()


# ==================== My Content ====================

@router.callback_query(F.data == "content:my")
async def content_my(callback: CallbackQuery):
    async with async_session() as session:
        # Find user
        result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user = result.scalar_one_or_none()
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return
        
        # Get upcoming content
        result = await session.execute(
            select(ContentPlan)
            .options(selectinload(ContentPlan.project))
            .where(and_(
                ContentPlan.assignee_id == user.id,
                ContentPlan.status.in_([ContentStatus.PLANNED, ContentStatus.IN_PROGRESS, ContentStatus.REVIEW])
            ))
            .order_by(ContentPlan.scheduled_date, ContentPlan.scheduled_time.asc().nulls_last())
            .limit(20)
        )
        items = result.scalars().all()
    
    if not items:
        text = "📝 <b>Мой контент</b>\n\n✨ У тебя нет активных задач по контенту"
    else:
        lines = ["📝 <b>Мой контент</b>\n"]
        for c in items:
            lines.append(format_content_item(c, show_assignee=False))
        text = "\n".join(lines)
    
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    builder = InlineKeyboardBuilder()
    for c in items:
        builder.row(InlineKeyboardButton(
            text=f"✏️ {c.title[:30]} ({c.scheduled_date.strftime('%d.%m')})",
            callback_data=f"cedit:{c.id}"
        ))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="menu:content"))
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()


# ==================== Edit Content Status ====================

@router.callback_query(F.data.startswith("cedit:"))
async def content_edit(callback: CallbackQuery):
    content_id = int(callback.data.split(":")[1])
    
    async with async_session() as session:
        result = await session.execute(
            select(ContentPlan)
            .options(selectinload(ContentPlan.assignee), selectinload(ContentPlan.project))
            .where(ContentPlan.id == content_id)
        )
        c = result.scalar_one_or_none()
    
    if not c:
        await callback.answer("Контент не найден", show_alert=True)
        return
    
    text = (
        f"📄 <b>{c.title}</b>\n\n"
        f"Тип: {TYPE_EMOJI.get(c.content_type, '📄')} {c.content_type.value}\n"
        f"Платформа: {PLATFORM_EMOJI.get(c.platform, '🌐')} {c.platform.value}\n"
        f"Дата: {c.scheduled_date.strftime('%d.%m.%Y')}\n"
        f"Статус: {STATUS_EMOJI.get(c.status, '❓')} {c.status.value}\n"
    )
    if c.assignee:
        text += f"Ответственный: {c.assignee.full_name}\n"
    if c.project:
        text += f"Проект: {c.project.emoji} {c.project.name}\n"
    if c.description:
        text += f"\n📎 {c.description}\n"
    
    text += "\n<b>Изменить статус:</b>"
    
    await callback.message.edit_text(
        text,
        reply_markup=content_status_kb(content_id),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("cstatus:"))
async def content_change_status(callback: CallbackQuery):
    parts = callback.data.split(":")
    content_id = int(parts[1])
    new_status = ContentStatus(parts[2])
    
    async with async_session() as session:
        result = await session.execute(
            select(ContentPlan).where(ContentPlan.id == content_id)
        )
        c = result.scalar_one_or_none()
        if c:
            c.status = new_status
            await session.commit()
    
    status_name = STATUS_EMOJI.get(new_status, "") + " " + new_status.value
    await callback.answer(f"Статус изменён: {status_name}", show_alert=True)
    
    # Refresh today view
    await content_today(callback)


# ==================== Add Content ====================

@router.callback_query(F.data == "content:add")
@router.message(Command("addcontent"))
async def content_add_start(event, state: FSMContext):
    await state.set_state(AddContent.title)
    text = "📝 <b>Новый контент</b>\n\nВведи название/тему:"
    
    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, parse_mode="HTML")
        await event.answer()
    else:
        await event.answer(text, parse_mode="HTML")


@router.message(AddContent.title)
async def content_add_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text)
    await state.set_state(AddContent.content_type)
    await message.answer("Выбери тип контента:", reply_markup=content_type_kb())


@router.callback_query(F.data.startswith("ctype:"), AddContent.content_type)
async def content_add_type(callback: CallbackQuery, state: FSMContext):
    ctype = callback.data.split(":")[1]
    await state.update_data(content_type=ctype)
    await state.set_state(AddContent.platform)
    await callback.message.edit_text("Выбери платформу:", reply_markup=platform_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("platform:"), AddContent.platform)
async def content_add_platform(callback: CallbackQuery, state: FSMContext):
    platform = callback.data.split(":")[1]
    await state.update_data(platform=platform)
    await state.set_state(AddContent.project)
    
    async with async_session() as session:
        result = await session.execute(select(Project).where(Project.is_active == True))
        projects = result.scalars().all()
    
    await callback.message.edit_text(
        "Выбери проект:",
        reply_markup=project_select_kb(projects, "cproject")
    )
    await callback.answer()


@router.callback_query(F.data.startswith("cproject:"), AddContent.project)
async def content_add_project(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split(":")[1]
    project_id = None if val == "skip" else int(val)
    await state.update_data(project_id=project_id)
    await state.set_state(AddContent.assignee)
    
    async with async_session() as session:
        result = await session.execute(select(User).where(User.is_active == True).order_by(User.full_name))
        users = result.scalars().all()
    
    await callback.message.edit_text(
        "Кто ответственный?",
        reply_markup=user_select_kb(users, "cassign")
    )
    await callback.answer()


@router.callback_query(F.data.startswith("cassign:"), AddContent.assignee)
async def content_add_assignee(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split(":")[1]
    assignee_id = None if val == "skip" else int(val)
    await state.update_data(assignee_id=assignee_id)
    await state.set_state(AddContent.date)
    
    # Quick date buttons
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    
    today = date.today()
    builder = InlineKeyboardBuilder()
    for i in range(7):
        d = today + timedelta(days=i)
        weekdays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        label = "Сегодня" if i == 0 else "Завтра" if i == 1 else f"{weekdays[d.weekday()]} {d.strftime('%d.%m')}"
        builder.row(InlineKeyboardButton(text=label, callback_data=f"cdate:{d.isoformat()}"))
    
    await callback.message.edit_text(
        "📅 Выбери дату публикации:",
        reply_markup=builder.as_markup()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("cdate:"), AddContent.date)
async def content_add_date(callback: CallbackQuery, state: FSMContext):
    date_str = callback.data.split(":")[1]
    await state.update_data(scheduled_date=date_str)
    await state.set_state(AddContent.time)
    
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    
    builder = InlineKeyboardBuilder()
    times = ["08:00", "10:00", "12:00", "14:00", "16:00", "18:00", "20:00"]
    for i in range(0, len(times), 3):
        row = [InlineKeyboardButton(text=t, callback_data=f"ctime:{t}") for t in times[i:i+3]]
        builder.row(*row)
    builder.row(InlineKeyboardButton(text="⏭ Без времени", callback_data="ctime:skip"))
    
    await callback.message.edit_text("🕐 Время публикации:", reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("ctime:"), AddContent.time)
async def content_add_time(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split(":")[1]
    scheduled_time = None if val == "skip" else val
    await state.update_data(scheduled_time=scheduled_time)
    await state.set_state(AddContent.description)
    
    await callback.message.edit_text(
        "📎 Описание/комментарий (или нажми пропустить):",
        reply_markup=skip_kb("cdesc:skip")
    )
    await callback.answer()


@router.callback_query(F.data == "cdesc:skip", AddContent.description)
async def content_add_desc_skip(callback: CallbackQuery, state: FSMContext):
    await state.update_data(description=None)
    await _save_content(callback.message, state, callback)


@router.message(AddContent.description)
async def content_add_desc(message: Message, state: FSMContext):
    await state.update_data(description=message.text)
    await _save_content(message, state)


async def _save_content(message: Message, state: FSMContext, callback: CallbackQuery = None):
    data = await state.get_data()
    await state.clear()
    
    from datetime import time as dt_time
    
    scheduled_time = None
    if data.get("scheduled_time"):
        h, m = map(int, data["scheduled_time"].split(":"))
        scheduled_time = dt_time(h, m)
    
    async with async_session() as session:
        content = ContentPlan(
            title=data["title"],
            content_type=ContentType(data["content_type"]),
            platform=Platform(data["platform"]),
            project_id=data.get("project_id"),
            assignee_id=data.get("assignee_id"),
            scheduled_date=date.fromisoformat(data["scheduled_date"]),
            scheduled_time=scheduled_time,
            description=data.get("description"),
            status=ContentStatus.PLANNED,
        )
        session.add(content)
        await session.commit()
        await session.refresh(content)
        
        # Load relations for display
        result = await session.execute(
            select(ContentPlan)
            .options(selectinload(ContentPlan.assignee), selectinload(ContentPlan.project))
            .where(ContentPlan.id == content.id)
        )
        content = result.scalar_one()
    
    text = (
        f"✅ <b>Контент добавлен!</b>\n\n"
        f"{format_content_item(content)}\n"
        f"📅 {content.scheduled_date.strftime('%d.%m.%Y')}"
    )
    
    target = callback.message if callback else message
    if callback:
        await target.edit_text(text, reply_markup=content_menu_kb(), parse_mode="HTML")
        await callback.answer()
    else:
        await target.answer(text, reply_markup=content_menu_kb(), parse_mode="HTML")


# ==================== Cancel ====================

@router.callback_query(F.data == "content:cancel")
async def content_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "❌ Отменено",
        reply_markup=content_menu_kb()
    )
    await callback.answer()
