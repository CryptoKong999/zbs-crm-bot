"""
ZBS CRM Bot — Unified Schedule Handler
Simple: title + assignee + date + time + project
No content types, no platforms, no bullshit
"""

from datetime import date, datetime, timedelta, time as dt_time
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import selectinload

from database import (
    async_session, ContentPlan, ContentType, ContentStatus,
    Platform, Project, User, UserRole
)
from keyboards import (
    content_menu_kb, content_status_kb,
    project_select_kb, user_select_kb, back_to_menu_kb, skip_kb
)

router = Router()

STATUS_EMOJI = {
    ContentStatus.PLANNED: "⬜",
    ContentStatus.IN_PROGRESS: "🔄",
    ContentStatus.REVIEW: "👀",
    ContentStatus.PUBLISHED: "✅",
    ContentStatus.CANCELLED: "❌",
}


def format_item(c, show_assignee: bool = True) -> str:
    status = STATUS_EMOJI.get(c.status, "⬜")
    time_str = c.scheduled_time.strftime("%H:%M") if c.scheduled_time else ""
    
    assignee_str = ""
    if show_assignee and c.assignee:
        assignee_str = f" → {c.assignee.full_name}"
    
    project_str = ""
    if c.project:
        project_str = f" [{c.project.emoji}]"
    
    return f"{status} {time_str} <b>{c.title}</b>{assignee_str}{project_str}"


# ==================== FSM ====================

class AddSchedule(StatesGroup):
    title = State()
    assignee = State()
    project = State()
    date = State()
    time = State()
    description = State()


class EditSchedule(StatesGroup):
    date = State()
    time = State()
    assignee = State()
    title = State()
    description = State()


# ==================== Schedule Menu ====================

def schedule_menu_kb():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📆 Сегодня", callback_data="sched:today"),
        InlineKeyboardButton(text="📅 Неделя", callback_data="sched:week"),
    )
    builder.row(
        InlineKeyboardButton(text="📋 Мои задачи", callback_data="sched:my"),
        InlineKeyboardButton(text="➕ Добавить", callback_data="sched:add"),
    )
    builder.row(
        InlineKeyboardButton(text="📅 След. неделя", callback_data="sched:nextweek"),
    )
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="menu:main"),
    )
    return builder.as_markup()


@router.callback_query(F.data == "menu:content")
@router.callback_query(F.data == "menu:tasks")
async def schedule_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "📅 <b>Расписание</b>\n\nВыбери действие:",
        reply_markup=schedule_menu_kb(),
        parse_mode="HTML"
    )
    await callback.answer()


# ==================== Today ====================

@router.callback_query(F.data == "sched:today")
@router.message(Command("today"))
async def sched_today(event, state: FSMContext = None):
    today = date.today()
    
    async with async_session() as session:
        result = await session.execute(
            select(ContentPlan)
            .options(selectinload(ContentPlan.assignee), selectinload(ContentPlan.project))
            .where(ContentPlan.scheduled_date == today)
            .order_by(ContentPlan.scheduled_time.asc().nulls_last(), ContentPlan.id)
        )
        items = result.scalars().all()
    
    weekdays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    day_name = weekdays[today.weekday()]
    
    if not items:
        text = f"📅 <b>{day_name} {today.strftime('%d.%m.%Y')}</b>\n\n🤷 Пусто"
    else:
        lines = [f"📅 <b>{day_name} {today.strftime('%d.%m.%Y')}</b>\n"]
        for c in items:
            lines.append(format_item(c))
        done = sum(1 for c in items if c.status == ContentStatus.PUBLISHED)
        lines.append(f"\n📊 Готово: {done}/{len(items)}")
        text = "\n".join(lines)
    
    builder = InlineKeyboardBuilder()
    for c in items:
        if c.status != ContentStatus.PUBLISHED:
            short = c.title[:25] + "..." if len(c.title) > 25 else c.title
            builder.row(InlineKeyboardButton(text=f"✏️ {short}", callback_data=f"sedit:{c.id}"))
    builder.row(
        InlineKeyboardButton(text="➕ Добавить", callback_data="sched:add"),
        InlineKeyboardButton(text="◀️ Меню", callback_data="menu:content"),
    )
    
    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
        await event.answer()
    else:
        await event.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")


# ==================== Week View ====================

async def _show_week(callback: CallbackQuery, start_date: date, label: str):
    end_date = start_date + timedelta(days=6)
    
    async with async_session() as session:
        result = await session.execute(
            select(ContentPlan)
            .options(selectinload(ContentPlan.assignee), selectinload(ContentPlan.project))
            .where(and_(
                ContentPlan.scheduled_date >= start_date,
                ContentPlan.scheduled_date <= end_date
            ))
            .order_by(ContentPlan.scheduled_date, ContentPlan.scheduled_time.asc().nulls_last())
        )
        items = result.scalars().all()
    
    days_map = {}
    for c in items:
        if c.scheduled_date not in days_map:
            days_map[c.scheduled_date] = []
        days_map[c.scheduled_date].append(c)
    
    weekdays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    today = date.today()
    
    lines = [f"📅 <b>{label}</b>\n"]
    current = start_date
    while current <= end_date:
        day_name = weekdays[current.weekday()]
        is_today = " ← сегодня" if current == today else ""
        day_items = days_map.get(current, [])
        
        if day_items:
            lines.append(f"\n<b>{day_name} {current.strftime('%d.%m')}{is_today}</b>")
            for c in day_items:
                lines.append(f"  {format_item(c)}")
        else:
            lines.append(f"\n{day_name} {current.strftime('%d.%m')}{is_today} — пусто")
        current += timedelta(days=1)
    
    total = len(items)
    done = sum(1 for c in items if c.status == ContentStatus.PUBLISHED)
    lines.append(f"\n📊 Всего: {total} | Готово: {done}")
    
    await callback.message.edit_text("\n".join(lines), reply_markup=schedule_menu_kb(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "sched:week")
async def sched_week(callback: CallbackQuery):
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    await _show_week(callback, monday, f"Эта неделя ({monday.strftime('%d.%m')} — {sunday.strftime('%d.%m')})")


@router.callback_query(F.data == "sched:nextweek")
async def sched_nextweek(callback: CallbackQuery):
    today = date.today()
    next_monday = today - timedelta(days=today.weekday()) + timedelta(days=7)
    next_sunday = next_monday + timedelta(days=6)
    await _show_week(callback, next_monday, f"След. неделя ({next_monday.strftime('%d.%m')} — {next_sunday.strftime('%d.%m')})")


# ==================== My Tasks (only mine) ====================

@router.callback_query(F.data == "sched:my")
@router.message(Command("mytasks"))
async def sched_my(event, state: FSMContext = None):
    tg_id = event.from_user.id
    
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == tg_id))
        user = result.scalar_one_or_none()
        if not user:
            text = "❌ Напиши /start"
            if isinstance(event, CallbackQuery):
                await event.answer(text, show_alert=True)
            else:
                await event.answer(text)
            return
        
        result = await session.execute(
            select(ContentPlan)
            .options(selectinload(ContentPlan.project))
            .where(and_(
                ContentPlan.assignee_id == user.id,
                ContentPlan.status.in_([ContentStatus.PLANNED, ContentStatus.IN_PROGRESS, ContentStatus.REVIEW]),
                ContentPlan.scheduled_date >= date.today()
            ))
            .order_by(ContentPlan.scheduled_date, ContentPlan.scheduled_time.asc().nulls_last())
            .limit(20)
        )
        items = result.scalars().all()
    
    if not items:
        text = "📋 <b>Мои задачи</b>\n\n✨ Нет активных задач"
    else:
        lines = [f"📋 <b>Мои задачи</b> ({len(items)})\n"]
        current_date = None
        weekdays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        for c in items:
            if c.scheduled_date != current_date:
                current_date = c.scheduled_date
                day_name = weekdays[c.scheduled_date.weekday()]
                is_today = " (сегодня)" if c.scheduled_date == date.today() else ""
                lines.append(f"\n<b>{day_name} {c.scheduled_date.strftime('%d.%m')}{is_today}</b>")
            lines.append(f"  {format_item(c, show_assignee=False)}")
        text = "\n".join(lines)
    
    builder = InlineKeyboardBuilder()
    for c in items:
        if c.status != ContentStatus.PUBLISHED:
            short = c.title[:25] + "..." if len(c.title) > 25 else c.title
            builder.row(InlineKeyboardButton(text=f"✏️ {short}", callback_data=f"sedit:{c.id}"))
    builder.row(InlineKeyboardButton(text="◀️ Меню", callback_data="menu:content"))
    
    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
        await event.answer()
    else:
        await event.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")


# ==================== Add ====================

@router.callback_query(F.data == "sched:add")
@router.callback_query(F.data == "tasks:add")
@router.message(Command("addtask"))
@router.message(Command("addcontent"))
async def sched_add_start(event, state: FSMContext):
    await state.set_state(AddSchedule.title)
    text = "📝 <b>Новая задача</b>\n\nВведи название:"
    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, parse_mode="HTML")
        await event.answer()
    else:
        await event.answer(text, parse_mode="HTML")


@router.message(AddSchedule.title)
async def sched_add_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text)
    await state.set_state(AddSchedule.assignee)
    
    async with async_session() as session:
        result = await session.execute(select(User).where(User.is_active == True).order_by(User.full_name))
        users = result.scalars().all()
    
    await message.answer("👤 Ответственный:", reply_markup=user_select_kb(users, "sassign"))


@router.callback_query(F.data.startswith("sassign:"), AddSchedule.assignee)
async def sched_add_assignee(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split(":")[1]
    assignee_id = None if val == "skip" else int(val)
    await state.update_data(assignee_id=assignee_id)
    await state.set_state(AddSchedule.project)
    
    async with async_session() as session:
        result = await session.execute(select(Project).where(Project.is_active == True))
        projects = result.scalars().all()
    
    await callback.message.edit_text("📁 Проект:", reply_markup=project_select_kb(projects, "sproj"))
    await callback.answer()


@router.callback_query(F.data.startswith("sproj:"), AddSchedule.project)
async def sched_add_project(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split(":")[1]
    project_id = None if val == "skip" else int(val)
    await state.update_data(project_id=project_id)
    await state.set_state(AddSchedule.date)
    
    # 3 weeks of dates
    today = date.today()
    weekdays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    builder = InlineKeyboardBuilder()
    for i in range(21):  # 3 weeks
        d = today + timedelta(days=i)
        if i == 0:
            label = "Сегодня"
        elif i == 1:
            label = "Завтра"
        else:
            label = f"{weekdays[d.weekday()]} {d.strftime('%d.%m')}"
        builder.row(InlineKeyboardButton(text=label, callback_data=f"sdate:{d.isoformat()}"))
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="sched:cancel"))
    
    await callback.message.edit_text("📅 Дата:", reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("sdate:"), AddSchedule.date)
async def sched_add_date(callback: CallbackQuery, state: FSMContext):
    date_str = callback.data.split(":", 1)[1]
    await state.update_data(scheduled_date=date_str)
    await state.set_state(AddSchedule.time)
    
    builder = InlineKeyboardBuilder()
    times = ["08:00", "09:00", "10:00", "11:00", "12:00", "13:00",
             "14:00", "15:00", "16:00", "17:00", "18:00", "19:00", "20:00"]
    for i in range(0, len(times), 3):
        row = [InlineKeyboardButton(text=t, callback_data=f"stime:{t}") for t in times[i:i+3]]
        builder.row(*row)
    builder.row(InlineKeyboardButton(text="⏭ Без времени", callback_data="stime:skip"))
    
    await callback.message.edit_text("🕐 Время:", reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("stime:"), AddSchedule.time)
async def sched_add_time(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split(":", 1)[1]
    scheduled_time = None if val == "skip" else val
    await state.update_data(scheduled_time=scheduled_time)
    await state.set_state(AddSchedule.description)
    
    await callback.message.edit_text("📎 Комментарий (или пропусти):", reply_markup=skip_kb("sdesc:skip"))
    await callback.answer()


@router.callback_query(F.data == "sdesc:skip", AddSchedule.description)
async def sched_desc_skip(callback: CallbackQuery, state: FSMContext):
    await state.update_data(description=None)
    await _save_schedule(callback.message, state, callback)


@router.message(AddSchedule.description)
async def sched_add_desc(message: Message, state: FSMContext):
    await state.update_data(description=message.text)
    await _save_schedule(message, state)


async def _save_schedule(message: Message, state: FSMContext, callback: CallbackQuery = None):
    data = await state.get_data()
    await state.clear()
    
    scheduled_time = None
    if data.get("scheduled_time"):
        h, m = map(int, data["scheduled_time"].split(":"))
        scheduled_time = dt_time(h, m)
    
    async with async_session() as session:
        item = ContentPlan(
            title=data["title"],
            content_type=ContentType.POST,  # default, doesn't matter
            platform=Platform.TELEGRAM,      # default, doesn't matter
            project_id=data.get("project_id"),
            assignee_id=data.get("assignee_id"),
            scheduled_date=date.fromisoformat(data["scheduled_date"]),
            scheduled_time=scheduled_time,
            description=data.get("description"),
            status=ContentStatus.PLANNED,
        )
        session.add(item)
        await session.commit()
        await session.refresh(item)
        
        result = await session.execute(
            select(ContentPlan)
            .options(selectinload(ContentPlan.assignee), selectinload(ContentPlan.project))
            .where(ContentPlan.id == item.id)
        )
        item = result.scalar_one()
    
    text = f"✅ <b>Задача добавлена!</b>\n\n{format_item(item)}\n📅 {item.scheduled_date.strftime('%d.%m.%Y')}"
    
    # Notify assignee instantly
    if item.assignee and item.assignee.telegram_id and item.assignee.telegram_id != 0:
        creator_id = callback.from_user.id if callback else message.from_user.id
        if item.assignee.telegram_id != creator_id:  # don't notify yourself
            weekdays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
            day_name = weekdays[item.scheduled_date.weekday()]
            time_str = item.scheduled_time.strftime("%H:%M") if item.scheduled_time else ""
            project_str = f"\n📁 {item.project.emoji} {item.project.name}" if item.project else ""
            desc_str = f"\n📎 {item.description}" if item.description else ""
            
            notify_text = (
                f"📌 <b>Новая задача для тебя:</b>\n\n"
                f"<b>{item.title}</b>\n"
                f"📅 {day_name} {item.scheduled_date.strftime('%d.%m.%Y')} {time_str}"
                f"{project_str}{desc_str}"
            )
            try:
                bot = message.bot if not callback else callback.message.bot
                await bot.send_message(item.assignee.telegram_id, notify_text, parse_mode="HTML")
            except Exception as e:
                print(f"Failed to notify assignee: {e}")
    
    target = callback.message if callback else message
    if callback:
        await target.edit_text(text, reply_markup=schedule_menu_kb(), parse_mode="HTML")
        await callback.answer()
    else:
        await target.answer(text, reply_markup=schedule_menu_kb(), parse_mode="HTML")


# ==================== Edit ====================

@router.callback_query(F.data.startswith("sedit:"))
async def sched_edit(callback: CallbackQuery, state: FSMContext):
    content_id = int(callback.data.split(":")[1])
    
    async with async_session() as session:
        result = await session.execute(
            select(ContentPlan)
            .options(selectinload(ContentPlan.assignee), selectinload(ContentPlan.project))
            .where(ContentPlan.id == content_id)
        )
        c = result.scalar_one_or_none()
    
    if not c:
        await callback.answer("Не найдено", show_alert=True)
        return
    
    time_str = c.scheduled_time.strftime("%H:%M") if c.scheduled_time else "не указано"
    weekdays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    day_name = weekdays[c.scheduled_date.weekday()]
    
    text = (
        f"📄 <b>{c.title}</b>\n\n"
        f"📅 {day_name} {c.scheduled_date.strftime('%d.%m.%Y')} в {time_str}\n"
        f"📊 {STATUS_EMOJI.get(c.status, '⬜')} {c.status.value}\n"
        f"👤 {c.assignee.full_name if c.assignee else 'не назначен'}\n"
    )
    if c.project:
        text += f"📁 {c.project.emoji} {c.project.name}\n"
    if c.description:
        text += f"\n📎 {c.description}\n"
    text += "\n<b>Что изменить?</b>"
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📅 Дату", callback_data=f"sed_date:{content_id}"),
        InlineKeyboardButton(text="🕐 Время", callback_data=f"sed_time:{content_id}"),
    )
    builder.row(
        InlineKeyboardButton(text="👤 Ответственного", callback_data=f"sed_assign:{content_id}"),
        InlineKeyboardButton(text="✏️ Название", callback_data=f"sed_title:{content_id}"),
    )
    # Status quick buttons
    builder.row(
        InlineKeyboardButton(text="🔄 В работе", callback_data=f"sst:{content_id}:progress"),
        InlineKeyboardButton(text="✅ Готово", callback_data=f"sst:{content_id}:published"),
    )
    builder.row(
        InlineKeyboardButton(text="❌ Отменить", callback_data=f"sst:{content_id}:cancelled"),
        InlineKeyboardButton(text="🗑 Удалить", callback_data=f"sed_del:{content_id}"),
    )
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="sched:today"))
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()


# --- Quick Status Change ---

@router.callback_query(F.data.startswith("sst:"))
async def sched_status(callback: CallbackQuery):
    parts = callback.data.split(":")
    content_id = int(parts[1])
    new_status = ContentStatus(parts[2])
    
    async with async_session() as session:
        result = await session.execute(select(ContentPlan).where(ContentPlan.id == content_id))
        c = result.scalar_one_or_none()
        if c:
            c.status = new_status
            await session.commit()
    
    await callback.answer(f"{STATUS_EMOJI.get(new_status, '')} Готово!", show_alert=True)
    callback.data = f"sedit:{content_id}"
    await sched_edit(callback)


# --- Edit Date ---

@router.callback_query(F.data.startswith("sed_date:"))
async def sed_date(callback: CallbackQuery, state: FSMContext):
    content_id = int(callback.data.split(":")[1])
    await state.update_data(edit_id=content_id)
    await state.set_state(EditSchedule.date)
    
    today = date.today()
    weekdays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    builder = InlineKeyboardBuilder()
    for i in range(21):
        d = today + timedelta(days=i)
        label = "Сегодня" if i == 0 else "Завтра" if i == 1 else f"{weekdays[d.weekday()]} {d.strftime('%d.%m')}"
        builder.row(InlineKeyboardButton(text=label, callback_data=f"sndate:{d.isoformat()}"))
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data=f"sedit:{content_id}"))
    
    await callback.message.edit_text("📅 Новая дата:", reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("sndate:"), EditSchedule.date)
async def sed_date_save(callback: CallbackQuery, state: FSMContext):
    date_str = callback.data.split(":", 1)[1]
    data = await state.get_data()
    cid = data["edit_id"]
    await state.clear()
    
    async with async_session() as session:
        result = await session.execute(select(ContentPlan).where(ContentPlan.id == cid))
        c = result.scalar_one_or_none()
        if c:
            c.scheduled_date = date.fromisoformat(date_str)
            await session.commit()
    
    await callback.answer(f"✅ Перенесено на {date_str}", show_alert=True)
    callback.data = f"sedit:{cid}"
    await sched_edit(callback, state)


# --- Edit Time ---

@router.callback_query(F.data.startswith("sed_time:"))
async def sed_time(callback: CallbackQuery, state: FSMContext):
    content_id = int(callback.data.split(":")[1])
    await state.update_data(edit_id=content_id)
    await state.set_state(EditSchedule.time)
    
    builder = InlineKeyboardBuilder()
    times = ["08:00", "09:00", "10:00", "11:00", "12:00", "13:00",
             "14:00", "15:00", "16:00", "17:00", "18:00", "19:00", "20:00"]
    for i in range(0, len(times), 3):
        row = [InlineKeyboardButton(text=t, callback_data=f"sntime:{t}") for t in times[i:i+3]]
        builder.row(*row)
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data=f"sedit:{content_id}"))
    
    await callback.message.edit_text("🕐 Новое время:", reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("sntime:"), EditSchedule.time)
async def sed_time_save(callback: CallbackQuery, state: FSMContext):
    time_str = callback.data.split(":", 1)[1]
    data = await state.get_data()
    cid = data["edit_id"]
    await state.clear()
    
    h, m = map(int, time_str.split(":"))
    async with async_session() as session:
        result = await session.execute(select(ContentPlan).where(ContentPlan.id == cid))
        c = result.scalar_one_or_none()
        if c:
            c.scheduled_time = dt_time(h, m)
            await session.commit()
    
    await callback.answer(f"✅ Время: {time_str}", show_alert=True)
    callback.data = f"sedit:{cid}"
    await sched_edit(callback, state)


# --- Edit Assignee ---

@router.callback_query(F.data.startswith("sed_assign:"))
async def sed_assign(callback: CallbackQuery, state: FSMContext):
    content_id = int(callback.data.split(":")[1])
    await state.update_data(edit_id=content_id)
    await state.set_state(EditSchedule.assignee)
    
    async with async_session() as session:
        result = await session.execute(select(User).where(User.is_active == True).order_by(User.full_name))
        users = result.scalars().all()
    
    await callback.message.edit_text("👤 Новый ответственный:", reply_markup=user_select_kb(users, "snassign"))
    await callback.answer()


@router.callback_query(F.data.startswith("snassign:"), EditSchedule.assignee)
async def sed_assign_save(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split(":")[1]
    assignee_id = None if val == "skip" else int(val)
    data = await state.get_data()
    cid = data["edit_id"]
    await state.clear()
    
    async with async_session() as session:
        result = await session.execute(
            select(ContentPlan)
            .options(selectinload(ContentPlan.project))
            .where(ContentPlan.id == cid)
        )
        c = result.scalar_one_or_none()
        if c:
            c.assignee_id = assignee_id
            await session.commit()
            
            # Notify new assignee
            if assignee_id:
                user_r = await session.execute(select(User).where(User.id == assignee_id))
                new_assignee = user_r.scalar_one_or_none()
                if new_assignee and new_assignee.telegram_id and new_assignee.telegram_id != 0 and new_assignee.telegram_id != callback.from_user.id:
                    weekdays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
                    day_name = weekdays[c.scheduled_date.weekday()]
                    time_str = c.scheduled_time.strftime("%H:%M") if c.scheduled_time else ""
                    notify = (
                        f"📌 <b>Тебе назначена задача:</b>\n\n"
                        f"<b>{c.title}</b>\n"
                        f"📅 {day_name} {c.scheduled_date.strftime('%d.%m.%Y')} {time_str}"
                    )
                    try:
                        await callback.message.bot.send_message(new_assignee.telegram_id, notify, parse_mode="HTML")
                    except Exception:
                        pass
            await session.commit()
    
    await callback.answer("✅ Ответственный изменён", show_alert=True)
    callback.data = f"sedit:{cid}"
    await sched_edit(callback, state)


# --- Edit Title ---

@router.callback_query(F.data.startswith("sed_title:"))
async def sed_title(callback: CallbackQuery, state: FSMContext):
    content_id = int(callback.data.split(":")[1])
    await state.update_data(edit_id=content_id)
    await state.set_state(EditSchedule.title)
    await callback.message.edit_text("✏️ Новое название:")
    await callback.answer()


@router.message(EditSchedule.title)
async def sed_title_save(message: Message, state: FSMContext):
    data = await state.get_data()
    cid = data["edit_id"]
    await state.clear()
    
    async with async_session() as session:
        result = await session.execute(select(ContentPlan).where(ContentPlan.id == cid))
        c = result.scalar_one_or_none()
        if c:
            c.title = message.text
            await session.commit()
    
    await message.answer(f"✅ Название: <b>{message.text}</b>", parse_mode="HTML", reply_markup=schedule_menu_kb())


# --- Delete ---

@router.callback_query(F.data.startswith("sed_del:"))
async def sed_delete(callback: CallbackQuery):
    content_id = int(callback.data.split(":")[1])
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"sdel_yes:{content_id}"),
        InlineKeyboardButton(text="❌ Нет", callback_data=f"sedit:{content_id}"),
    )
    await callback.message.edit_text("🗑 <b>Удалить?</b>", reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("sdel_yes:"))
async def sed_delete_confirm(callback: CallbackQuery):
    content_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        result = await session.execute(select(ContentPlan).where(ContentPlan.id == content_id))
        c = result.scalar_one_or_none()
        if c:
            await session.delete(c)
            await session.commit()
    
    await callback.answer("🗑 Удалено", show_alert=True)
    await callback.message.edit_text("🗑 Задача удалена", reply_markup=schedule_menu_kb())


# ==================== Cancel ====================

@router.callback_query(F.data == "sched:cancel")
@router.callback_query(F.data == "content:cancel")
@router.callback_query(F.data == "tasks:cancel")
async def sched_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Отменено", reply_markup=schedule_menu_kb())
    await callback.answer()
