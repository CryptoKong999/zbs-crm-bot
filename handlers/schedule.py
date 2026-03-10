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
    async_session, ContentPlan, ContentAssignee, TaskAttachment, ContentType, ContentStatus,
    Platform, Project, User, UserRole
)
from keyboards import (
    content_menu_kb, content_status_kb,
    project_select_kb, back_to_menu_kb, skip_kb
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
    if show_assignee:
        names = [u.full_name for u in c.assignees] if c.assignees else []
        if not names and c.assignee:
            names = [c.assignee.full_name]
        if names:
            assignee_str = f" → {', '.join(names)}"
    
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
    media = State()


class EditSchedule(StatesGroup):
    date = State()
    time = State()
    assignee = State()
    title = State()
    description = State()
    media = State()


class Reschedule(StatesGroup):
    date = State()
    time = State()
    reason = State()


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
                await event.answer(text)
            else:
                await event.answer(text)
            return
        
        result = await session.execute(
            select(ContentPlan)
            .options(selectinload(ContentPlan.project))
            .join(ContentAssignee, ContentAssignee.content_id == ContentPlan.id, isouter=True)
            .where(and_(
                or_(
                    ContentAssignee.user_id == user.id,
                    ContentPlan.assignee_id == user.id,  # legacy compat
                ),
                ContentPlan.status.in_([ContentStatus.PLANNED, ContentStatus.IN_PROGRESS, ContentStatus.REVIEW]),
                ContentPlan.scheduled_date >= date.today()
            ))
            .order_by(ContentPlan.scheduled_date, ContentPlan.scheduled_time.asc().nulls_last())
            .limit(20)
        )
        items = list(dict.fromkeys(result.scalars().all()))  # deduplicate
    
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
    await state.update_data(title=message.text, selected_users=[])
    await state.set_state(AddSchedule.assignee)
    await _show_user_picker(message, state, is_callback=False)


async def _show_user_picker(target, state: FSMContext, is_callback: bool = True):
    """Show multi-select user picker"""
    data = await state.get_data()
    selected = data.get("selected_users", [])
    
    async with async_session() as session:
        result = await session.execute(select(User).where(User.is_active == True).order_by(User.full_name))
        users = result.scalars().all()
    
    builder = InlineKeyboardBuilder()
    for u in users:
        check = "✅ " if u.id in selected else ""
        label = f"{check}{u.full_name}"
        if u.username:
            label += f" (@{u.username})"
        builder.row(InlineKeyboardButton(text=label, callback_data=f"stoggle:{u.id}"))
    builder.row(InlineKeyboardButton(text="✔️ Готово", callback_data="sassign:done"))
    builder.row(InlineKeyboardButton(text="⏭ Пропустить", callback_data="sassign:skip"))
    
    count = len(selected)
    text = f"👤 Ответственные ({count} выбрано):\nНажми на имя чтобы выбрать/убрать"
    
    if is_callback:
        await target.message.edit_text(text, reply_markup=builder.as_markup())
    else:
        await target.answer(text, reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("stoggle:"), AddSchedule.assignee)
async def sched_toggle_user(callback: CallbackQuery, state: FSMContext):
    user_id = int(callback.data.split(":")[1])
    data = await state.get_data()
    selected = data.get("selected_users", [])
    
    if user_id in selected:
        selected.remove(user_id)
    else:
        selected.append(user_id)
    
    await state.update_data(selected_users=selected)
    await _show_user_picker(callback, state)
    await callback.answer()


@router.callback_query(F.data.startswith("sassign:"), AddSchedule.assignee)
async def sched_add_assignee(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split(":")[1]
    if val == "skip":
        await state.update_data(selected_users=[])
    # "done" keeps current selection
    
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
    await _ask_media(callback.message, state, is_callback=True)
    await callback.answer()


@router.message(AddSchedule.description)
async def sched_add_desc(message: Message, state: FSMContext):
    await state.update_data(description=message.text)
    await _ask_media(message, state, is_callback=False)


async def _ask_media(message, state, is_callback=False):
    await state.update_data(media_files=[])
    await state.set_state(AddSchedule.media)
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⏭ Без вложений", callback_data="smedia:done"))
    
    text = "📷 Прикрепи фото, голосовое или файл\n\nМожно несколько — отправляй по одному.\nКогда закончишь — нажми кнопку."
    if is_callback:
        await message.edit_text(text, reply_markup=builder.as_markup())
    else:
        await message.answer(text, reply_markup=builder.as_markup())


def _media_done_kb(count: int):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=f"✅ Готово ({count} прикреплено)", callback_data="smedia:done"))
    return builder.as_markup()


@router.message(AddSchedule.media, F.photo)
async def sched_media_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    files = data.get("media_files", [])
    files.append({"file_id": message.photo[-1].file_id, "type": "photo"})
    await state.update_data(media_files=files)
    await message.answer(f"📷 Фото добавлено ({len(files)} вложений)", reply_markup=_media_done_kb(len(files)))


@router.message(AddSchedule.media, F.voice)
async def sched_media_voice(message: Message, state: FSMContext):
    data = await state.get_data()
    files = data.get("media_files", [])
    files.append({"file_id": message.voice.file_id, "type": "voice"})
    await state.update_data(media_files=files)
    await message.answer(f"🎤 Голосовое добавлено ({len(files)} вложений)", reply_markup=_media_done_kb(len(files)))


@router.message(AddSchedule.media, F.video)
async def sched_media_video(message: Message, state: FSMContext):
    data = await state.get_data()
    files = data.get("media_files", [])
    files.append({"file_id": message.video.file_id, "type": "video"})
    await state.update_data(media_files=files)
    await message.answer(f"🎬 Видео добавлено ({len(files)} вложений)", reply_markup=_media_done_kb(len(files)))


@router.message(AddSchedule.media, F.document)
async def sched_media_doc(message: Message, state: FSMContext):
    data = await state.get_data()
    files = data.get("media_files", [])
    files.append({"file_id": message.document.file_id, "type": "document"})
    await state.update_data(media_files=files)
    await message.answer(f"📄 Файл добавлен ({len(files)} вложений)", reply_markup=_media_done_kb(len(files)))


@router.message(AddSchedule.media, F.video_note)
async def sched_media_videonote(message: Message, state: FSMContext):
    data = await state.get_data()
    files = data.get("media_files", [])
    files.append({"file_id": message.video_note.file_id, "type": "video_note"})
    await state.update_data(media_files=files)
    await message.answer(f"⭕ Кружок добавлен ({len(files)} вложений)", reply_markup=_media_done_kb(len(files)))


@router.callback_query(F.data == "smedia:done", AddSchedule.media)
async def sched_media_done(callback: CallbackQuery, state: FSMContext):
    await _save_schedule(callback.message, state, callback)


async def _save_schedule(message: Message, state: FSMContext, callback: CallbackQuery = None):
    data = await state.get_data()
    tg_id = callback.from_user.id if callback else message.from_user.id
    await state.clear()
    
    scheduled_time = None
    if data.get("scheduled_time"):
        h, m = map(int, data["scheduled_time"].split(":"))
        scheduled_time = dt_time(h, m)
    
    selected_users = data.get("selected_users", [])
    first_assignee = selected_users[0] if selected_users else None
    media_files = data.get("media_files", [])
    
    async with async_session() as session:
        result = await session.execute(select(User.id).where(User.telegram_id == tg_id))
        creator_id = result.scalar_one_or_none()
        
        item = ContentPlan(
            title=data["title"],
            content_type=ContentType.POST,
            platform=Platform.TELEGRAM,
            project_id=data.get("project_id"),
            assignee_id=first_assignee,
            scheduled_date=date.fromisoformat(data["scheduled_date"]),
            scheduled_time=scheduled_time,
            description=data.get("description"),
            status=ContentStatus.PLANNED,
            created_by_user_id=creator_id,
        )
        session.add(item)
        await session.flush()
        
        # Save assignees
        for uid in selected_users:
            session.add(ContentAssignee(content_id=item.id, user_id=uid))
        
        # Save attachments
        for mf in media_files:
            session.add(TaskAttachment(
                content_id=item.id,
                file_id=mf["file_id"],
                file_type=mf["type"],
                uploaded_by=creator_id,
            ))
        
        await session.commit()
        
        # Reload
        result = await session.execute(
            select(ContentPlan).options(selectinload(ContentPlan.project))
            .where(ContentPlan.id == item.id)
        )
        item = result.scalar_one()
        
        assignee_users = []
        if selected_users:
            r = await session.execute(select(User).where(User.id.in_(selected_users)))
            assignee_users = r.scalars().all()
    
    attach_count = len(media_files)
    attach_str = f"\n📎 {attach_count} вложений" if attach_count else ""
    text = f"✅ <b>Задача добавлена!</b>\n\n{format_item(item)}\n📅 {item.scheduled_date.strftime('%d.%m.%Y')}{attach_str}"
    
    # Notify all assignees
    bot_instance = message.bot if not callback else callback.message.bot
    weekdays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    day_name = weekdays[item.scheduled_date.weekday()]
    time_str_fmt = item.scheduled_time.strftime("%H:%M") if item.scheduled_time else ""
    project_str = f"\n📁 {item.project.emoji} {item.project.name}" if item.project else ""
    desc_str = f"\n📎 {item.description}" if item.description else ""
    
    for u in assignee_users:
        if u.telegram_id and u.telegram_id != 0 and u.telegram_id != tg_id:
            notify_text = (
                f"📌 <b>Новая задача для тебя:</b>\n\n"
                f"<b>{item.title}</b>\n"
                f"📅 {day_name} {item.scheduled_date.strftime('%d.%m.%Y')} {time_str_fmt}"
                f"{project_str}{desc_str}"
            )
            notify_kb = InlineKeyboardBuilder()
            notify_kb.row(
                InlineKeyboardButton(text="✅ Принял", callback_data=f"sst:{item.id}:progress"),
                InlineKeyboardButton(text="📆 Перенести", callback_data=f"resched:{item.id}"),
            )
            try:
                await bot_instance.send_message(u.telegram_id, notify_text, reply_markup=notify_kb.as_markup(), parse_mode="HTML")
                # Send attachments
                for mf in media_files:
                    try:
                        if mf["type"] == "photo":
                            await bot_instance.send_photo(u.telegram_id, mf["file_id"])
                        elif mf["type"] == "voice":
                            await bot_instance.send_voice(u.telegram_id, mf["file_id"])
                        elif mf["type"] == "video":
                            await bot_instance.send_video(u.telegram_id, mf["file_id"])
                        elif mf["type"] == "video_note":
                            await bot_instance.send_video_note(u.telegram_id, mf["file_id"])
                        elif mf["type"] == "document":
                            await bot_instance.send_document(u.telegram_id, mf["file_id"])
                    except Exception:
                        pass
            except Exception as e:
                print(f"Failed to notify {u.full_name}: {e}")
    
    target = callback.message if callback else message
    if callback:
        await target.edit_text(text, reply_markup=schedule_menu_kb(), parse_mode="HTML")
        await callback.answer()
    else:
        await target.answer(text, reply_markup=schedule_menu_kb(), parse_mode="HTML")


# ==================== Edit ====================

@router.callback_query(F.data.startswith("sedit:"))
async def sched_edit(callback: CallbackQuery, state: FSMContext = None):
    content_id = int(callback.data.split(":")[1])
    
    async with async_session() as session:
        result = await session.execute(
            select(ContentPlan)
            .options(selectinload(ContentPlan.assignee), selectinload(ContentPlan.project), selectinload(ContentPlan.assignees))
            .where(ContentPlan.id == content_id)
        )
        c = result.scalar_one_or_none()
        
        # Get current user
        user_r = await session.execute(select(User).where(User.telegram_id == callback.from_user.id))
        current_user = user_r.scalar_one_or_none()
    
    if not c:
        await callback.answer()
        return
    
    is_admin = current_user and current_user.role in (UserRole.ADMIN, UserRole.MANAGER)
    assignee_ids = [u.id for u in c.assignees] if c.assignees else ([c.assignee_id] if c.assignee_id else [])
    is_assignee = current_user and current_user.id in assignee_ids
    
    time_str = c.scheduled_time.strftime("%H:%M") if c.scheduled_time else "не указано"
    weekdays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    day_name = weekdays[c.scheduled_date.weekday()]
    
    # Build assignee names
    names = [u.full_name for u in c.assignees] if c.assignees else []
    if not names and c.assignee:
        names = [c.assignee.full_name]
    assignee_display = ", ".join(names) if names else "не назначен"
    
    text = (
        f"📄 <b>{c.title}</b>\n\n"
        f"📅 {day_name} {c.scheduled_date.strftime('%d.%m.%Y')} в {time_str}\n"
        f"📊 {STATUS_EMOJI.get(c.status, '⬜')} {c.status.value}\n"
        f"👤 {assignee_display}\n"
    )
    if c.project:
        text += f"📁 {c.project.emoji} {c.project.name}\n"
    if c.description:
        text += f"\n📎 {c.description}\n"
    
    # Count attachments
    async with async_session() as session:
        from sqlalchemy import func as sqlfunc
        att_count = (await session.execute(
            select(sqlfunc.count(TaskAttachment.id)).where(TaskAttachment.content_id == content_id)
        )).scalar() or 0
    
    if att_count:
        text += f"\n🖼 Вложений: {att_count}\n"
    
    builder = InlineKeyboardBuilder()
    
    if is_admin:
        # Admin: full control
        text += "\n<b>Что изменить?</b>"
        builder.row(
            InlineKeyboardButton(text="📅 Дату", callback_data=f"sed_date:{content_id}"),
            InlineKeyboardButton(text="🕐 Время", callback_data=f"sed_time:{content_id}"),
        )
        builder.row(
            InlineKeyboardButton(text="👤 Ответственного", callback_data=f"sed_assign:{content_id}"),
            InlineKeyboardButton(text="✏️ Название", callback_data=f"sed_title:{content_id}"),
        )
        builder.row(
            InlineKeyboardButton(text="🔄 В работе", callback_data=f"sst:{content_id}:progress"),
            InlineKeyboardButton(text="✅ Готово", callback_data=f"sst:{content_id}:published"),
        )
        builder.row(
            InlineKeyboardButton(text=f"🖼 Вложения ({att_count})", callback_data=f"satt:{content_id}"),
            InlineKeyboardButton(text="➕ Прикрепить", callback_data=f"satt_add:{content_id}"),
        )
        builder.row(
            InlineKeyboardButton(text="❌ Отменить", callback_data=f"sst:{content_id}:cancelled"),
            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"sed_del:{content_id}"),
        )
    elif is_assignee:
        text += "\n<b>Действия:</b>"
        builder.row(
            InlineKeyboardButton(text="🔄 В работе", callback_data=f"sst:{content_id}:progress"),
            InlineKeyboardButton(text="✅ Готово", callback_data=f"sst:{content_id}:published"),
        )
        builder.row(
            InlineKeyboardButton(text=f"🖼 Вложения ({att_count})", callback_data=f"satt:{content_id}"),
            InlineKeyboardButton(text="➕ Прикрепить", callback_data=f"satt_add:{content_id}"),
        )
        builder.row(
            InlineKeyboardButton(text="📆 Перенести", callback_data=f"resched:{content_id}"),
        )
    else:
        text += "\n<i>Только просмотр</i>"
        if att_count:
            builder.row(InlineKeyboardButton(text=f"🖼 Вложения ({att_count})", callback_data=f"satt:{content_id}"))
    
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="sched:today"))
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()


# --- Quick Status Change (notifies task creator) ---

@router.callback_query(F.data.startswith("sst:"))
async def sched_status(callback: CallbackQuery):
    parts = callback.data.split(":")
    content_id = int(parts[1])
    new_status = ContentStatus(parts[2])
    
    async with async_session() as session:
        result = await session.execute(
            select(ContentPlan)
            .options(selectinload(ContentPlan.assignee), selectinload(ContentPlan.creator), selectinload(ContentPlan.assignees))
            .where(ContentPlan.id == content_id)
        )
        c = result.scalar_one_or_none()
        if c:
            c.status = new_status
            await session.commit()
            
            bot = callback.message.bot
            who = callback.from_user.full_name
            status_text = STATUS_EMOJI.get(new_status, "") + " " + new_status.value
            
            if new_status == ContentStatus.PUBLISHED:
                # Task completed — notify creator
                menu_kb = InlineKeyboardBuilder()
                menu_kb.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main"))
                
                done_text = (
                    f"✅ <b>Задача выполнена!</b>\n\n"
                    f"<b>{c.title}</b>\n"
                    f"👤 {who}\n\n"
                    f"Задача закрыта."
                )
                
                # Notify creator
                if c.creator and c.creator.telegram_id and c.creator.telegram_id != callback.from_user.id:
                    try:
                        await bot.send_message(c.creator.telegram_id, done_text, reply_markup=menu_kb.as_markup(), parse_mode="HTML")
                    except Exception:
                        pass
                
                # Notify all assignees (except the one who completed)
                users_to_notify = c.assignees if c.assignees else ([c.assignee] if c.assignee else [])
                for u in users_to_notify:
                    if u and u.telegram_id and u.telegram_id != 0 and u.telegram_id != callback.from_user.id:
                        if not (c.creator and u.telegram_id == c.creator.telegram_id):  # don't double-notify creator
                            try:
                                await bot.send_message(u.telegram_id, done_text, reply_markup=menu_kb.as_markup(), parse_mode="HTML")
                            except Exception:
                                pass
            else:
                # Other status — notify creator only
                if c.creator and c.creator.telegram_id and c.creator.telegram_id != callback.from_user.id:
                    notify = (
                        f"📋 <b>{who}</b> обновил задачу:\n\n"
                        f"<b>{c.title}</b>\n"
                        f"Статус: {status_text}"
                    )
                    try:
                        await bot.send_message(c.creator.telegram_id, notify, parse_mode="HTML")
                    except Exception:
                        pass
    
    if new_status == ContentStatus.PUBLISHED:
        # Show completion message to the person who completed it
        menu_kb_self = InlineKeyboardBuilder()
        menu_kb_self.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main"))
        await callback.message.edit_text(
            f"✅ <b>Задача выполнена!</b>\n\n<b>{c.title if c else ''}</b>\n\nОтличная работа!",
            reply_markup=menu_kb_self.as_markup(),
            parse_mode="HTML"
        )
        await callback.answer()
    else:
        status_label = STATUS_EMOJI.get(new_status, "") + " " + new_status.value
        menu_kb_s = InlineKeyboardBuilder()
        menu_kb_s.row(InlineKeyboardButton(text="🏠 Меню", callback_data="menu:main"))
        await callback.message.edit_text(
            f"{status_label}\n\n<b>{c.title if c else ''}</b>",
            reply_markup=menu_kb_s.as_markup(),
            parse_mode="HTML"
        )
        await callback.answer()


# --- Reschedule (assignee picks date + time + writes reason, admins notified) ---

@router.callback_query(F.data.startswith("resched:"))
async def resched_start(callback: CallbackQuery, state: FSMContext):
    content_id = int(callback.data.split(":")[1])
    await state.update_data(resched_id=content_id)
    await state.set_state(Reschedule.date)
    
    today = date.today()
    weekdays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    builder = InlineKeyboardBuilder()
    for i in range(21):
        d = today + timedelta(days=i)
        label = "Сегодня" if i == 0 else "Завтра" if i == 1 else f"{weekdays[d.weekday()]} {d.strftime('%d.%m')}"
        builder.row(InlineKeyboardButton(text=label, callback_data=f"rsdate:{d.isoformat()}"))
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data=f"sedit:{content_id}"))
    
    await callback.message.edit_text("📆 <b>Перенести на какой день?</b>", reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("rsdate:"), Reschedule.date)
async def resched_date(callback: CallbackQuery, state: FSMContext):
    date_str = callback.data.split(":", 1)[1]
    await state.update_data(new_date=date_str)
    await state.set_state(Reschedule.time)
    
    builder = InlineKeyboardBuilder()
    times = ["08:00", "09:00", "10:00", "11:00", "12:00", "13:00",
             "14:00", "15:00", "16:00", "17:00", "18:00", "19:00", "20:00"]
    for i in range(0, len(times), 3):
        row = [InlineKeyboardButton(text=t, callback_data=f"rstime:{t}") for t in times[i:i+3]]
        builder.row(*row)
    builder.row(InlineKeyboardButton(text="⏭ Оставить как было", callback_data="rstime:keep"))
    
    await callback.message.edit_text("🕐 Новое время:", reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("rstime:"), Reschedule.time)
async def resched_time(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split(":", 1)[1]
    await state.update_data(new_time=val)
    await state.set_state(Reschedule.reason)
    
    await callback.message.edit_text("📝 <b>Причина переноса:</b>\n\nНапиши почему переносишь", parse_mode="HTML")
    await callback.answer()


@router.message(Reschedule.reason)
async def resched_reason(message: Message, state: FSMContext):
    reason = message.text
    data = await state.get_data()
    content_id = data["resched_id"]
    new_date_str = data["new_date"]
    new_time_val = data.get("new_time")
    await state.clear()
    
    new_date = date.fromisoformat(new_date_str)
    new_time = None
    
    async with async_session() as session:
        result = await session.execute(
            select(ContentPlan)
            .options(selectinload(ContentPlan.assignee), selectinload(ContentPlan.project), selectinload(ContentPlan.creator))
            .where(ContentPlan.id == content_id)
        )
        c = result.scalar_one_or_none()
        if not c:
            await message.answer("❌ Задача не найдена")
            return
        
        old_date = c.scheduled_date.strftime("%d.%m")
        old_time = c.scheduled_time.strftime("%H:%M") if c.scheduled_time else ""
        
        c.scheduled_date = new_date
        
        if new_time_val and new_time_val != "keep":
            h, m = map(int, new_time_val.split(":"))
            c.scheduled_time = dt_time(h, m)
            new_time = new_time_val
        else:
            new_time = old_time
        
        # Add reason to description
        old_desc = c.description or ""
        timestamp = datetime.now().strftime("%d.%m %H:%M")
        assignee_name = c.assignee.full_name if c.assignee else "?"
        reschedule_note = f"\n⏩ Перенос ({timestamp}) {assignee_name}: {reason}"
        c.description = (old_desc + reschedule_note).strip()
        
        await session.commit()
        
        # Notify task creator (not yourself)
        weekdays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
        new_day = weekdays[new_date.weekday()]
        
        notify = (
            f"📆 <b>Перенос задачи</b>\n\n"
            f"<b>{c.title}</b>\n"
            f"👤 {assignee_name}\n\n"
            f"Было: {old_date} {old_time}\n"
            f"Стало: <b>{new_day} {new_date.strftime('%d.%m')} {new_time}</b>\n\n"
            f"💬 Причина: <i>{reason}</i>"
        )
        
        if c.creator and c.creator.telegram_id and c.creator.telegram_id != message.from_user.id:
            try:
                await message.bot.send_message(c.creator.telegram_id, notify, parse_mode="HTML")
            except Exception:
                pass
    
    await message.answer(
        f"✅ Задача перенесена на {new_date.strftime('%d.%m')} {new_time}\n\n💬 {reason}",
        reply_markup=schedule_menu_kb()
    )


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
    
    await callback.message.edit_text(f"✅ Дата изменена: <b>{date_str}</b>", reply_markup=schedule_menu_kb(), parse_mode="HTML")
    await callback.answer()


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
    
    await callback.message.edit_text(f"✅ Время изменено: <b>{time_str}</b>", reply_markup=schedule_menu_kb(), parse_mode="HTML")
    await callback.answer()


# --- Edit Assignee ---

@router.callback_query(F.data.startswith("sed_assign:"))
async def sed_assign(callback: CallbackQuery, state: FSMContext):
    content_id = int(callback.data.split(":")[1])
    
    # Load current assignees
    async with async_session() as session:
        result = await session.execute(
            select(ContentPlan).options(selectinload(ContentPlan.assignees)).where(ContentPlan.id == content_id)
        )
        c = result.scalar_one_or_none()
        current_ids = [u.id for u in c.assignees] if c and c.assignees else ([c.assignee_id] if c and c.assignee_id else [])
    
    await state.update_data(edit_id=content_id, edit_selected=current_ids)
    await state.set_state(EditSchedule.assignee)
    await _show_edit_user_picker(callback, state)
    await callback.answer()


async def _show_edit_user_picker(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = data.get("edit_selected", [])
    cid = data["edit_id"]
    
    async with async_session() as session:
        result = await session.execute(select(User).where(User.is_active == True).order_by(User.full_name))
        users = result.scalars().all()
    
    builder = InlineKeyboardBuilder()
    for u in users:
        check = "✅ " if u.id in selected else ""
        label = f"{check}{u.full_name}"
        builder.row(InlineKeyboardButton(text=label, callback_data=f"etoggle:{u.id}"))
    builder.row(InlineKeyboardButton(text="✔️ Сохранить", callback_data="snassign:done"))
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data=f"sedit:{cid}"))
    
    count = len(selected)
    await callback.message.edit_text(f"👤 Ответственные ({count}):", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("etoggle:"), EditSchedule.assignee)
async def sed_toggle_user(callback: CallbackQuery, state: FSMContext):
    user_id = int(callback.data.split(":")[1])
    data = await state.get_data()
    selected = data.get("edit_selected", [])
    
    if user_id in selected:
        selected.remove(user_id)
    else:
        selected.append(user_id)
    
    await state.update_data(edit_selected=selected)
    await _show_edit_user_picker(callback, state)
    await callback.answer()


@router.callback_query(F.data.startswith("snassign:"), EditSchedule.assignee)
async def sed_assign_save(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    cid = data["edit_id"]
    selected = data.get("edit_selected", [])
    await state.clear()
    
    async with async_session() as session:
        result = await session.execute(
            select(ContentPlan).options(selectinload(ContentPlan.project)).where(ContentPlan.id == cid)
        )
        c = result.scalar_one_or_none()
        if c:
            # Update legacy field
            c.assignee_id = selected[0] if selected else None
            
            # Clear old assignees
            await session.execute(
                select(ContentAssignee).where(ContentAssignee.content_id == cid)
            )
            from sqlalchemy import delete
            await session.execute(delete(ContentAssignee).where(ContentAssignee.content_id == cid))
            
            # Add new assignees
            for uid in selected:
                session.add(ContentAssignee(content_id=cid, user_id=uid))
            
            await session.commit()
            
            # Notify new assignees
            if selected:
                users_r = await session.execute(select(User).where(User.id.in_(selected)))
                new_assignees = users_r.scalars().all()
                
                weekdays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
                day_name = weekdays[c.scheduled_date.weekday()]
                time_str = c.scheduled_time.strftime("%H:%M") if c.scheduled_time else ""
                
                for u in new_assignees:
                    if u.telegram_id and u.telegram_id != 0 and u.telegram_id != callback.from_user.id:
                        notify = (
                            f"📌 <b>Тебе назначена задача:</b>\n\n"
                            f"<b>{c.title}</b>\n"
                            f"📅 {day_name} {c.scheduled_date.strftime('%d.%m.%Y')} {time_str}"
                        )
                        notify_kb = InlineKeyboardBuilder()
                        notify_kb.row(
                            InlineKeyboardButton(text="✅ Принял", callback_data=f"sst:{cid}:progress"),
                            InlineKeyboardButton(text="📆 Перенести", callback_data=f"resched:{cid}"),
                        )
                        try:
                            await callback.message.bot.send_message(u.telegram_id, notify, reply_markup=notify_kb.as_markup(), parse_mode="HTML")
                        except Exception:
                            pass
    
    await callback.message.edit_text("✅ Ответственные обновлены", reply_markup=schedule_menu_kb())
    await callback.answer()


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
    
    await callback.answer()
    await callback.message.edit_text("🗑 Задача удалена", reply_markup=schedule_menu_kb())


# ==================== Attachments ====================

@router.callback_query(F.data.startswith("satt:"))
async def satt_view(callback: CallbackQuery):
    """View all attachments for a task"""
    content_id = int(callback.data.split(":")[1])
    
    async with async_session() as session:
        result = await session.execute(
            select(TaskAttachment)
            .options(selectinload(TaskAttachment.uploader))
            .where(TaskAttachment.content_id == content_id)
            .order_by(TaskAttachment.created_at)
        )
        attachments = result.scalars().all()
    
    if not attachments:
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="➕ Прикрепить", callback_data=f"satt_add:{content_id}"))
        builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data=f"sedit:{content_id}"))
        await callback.message.edit_text("📎 Нет вложений", reply_markup=builder.as_markup())
        await callback.answer()
        return
    
    # Send all attachments
    type_emoji = {"photo": "📷", "voice": "🎤", "video": "🎬", "video_note": "⭕", "document": "📄"}
    bot = callback.message.bot
    
    for att in attachments:
        try:
            who = att.uploader.full_name if att.uploader else ""
            caption = f"{type_emoji.get(att.file_type, '📎')} {who}" if who else None
            
            if att.file_type == "photo":
                await bot.send_photo(callback.from_user.id, att.file_id, caption=caption)
            elif att.file_type == "voice":
                await bot.send_voice(callback.from_user.id, att.file_id, caption=caption)
            elif att.file_type == "video":
                await bot.send_video(callback.from_user.id, att.file_id, caption=caption)
            elif att.file_type == "video_note":
                await bot.send_video_note(callback.from_user.id, att.file_id)
            elif att.file_type == "document":
                await bot.send_document(callback.from_user.id, att.file_id, caption=caption)
        except Exception as e:
            print(f"Failed to send attachment: {e}")
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ К задаче", callback_data=f"sedit:{content_id}"))
    await bot.send_message(callback.from_user.id, f"📎 Отправлено {len(attachments)} вложений", reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("satt_add:"))
async def satt_add_start(callback: CallbackQuery, state: FSMContext):
    """Start adding attachment to existing task"""
    content_id = int(callback.data.split(":")[1])
    await state.update_data(att_content_id=content_id, att_files=[])
    await state.set_state(EditSchedule.media)
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✅ Готово", callback_data="satt_save"))
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data=f"sedit:{content_id}"))
    
    await callback.message.edit_text(
        "📷 Отправь фото, голосовое или файл\n\nМожно несколько — по одному. Потом нажми Готово.",
        reply_markup=builder.as_markup()
    )
    await callback.answer()


def _att_save_kb(count: int, content_id: int):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=f"✅ Сохранить ({count})", callback_data="satt_save"))
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data=f"sedit:{content_id}"))
    return builder.as_markup()


@router.message(EditSchedule.media, F.photo)
async def satt_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    files = data.get("att_files", [])
    files.append({"file_id": message.photo[-1].file_id, "type": "photo"})
    await state.update_data(att_files=files)
    await message.answer(f"📷 Добавлено ({len(files)})", reply_markup=_att_save_kb(len(files), data["att_content_id"]))


@router.message(EditSchedule.media, F.voice)
async def satt_voice(message: Message, state: FSMContext):
    data = await state.get_data()
    files = data.get("att_files", [])
    files.append({"file_id": message.voice.file_id, "type": "voice"})
    await state.update_data(att_files=files)
    await message.answer(f"🎤 Добавлено ({len(files)})", reply_markup=_att_save_kb(len(files), data["att_content_id"]))


@router.message(EditSchedule.media, F.video)
async def satt_video(message: Message, state: FSMContext):
    data = await state.get_data()
    files = data.get("att_files", [])
    files.append({"file_id": message.video.file_id, "type": "video"})
    await state.update_data(att_files=files)
    await message.answer(f"🎬 Добавлено ({len(files)})", reply_markup=_att_save_kb(len(files), data["att_content_id"]))


@router.message(EditSchedule.media, F.document)
async def satt_doc(message: Message, state: FSMContext):
    data = await state.get_data()
    files = data.get("att_files", [])
    files.append({"file_id": message.document.file_id, "type": "document"})
    await state.update_data(att_files=files)
    await message.answer(f"📄 Добавлено ({len(files)})", reply_markup=_att_save_kb(len(files), data["att_content_id"]))


@router.message(EditSchedule.media, F.video_note)
async def satt_videonote(message: Message, state: FSMContext):
    data = await state.get_data()
    files = data.get("att_files", [])
    files.append({"file_id": message.video_note.file_id, "type": "video_note"})
    await state.update_data(att_files=files)
    await message.answer(f"⭕ Добавлено ({len(files)})", reply_markup=_att_save_kb(len(files), data["att_content_id"]))


@router.callback_query(F.data == "satt_save", EditSchedule.media)
async def satt_save(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    content_id = data["att_content_id"]
    files = data.get("att_files", [])
    await state.clear()
    
    if not files:
        await callback.message.edit_text("📎 Ничего не прикреплено", reply_markup=schedule_menu_kb())
        await callback.answer()
        return
    
    # Get uploader
    async with async_session() as session:
        user_r = await session.execute(select(User.id).where(User.telegram_id == callback.from_user.id))
        uploader_id = user_r.scalar_one_or_none()
        
        for mf in files:
            session.add(TaskAttachment(
                content_id=content_id,
                file_id=mf["file_id"],
                file_type=mf["type"],
                uploaded_by=uploader_id,
            ))
        await session.commit()
    
    await callback.message.edit_text(f"✅ {len(files)} вложений сохранено", reply_markup=schedule_menu_kb())
    await callback.answer()
    await sched_edit(callback)


# ==================== Cancel ====================

@router.callback_query(F.data == "sched:cancel")
@router.callback_query(F.data == "content:cancel")
@router.callback_query(F.data == "tasks:cancel")
async def sched_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Отменено", reply_markup=schedule_menu_kb())
    await callback.answer()
