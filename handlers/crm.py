"""
ZBS CRM Bot — Client & Deal Handlers
CRM pipeline management
"""

from datetime import date
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from database import (
    async_session, Client, Deal, DealStatus, Project, User
)
from keyboards import (
    clients_menu_kb, deal_status_kb, client_select_kb,
    project_select_kb, back_to_menu_kb, skip_kb
)

router = Router()

async def _get_user_id(tg_id: int) -> int | None:
    async with async_session() as session:
        result = await session.execute(select(User.id).where(User.telegram_id == tg_id))
        return result.scalar_one_or_none()

DEAL_STATUS_EMOJI = {
    DealStatus.LEAD: "🔵",
    DealStatus.NEGOTIATION: "🟡",
    DealStatus.PROPOSAL: "📄",
    DealStatus.CONTRACT: "📝",
    DealStatus.ACTIVE: "🟢",
    DealStatus.COMPLETED: "✅",
    DealStatus.LOST: "🔴",
}

DEAL_STATUS_NAME = {
    DealStatus.LEAD: "Лид",
    DealStatus.NEGOTIATION: "Переговоры",
    DealStatus.PROPOSAL: "КП отправлено",
    DealStatus.CONTRACT: "Договор",
    DealStatus.ACTIVE: "В работе",
    DealStatus.COMPLETED: "Завершено",
    DealStatus.LOST: "Потеряно",
}


# ==================== FSM States ====================

class AddClient(StatesGroup):
    name = State()
    contact_person = State()
    contact_telegram = State()
    notes = State()

class AddDeal(StatesGroup):
    client = State()
    title = State()
    amount = State()
    project = State()
    deadline = State()
    description = State()


# ==================== Clients Menu ====================

@router.callback_query(F.data == "menu:clients")
async def clients_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "👥 <b>CRM — Клиенты и сделки</b>\n\nВыбери действие:",
        reply_markup=clients_menu_kb(),
        parse_mode="HTML"
    )
    await callback.answer()


# ==================== Client List ====================

@router.callback_query(F.data == "clients:list")
async def clients_list(callback: CallbackQuery):
    user_id = await _get_user_id(callback.from_user.id)
    
    async with async_session() as session:
        result = await session.execute(
            select(Client).where(
                Client.is_active == True,
                Client.created_by_user_id == user_id
            ).order_by(Client.name)
        )
        clients = result.scalars().all()
        
        # Get deal counts per client
        deal_counts = {}
        for c in clients:
            result2 = await session.execute(
                select(func.count(Deal.id)).where(
                    Deal.client_id == c.id,
                    Deal.status.notin_([DealStatus.COMPLETED, DealStatus.LOST])
                )
            )
            deal_counts[c.id] = result2.scalar() or 0
    
    if not clients:
        text = "👥 <b>Клиенты</b>\n\n🤷 Список пуст"
    else:
        lines = ["👥 <b>Клиенты ZBS</b>\n"]
        for c in clients:
            deals = deal_counts.get(c.id, 0)
            deals_str = f" — {deals} сделок" if deals else ""
            contact = f" (@{c.contact_telegram})" if c.contact_telegram else ""
            lines.append(f"• <b>{c.name}</b>{contact}{deals_str}")
        text = "\n".join(lines)
    
    builder = InlineKeyboardBuilder()
    for c in clients:
        builder.row(InlineKeyboardButton(
            text=f"📋 {c.name}",
            callback_data=f"client_view:{c.id}"
        ))
    builder.row(
        InlineKeyboardButton(text="➕ Новый клиент", callback_data="clients:add"),
        InlineKeyboardButton(text="◀️ Назад", callback_data="menu:clients"),
    )
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()


# ==================== Client Detail ====================

@router.callback_query(F.data.startswith("client_view:"))
async def client_view(callback: CallbackQuery):
    client_id = int(callback.data.split(":")[1])
    
    async with async_session() as session:
        result = await session.execute(
            select(Client).where(Client.id == client_id)
        )
        c = result.scalar_one_or_none()
        if not c:
            await callback.answer("Клиент не найден")
            return
        
        # Get deals
        result = await session.execute(
            select(Deal)
            .options(selectinload(Deal.project))
            .where(Deal.client_id == client_id)
            .order_by(Deal.created_at.desc())
        )
        deals = result.scalars().all()
    
    lines = [f"👤 <b>{c.name}</b>\n"]
    if c.contact_person:
        lines.append(f"📞 Контакт: {c.contact_person}")
    if c.contact_telegram:
        lines.append(f"✈️ Telegram: @{c.contact_telegram}")
    if c.notes:
        lines.append(f"📝 {c.notes}")
    
    if deals:
        lines.append(f"\n💼 <b>Сделки ({len(deals)}):</b>")
        total = 0
        for d in deals:
            emoji = DEAL_STATUS_EMOJI.get(d.status, "❓")
            amount_str = f" — ${d.amount:,.0f}" if d.amount else ""
            lines.append(f"  {emoji} {d.title}{amount_str}")
            if d.status in (DealStatus.ACTIVE, DealStatus.CONTRACT):
                total += d.amount or 0
        if total:
            lines.append(f"\n💰 В работе: ${total:,.0f}")
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="➕ Новая сделка", callback_data=f"deal_for_client:{client_id}"))
    for d in deals:
        if d.status not in (DealStatus.COMPLETED, DealStatus.LOST):
            builder.row(InlineKeyboardButton(
                text=f"✏️ {d.title[:30]}",
                callback_data=f"deal_view:{d.id}"
            ))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="clients:list"))
    
    await callback.message.edit_text("\n".join(lines), reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()


# ==================== Add Client ====================

@router.callback_query(F.data == "clients:add")
async def client_add_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AddClient.name)
    await callback.message.edit_text("🏢 <b>Новый клиент</b>\n\nВведи название компании:", parse_mode="HTML")
    await callback.answer()


@router.message(AddClient.name)
async def client_add_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(AddClient.contact_person)
    await message.answer("Контактное лицо (или пропусти):", reply_markup=skip_kb("client_skip:contact"))


@router.callback_query(F.data == "client_skip:contact", AddClient.contact_person)
async def client_skip_contact(callback: CallbackQuery, state: FSMContext):
    await state.update_data(contact_person=None)
    await state.set_state(AddClient.contact_telegram)
    await callback.message.edit_text("Telegram контакта (без @, или пропусти):", reply_markup=skip_kb("client_skip:tg"))
    await callback.answer()


@router.message(AddClient.contact_person)
async def client_add_contact(message: Message, state: FSMContext):
    await state.update_data(contact_person=message.text)
    await state.set_state(AddClient.contact_telegram)
    await message.answer("Telegram контакта (без @, или пропусти):", reply_markup=skip_kb("client_skip:tg"))


@router.callback_query(F.data == "client_skip:tg", AddClient.contact_telegram)
async def client_skip_tg(callback: CallbackQuery, state: FSMContext):
    await state.update_data(contact_telegram=None)
    await state.set_state(AddClient.notes)
    await callback.message.edit_text("Заметки о клиенте (или пропусти):", reply_markup=skip_kb("client_skip:notes"))
    await callback.answer()


@router.message(AddClient.contact_telegram)
async def client_add_tg(message: Message, state: FSMContext):
    tg = message.text.replace("@", "").strip()
    await state.update_data(contact_telegram=tg)
    await state.set_state(AddClient.notes)
    await message.answer("Заметки о клиенте (или пропусти):", reply_markup=skip_kb("client_skip:notes"))


@router.callback_query(F.data == "client_skip:notes", AddClient.notes)
async def client_skip_notes(callback: CallbackQuery, state: FSMContext):
    await state.update_data(notes=None)
    await _save_client(callback.message, state, callback)


@router.message(AddClient.notes)
async def client_add_notes(message: Message, state: FSMContext):
    await state.update_data(notes=message.text)
    await _save_client(message, state)


async def _save_client(message: Message, state: FSMContext, callback: CallbackQuery = None):
    data = await state.get_data()
    tg_id = callback.from_user.id if callback else message.from_user.id
    await state.clear()
    
    user_id = await _get_user_id(tg_id)
    
    async with async_session() as session:
        client = Client(
            name=data["name"],
            contact_person=data.get("contact_person"),
            contact_telegram=data.get("contact_telegram"),
            notes=data.get("notes"),
            created_by_user_id=user_id,
        )
        session.add(client)
        await session.commit()
    
    text = f"✅ Клиент <b>{data['name']}</b> добавлен!"
    target = callback.message if callback else message
    if callback:
        await target.edit_text(text, reply_markup=clients_menu_kb(), parse_mode="HTML")
        await callback.answer()
    else:
        await target.answer(text, reply_markup=clients_menu_kb(), parse_mode="HTML")


# ==================== Deals ====================

@router.callback_query(F.data == "deals:list")
async def deals_list(callback: CallbackQuery):
    user_id = await _get_user_id(callback.from_user.id)
    
    async with async_session() as session:
        result = await session.execute(
            select(Deal)
            .options(selectinload(Deal.client), selectinload(Deal.project))
            .where(
                Deal.status.notin_([DealStatus.COMPLETED, DealStatus.LOST]),
                Deal.created_by_user_id == user_id
            )
            .order_by(Deal.status, Deal.deadline.asc().nulls_last())
        )
        deals = result.scalars().all()
    
    if not deals:
        text = "💼 <b>Активные сделки</b>\n\n🤷 Нет активных сделок"
    else:
        lines = ["💼 <b>Активные сделки</b>\n"]
        total = 0
        for d in deals:
            emoji = DEAL_STATUS_EMOJI.get(d.status, "❓")
            status = DEAL_STATUS_NAME.get(d.status, "")
            amount = f"${d.amount:,.0f}" if d.amount else ""
            deadline = f" до {d.deadline.strftime('%d.%m')}" if d.deadline else ""
            lines.append(f"{emoji} <b>{d.title}</b> — {d.client.name}")
            lines.append(f"   {status} {amount}{deadline}\n")
            total += d.amount or 0
        lines.append(f"💰 Итого в пайплайне: <b>${total:,.0f}</b>")
        text = "\n".join(lines)
    
    builder = InlineKeyboardBuilder()
    for d in deals:
        builder.row(InlineKeyboardButton(
            text=f"{DEAL_STATUS_EMOJI.get(d.status, '')} {d.title[:30]}",
            callback_data=f"deal_view:{d.id}"
        ))
    builder.row(
        InlineKeyboardButton(text="➕ Новая сделка", callback_data="deals:add"),
        InlineKeyboardButton(text="◀️ Назад", callback_data="menu:clients"),
    )
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()


# ==================== Deal Pipeline View ====================

@router.callback_query(F.data == "deals:pipeline")
async def deals_pipeline(callback: CallbackQuery):
    user_id = await _get_user_id(callback.from_user.id)
    
    async with async_session() as session:
        result = await session.execute(
            select(Deal)
            .options(selectinload(Deal.client))
            .where(
                Deal.status.notin_([DealStatus.COMPLETED, DealStatus.LOST]),
                Deal.created_by_user_id == user_id
            )
            .order_by(Deal.amount.desc().nulls_last())
        )
        deals = result.scalars().all()
    
    pipeline = {}
    for d in deals:
        if d.status not in pipeline:
            pipeline[d.status] = []
        pipeline[d.status].append(d)
    
    stages = [
        DealStatus.LEAD, DealStatus.NEGOTIATION, DealStatus.PROPOSAL,
        DealStatus.CONTRACT, DealStatus.ACTIVE
    ]
    
    lines = ["📊 <b>Sales Pipeline</b>\n"]
    grand_total = 0
    
    for stage in stages:
        items = pipeline.get(stage, [])
        emoji = DEAL_STATUS_EMOJI[stage]
        name = DEAL_STATUS_NAME[stage]
        stage_total = sum(d.amount or 0 for d in items)
        grand_total += stage_total
        
        lines.append(f"\n{emoji} <b>{name}</b> ({len(items)}) — ${stage_total:,.0f}")
        for d in items:
            amount = f" ${d.amount:,.0f}" if d.amount else ""
            lines.append(f"   • {d.title} ({d.client.name}){amount}")
    
    lines.append(f"\n═══════════════")
    lines.append(f"💰 Всего в pipeline: <b>${grand_total:,.0f}</b>")
    
    await callback.message.edit_text(
        "\n".join(lines), reply_markup=clients_menu_kb(), parse_mode="HTML"
    )
    await callback.answer()


# ==================== Deal View ====================

@router.callback_query(F.data.startswith("deal_view:"))
async def deal_view(callback: CallbackQuery):
    deal_id = int(callback.data.split(":")[1])
    
    async with async_session() as session:
        result = await session.execute(
            select(Deal)
            .options(selectinload(Deal.client), selectinload(Deal.project))
            .where(Deal.id == deal_id)
        )
        d = result.scalar_one_or_none()
    
    if not d:
        await callback.answer("Сделка не найдена")
        return
    
    lines = [
        f"💼 <b>{d.title}</b>\n",
        f"🏢 Клиент: {d.client.name}",
        f"📊 Статус: {DEAL_STATUS_EMOJI.get(d.status, '')} {DEAL_STATUS_NAME.get(d.status, '')}",
    ]
    if d.amount:
        lines.append(f"💰 Сумма: ${d.amount:,.0f} {d.currency}")
    if d.project:
        lines.append(f"📁 Проект: {d.project.emoji} {d.project.name}")
    if d.deadline:
        lines.append(f"📅 Дедлайн: {d.deadline.strftime('%d.%m.%Y')}")
    if d.description:
        lines.append(f"\n📝 {d.description}")
    
    lines.append("\n<b>Изменить статус:</b>")
    
    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=deal_status_kb(deal_id),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("dstatus:"))
async def deal_change_status(callback: CallbackQuery):
    parts = callback.data.split(":")
    deal_id = int(parts[1])
    new_status = DealStatus(parts[2])
    
    async with async_session() as session:
        result = await session.execute(select(Deal).where(Deal.id == deal_id))
        d = result.scalar_one_or_none()
        if d:
            d.status = new_status
            await session.commit()
    
    emoji = DEAL_STATUS_EMOJI.get(new_status, "")
    name = DEAL_STATUS_NAME.get(new_status, "")
    await callback.answer(f"Статус: {emoji} {name}")
    await deal_view(callback)


# ==================== Add Deal ====================

@router.callback_query(F.data == "deals:add")
async def deal_add_start(callback: CallbackQuery, state: FSMContext):
    user_id = await _get_user_id(callback.from_user.id)
    
    async with async_session() as session:
        result = await session.execute(
            select(Client).where(Client.is_active == True, Client.created_by_user_id == user_id).order_by(Client.name)
        )
        clients = result.scalars().all()
    
    if not clients:
        await callback.answer("Сначала добавь клиента!")
        return
    
    await state.set_state(AddDeal.client)
    await callback.message.edit_text(
        "💼 <b>Новая сделка</b>\n\nВыбери клиента:",
        reply_markup=client_select_kb(clients, "deal_client"),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("deal_for_client:"))
async def deal_add_for_client(callback: CallbackQuery, state: FSMContext):
    client_id = int(callback.data.split(":")[1])
    await state.update_data(client_id=client_id)
    await state.set_state(AddDeal.title)
    await callback.message.edit_text("Название сделки:", parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("deal_client:"), AddDeal.client)
async def deal_add_client(callback: CallbackQuery, state: FSMContext):
    client_id = int(callback.data.split(":")[1])
    await state.update_data(client_id=client_id)
    await state.set_state(AddDeal.title)
    await callback.message.edit_text("Название сделки:")
    await callback.answer()


@router.message(AddDeal.title)
async def deal_add_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text)
    await state.set_state(AddDeal.amount)
    await message.answer("Сумма в USD (число, или пропусти):", reply_markup=skip_kb("deal_skip:amount"))


@router.callback_query(F.data == "deal_skip:amount", AddDeal.amount)
async def deal_skip_amount(callback: CallbackQuery, state: FSMContext):
    await state.update_data(amount=0)
    await _deal_select_project(callback, state)


@router.message(AddDeal.amount)
async def deal_add_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", "").replace("$", "").strip())
    except ValueError:
        await message.answer("❌ Введи число. Например: 5000")
        return
    await state.update_data(amount=amount)
    
    async with async_session() as session:
        result = await session.execute(select(Project).where(Project.is_active == True))
        projects = result.scalars().all()
    
    await state.set_state(AddDeal.project)
    await message.answer("Проект:", reply_markup=project_select_kb(projects, "deal_project"))


async def _deal_select_project(callback: CallbackQuery, state: FSMContext):
    async with async_session() as session:
        result = await session.execute(select(Project).where(Project.is_active == True))
        projects = result.scalars().all()
    await state.set_state(AddDeal.project)
    await callback.message.edit_text("Проект:", reply_markup=project_select_kb(projects, "deal_project"))
    await callback.answer()


@router.callback_query(F.data.startswith("deal_project:"), AddDeal.project)
async def deal_add_project(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split(":")[1]
    project_id = None if val == "skip" else int(val)
    await state.update_data(project_id=project_id)
    await state.set_state(AddDeal.description)
    await callback.message.edit_text("Описание (или пропусти):", reply_markup=skip_kb("deal_skip:desc"))
    await callback.answer()


@router.callback_query(F.data == "deal_skip:desc", AddDeal.description)
async def deal_skip_desc(callback: CallbackQuery, state: FSMContext):
    await state.update_data(description=None)
    await _save_deal(callback.message, state, callback)


@router.message(AddDeal.description)
async def deal_add_desc(message: Message, state: FSMContext):
    await state.update_data(description=message.text)
    await _save_deal(message, state)


async def _save_deal(message: Message, state: FSMContext, callback: CallbackQuery = None):
    data = await state.get_data()
    tg_id = callback.from_user.id if callback else message.from_user.id
    await state.clear()
    
    user_id = await _get_user_id(tg_id)
    
    async with async_session() as session:
        deal = Deal(
            title=data["title"],
            client_id=data["client_id"],
            project_id=data.get("project_id"),
            amount=data.get("amount", 0),
            description=data.get("description"),
            status=DealStatus.LEAD,
            created_by_user_id=user_id,
        )
        session.add(deal)
        await session.commit()
    
    amount_str = f" — ${data.get('amount', 0):,.0f}" if data.get('amount') else ""
    text = f"✅ Сделка <b>{data['title']}</b>{amount_str} добавлена!\n\nСтатус: 🔵 Лид"
    
    target = callback.message if callback else message
    if callback:
        await target.edit_text(text, reply_markup=clients_menu_kb(), parse_mode="HTML")
        await callback.answer()
    else:
        await target.answer(text, reply_markup=clients_menu_kb(), parse_mode="HTML")
