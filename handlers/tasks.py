"""
ZBS CRM Bot — Task Handlers
Task creation, assignment, tracking
"""

from datetime import date, datetime, timedelta
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import selectinload

from database import (
    async_session, Task, TaskPriority, TaskStatus, Project, User
)
from keyboards import (
    tasks_menu_kb, task_priority_kb, task_action_kb,
    user_select_kb, project_select_kb, back_to_menu_kb, skip_kb
)

router = Router()

PRIORITY_EMOJI = {
    TaskPriority.LOW: "🟢",
    TaskPriority.MEDIUM: "🟡",
    TaskPriority.HIGH: "🟠",
    TaskPriority.URGENT: "🔴",
}

STATUS_EMOJI = {
    TaskStatus.TODO: "⬜",
    TaskStatus.IN_PROGRESS: "🔄",
    TaskStatus.DONE: "✅",
    TaskStatus.CANCELLED: "❌",
}


def format_task(t: Task, show_assignee: bool = True) -> str:
    priority = PRIORITY_EMOJI.get(t.priority, "⬜")
    status = STATUS_EMOJI.get(t.status, "⬜")
    
    assignee_str = ""
    if show_assignee and t.assignee:
        assignee_str = f" → {t.assignee.full_name}"
    
    deadline_str = ""
    if t.deadline:
        days_left = (t.deadline.date() - date.today()).days
        if days_left < 0:
            deadline_str = f" ⚠️ просрочено {abs(days_left)}д"
        elif days_left == 0:
            deadline_str = " ⏰ сегодня!"
        elif days_left == 1:
            deadline_str = " ⏰ завтра"
        else:
            deadline_str = f" 📅 {t.deadline.strftime('%d.%m')}"
    
    project_str = ""
    if t.project:
        project_str = f" [{t.project.emoji}]"
    
    return f"{status}{priority} <b>{t.title}</b>{assignee_str}{deadline_str}{project_str}"


# ==================== FSM States ====================

class AddTask(StatesGroup):
    title = State()
    description = State()
    priority = State()
    assignee = State()
    project = State()
    deadline = State()


# ==================== Tasks Menu ====================

@router.callback_query(F.data == "menu:tasks")
async def tasks_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "📋 <b>Задачи</b>\n\nВыбери действие:",
        reply_markup=tasks_menu_kb(),
        parse_mode="HTML"
    )
    await callback.answer()


# ==================== My Tasks ====================

@router.callback_query(F.data == "tasks:my")
@router.message(Command("mytasks"))
async def tasks_my(event, state: FSMContext = None):
    tg_id = event.from_user.id
    
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == tg_id))
        user = result.scalar_one_or_none()
        if not user:
            text = "❌ Сначала напиши /start"
            if isinstance(event, CallbackQuery):
                await event.answer(text, show_alert=True)
            else:
                await event.answer(text)
            return
        
        result = await session.execute(
            select(Task)
            .options(selectinload(Task.project), selectinload(Task.creator))
            .where(and_(
                Task.assignee_id == user.id,
                Task.status.in_([TaskStatus.TODO, TaskStatus.IN_PROGRESS])
            ))
            .order_by(Task.priority.desc(), Task.deadline.asc().nulls_last())
        )
        tasks = result.scalars().all()
    
    if not tasks:
        text = "📋 <b>Мои задачи</b>\n\n✨ Нет активных задач"
    else:
        lines = [f"📋 <b>Мои задачи</b> ({len(tasks)})\n"]
        for t in tasks:
            lines.append(format_task(t, show_assignee=False))
        text = "\n".join(lines)
    
    builder = InlineKeyboardBuilder()
    for t in tasks:
        short = t.title[:25] + "..." if len(t.title) > 25 else t.title
        builder.row(InlineKeyboardButton(text=f"✏️ {short}", callback_data=f"task_view:{t.id}"))
    builder.row(
        InlineKeyboardButton(text="➕ Создать", callback_data="tasks:add"),
        InlineKeyboardButton(text="◀️ Назад", callback_data="menu:tasks"),
    )
    
    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
        await event.answer()
    else:
        await event.answer(text, reply_markup=builder.as_markup(), parse_mode="HTML")


# ==================== All Tasks ====================

@router.callback_query(F.data == "tasks:all")
async def tasks_all(callback: CallbackQuery):
    async with async_session() as session:
        result = await session.execute(
            select(Task)
            .options(selectinload(Task.assignee), selectinload(Task.project))
            .where(Task.status.in_([TaskStatus.TODO, TaskStatus.IN_PROGRESS]))
            .order_by(Task.priority.desc(), Task.deadline.asc().nulls_last())
            .limit(30)
        )
        tasks = result.scalars().all()
    
    if not tasks:
        text = "📋 <b>Все задачи</b>\n\n✨ Нет активных задач"
    else:
        lines = [f"📋 <b>Все задачи</b> ({len(tasks)})\n"]
        for t in tasks:
            lines.append(format_task(t))
        text = "\n".join(lines)
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="➕ Создать", callback_data="tasks:add"),
        InlineKeyboardButton(text="◀️ Назад", callback_data="menu:tasks"),
    )
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()


# ==================== Urgent Tasks ====================

@router.callback_query(F.data == "tasks:urgent")
async def tasks_urgent(callback: CallbackQuery):
    today = date.today()
    tomorrow = today + timedelta(days=1)
    
    async with async_session() as session:
        result = await session.execute(
            select(Task)
            .options(selectinload(Task.assignee), selectinload(Task.project))
            .where(and_(
                Task.status.in_([TaskStatus.TODO, TaskStatus.IN_PROGRESS]),
                or_(
                    Task.priority == TaskPriority.URGENT,
                    Task.deadline <= datetime.combine(tomorrow, datetime.max.time())
                )
            ))
            .order_by(Task.deadline.asc().nulls_last())
        )
        tasks = result.scalars().all()
    
    if not tasks:
        text = "🔥 <b>Срочные задачи</b>\n\n✨ Ничего срочного!"
    else:
        lines = [f"🔥 <b>Срочные задачи</b> ({len(tasks)})\n"]
        for t in tasks:
            lines.append(format_task(t))
        text = "\n".join(lines)
    
    await callback.message.edit_text(text, reply_markup=tasks_menu_kb(), parse_mode="HTML")
    await callback.answer()


# ==================== Task Detail ====================

@router.callback_query(F.data.startswith("task_view:"))
async def task_view(callback: CallbackQuery):
    task_id = int(callback.data.split(":")[1])
    
    async with async_session() as session:
        result = await session.execute(
            select(Task)
            .options(
                selectinload(Task.assignee),
                selectinload(Task.creator),
                selectinload(Task.project)
            )
            .where(Task.id == task_id)
        )
        t = result.scalar_one_or_none()
    
    if not t:
        await callback.answer("Задача не найдена", show_alert=True)
        return
    
    lines = [
        f"📋 <b>{t.title}</b>\n",
        f"Статус: {STATUS_EMOJI.get(t.status, '')} {t.status.value}",
        f"Приоритет: {PRIORITY_EMOJI.get(t.priority, '')} {t.priority.value}",
    ]
    if t.assignee:
        lines.append(f"Ответственный: {t.assignee.full_name}")
    if t.creator:
        lines.append(f"Создал: {t.creator.full_name}")
    if t.project:
        lines.append(f"Проект: {t.project.emoji} {t.project.name}")
    if t.deadline:
        lines.append(f"Дедлайн: {t.deadline.strftime('%d.%m.%Y %H:%M')}")
    if t.description:
        lines.append(f"\n📝 {t.description}")
    
    # Check if current user is assignee
    is_assignee = t.assignee and t.assignee.telegram_id == callback.from_user.id
    
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=task_action_kb(task_id, is_assignee),
        parse_mode="HTML"
    )
    await callback.answer()


# ==================== Change Task Status ====================

@router.callback_query(F.data.startswith("tstatus:"))
async def task_change_status(callback: CallbackQuery):
    parts = callback.data.split(":")
    task_id = int(parts[1])
    new_status = TaskStatus(parts[2])
    
    async with async_session() as session:
        result = await session.execute(select(Task).where(Task.id == task_id))
        t = result.scalar_one_or_none()
        if t:
            t.status = new_status
            if new_status == TaskStatus.DONE:
                t.completed_at = datetime.utcnow()
            await session.commit()
    
    emoji = STATUS_EMOJI.get(new_status, "")
    await callback.answer(f"Статус: {emoji} {new_status.value}", show_alert=True)
    
    # Refresh view
    callback.data = f"task_view:{task_id}"
    await task_view(callback)


# ==================== Add Task ====================

@router.callback_query(F.data == "tasks:add")
@router.message(Command("addtask"))
async def task_add_start(event, state: FSMContext):
    await state.set_state(AddTask.title)
    text = "📋 <b>Новая задача</b>\n\nВведи название задачи:"
    
    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, parse_mode="HTML")
        await event.answer()
    else:
        await event.answer(text, parse_mode="HTML")


@router.message(AddTask.title)
async def task_add_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text)
    await state.set_state(AddTask.priority)
    await message.answer("Приоритет:", reply_markup=task_priority_kb())


@router.callback_query(F.data.startswith("tpriority:"), AddTask.priority)
async def task_add_priority(callback: CallbackQuery, state: FSMContext):
    priority = callback.data.split(":")[1]
    await state.update_data(priority=priority)
    await state.set_state(AddTask.assignee)
    
    async with async_session() as session:
        result = await session.execute(select(User).where(User.is_active == True).order_by(User.full_name))
        users = result.scalars().all()
    
    await callback.message.edit_text("Назначить на:", reply_markup=user_select_kb(users, "task_assign"))
    await callback.answer()


@router.callback_query(F.data.startswith("task_assign:"), AddTask.assignee)
async def task_add_assignee(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split(":")[1]
    assignee_id = None if val == "skip" else int(val)
    await state.update_data(assignee_id=assignee_id)
    await state.set_state(AddTask.project)
    
    async with async_session() as session:
        result = await session.execute(select(Project).where(Project.is_active == True))
        projects = result.scalars().all()
    
    await callback.message.edit_text("Проект:", reply_markup=project_select_kb(projects, "task_project"))
    await callback.answer()


@router.callback_query(F.data.startswith("task_project:"), AddTask.project)
async def task_add_project(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split(":")[1]
    project_id = None if val == "skip" else int(val)
    await state.update_data(project_id=project_id)
    await state.set_state(AddTask.deadline)
    
    builder = InlineKeyboardBuilder()
    today = date.today()
    options = [
        ("Сегодня", 0), ("Завтра", 1), ("Через 3 дня", 3),
        ("Через неделю", 7), ("Через 2 недели", 14), ("Через месяц", 30),
    ]
    for label, days in options:
        d = today + timedelta(days=days)
        builder.row(InlineKeyboardButton(text=label, callback_data=f"tdeadline:{d.isoformat()}"))
    builder.row(InlineKeyboardButton(text="⏭ Без дедлайна", callback_data="tdeadline:skip"))
    
    await callback.message.edit_text("📅 Дедлайн:", reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("tdeadline:"), AddTask.deadline)
async def task_add_deadline(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split(":")[1]
    deadline = None if val == "skip" else val
    await state.update_data(deadline=deadline)
    await state.set_state(AddTask.description)
    
    await callback.message.edit_text("📝 Описание (или пропусти):", reply_markup=skip_kb("task_skip:desc"))
    await callback.answer()


@router.callback_query(F.data == "task_skip:desc", AddTask.description)
async def task_skip_desc(callback: CallbackQuery, state: FSMContext):
    await state.update_data(description=None)
    await _save_task(callback.message, state, callback)


@router.message(AddTask.description)
async def task_add_desc(message: Message, state: FSMContext):
    await state.update_data(description=message.text)
    await _save_task(message, state)


async def _save_task(message: Message, state: FSMContext, callback: CallbackQuery = None):
    data = await state.get_data()
    tg_id = callback.from_user.id if callback else message.from_user.id
    await state.clear()
    
    # Get creator
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == tg_id))
        creator = result.scalar_one_or_none()
    
    deadline_dt = None
    if data.get("deadline"):
        deadline_dt = datetime.fromisoformat(data["deadline"] + "T23:59:00")
    
    async with async_session() as session:
        task = Task(
            title=data["title"],
            description=data.get("description"),
            priority=TaskPriority(data["priority"]),
            assignee_id=data.get("assignee_id"),
            creator_id=creator.id if creator else None,
            project_id=data.get("project_id"),
            deadline=deadline_dt,
            status=TaskStatus.TODO,
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)
        
        # Notify assignee if different from creator
        if task.assignee_id and creator and task.assignee_id != creator.id:
            result = await session.execute(select(User).where(User.id == task.assignee_id))
            assignee = result.scalar_one_or_none()
            if assignee:
                # Will send notification via bot
                task._notify_assignee = assignee
    
    priority_emoji = PRIORITY_EMOJI.get(TaskPriority(data["priority"]), "")
    text = f"✅ Задача создана!\n\n{priority_emoji} <b>{data['title']}</b>"
    if deadline_dt:
        text += f"\n📅 Дедлайн: {deadline_dt.strftime('%d.%m.%Y')}"
    
    target = callback.message if callback else message
    if callback:
        await target.edit_text(text, reply_markup=tasks_menu_kb(), parse_mode="HTML")
        await callback.answer()
    else:
        await target.answer(text, reply_markup=tasks_menu_kb(), parse_mode="HTML")


# ==================== Cancel ====================

@router.callback_query(F.data == "tasks:cancel")
async def tasks_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Отменено", reply_markup=tasks_menu_kb())
    await callback.answer()
