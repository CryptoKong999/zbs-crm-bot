"""
ZBS CRM Bot — Finance Handlers
Income/expense tracking by project
"""

from datetime import date, datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select, func, and_

from database import (
    async_session, Finance, FinanceType, Project, User
)
from keyboards import (
    finance_menu_kb, project_select_kb, back_to_menu_kb, skip_kb
)

router = Router()


# ==================== FSM States ====================

class AddFinance(StatesGroup):
    type = State()
    amount = State()
    category = State()
    project = State()
    description = State()


# ==================== Finance Menu ====================

@router.callback_query(F.data == "menu:finance")
async def finance_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    
    # Quick summary
    today = date.today()
    month_start = today.replace(day=1)
    
    async with async_session() as session:
        inc = await session.execute(
            select(func.coalesce(func.sum(Finance.amount), 0)).where(
                Finance.type == FinanceType.INCOME,
                Finance.record_date >= month_start
            )
        )
        exp = await session.execute(
            select(func.coalesce(func.sum(Finance.amount), 0)).where(
                Finance.type == FinanceType.EXPENSE,
                Finance.record_date >= month_start
            )
        )
        income = inc.scalar() or 0
        expense = exp.scalar() or 0
    
    text = (
        f"💰 <b>Финансы</b>\n\n"
        f"📅 {today.strftime('%B %Y')}\n"
        f"💵 Приход: ${income:,.0f}\n"
        f"💸 Расход: ${expense:,.0f}\n"
        f"📊 Баланс: <b>${income - expense:,.0f}</b>\n\n"
        f"Выбери действие:"
    )
    
    await callback.message.edit_text(text, reply_markup=finance_menu_kb(), parse_mode="HTML")
    await callback.answer()


# ==================== Add Income ====================

@router.callback_query(F.data == "fin:add_income")
async def fin_add_income(callback: CallbackQuery, state: FSMContext):
    await state.update_data(fin_type=FinanceType.INCOME.value)
    await state.set_state(AddFinance.amount)
    await callback.message.edit_text("💵 <b>Новый приход</b>\n\nСумма в USD:", parse_mode="HTML")
    await callback.answer()


# ==================== Add Expense ====================

@router.callback_query(F.data == "fin:add_expense")
async def fin_add_expense(callback: CallbackQuery, state: FSMContext):
    await state.update_data(fin_type=FinanceType.EXPENSE.value)
    await state.set_state(AddFinance.amount)
    await callback.message.edit_text("💸 <b>Новый расход</b>\n\nСумма в USD:", parse_mode="HTML")
    await callback.answer()


@router.message(AddFinance.amount)
async def fin_add_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", "").replace("$", "").strip())
    except ValueError:
        await message.answer("❌ Введи число. Например: 500")
        return
    
    await state.update_data(amount=amount)
    await state.set_state(AddFinance.category)
    
    data = await state.get_data()
    is_income = data["fin_type"] == FinanceType.INCOME.value
    
    categories = [
        ("📺 Реклама", "Реклама"),
        ("🎙 Подкаст", "Подкаст"),
        ("🎬 Продакшн", "Продакшн"),
        ("🤝 Спонсор", "Спонсорство"),
    ] if is_income else [
        ("👥 Зарплата", "Зарплата"),
        ("🎬 Продакшн", "Продакшн"),
        ("📢 Маркетинг", "Маркетинг"),
        ("🏢 Аренда/офис", "Офис"),
        ("🔧 Оборудование", "Оборудование"),
        ("📦 Другое", "Другое"),
    ]
    
    builder = InlineKeyboardBuilder()
    for i in range(0, len(categories), 2):
        row = [InlineKeyboardButton(text=c[0], callback_data=f"fcat:{c[1]}") for c in categories[i:i+2]]
        builder.row(*row)
    builder.row(InlineKeyboardButton(text="⏭ Без категории", callback_data="fcat:skip"))
    
    await message.answer("Категория:", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("fcat:"), AddFinance.category)
async def fin_add_category(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split(":")[1]
    category = None if val == "skip" else val
    await state.update_data(category=category)
    await state.set_state(AddFinance.project)
    
    async with async_session() as session:
        result = await session.execute(select(Project).where(Project.is_active == True))
        projects = result.scalars().all()
    
    await callback.message.edit_text("Проект:", reply_markup=project_select_kb(projects, "fproject"))
    await callback.answer()


@router.callback_query(F.data.startswith("fproject:"), AddFinance.project)
async def fin_add_project(callback: CallbackQuery, state: FSMContext):
    val = callback.data.split(":")[1]
    project_id = None if val == "skip" else int(val)
    await state.update_data(project_id=project_id)
    await state.set_state(AddFinance.description)
    
    await callback.message.edit_text("Описание (или пропусти):", reply_markup=skip_kb("fin_skip:desc"))
    await callback.answer()


@router.callback_query(F.data == "fin_skip:desc", AddFinance.description)
async def fin_skip_desc(callback: CallbackQuery, state: FSMContext):
    await state.update_data(description=None)
    await _save_finance(callback.message, state, callback)


@router.message(AddFinance.description)
async def fin_add_desc(message: Message, state: FSMContext):
    await state.update_data(description=message.text)
    await _save_finance(message, state)


async def _save_finance(message: Message, state: FSMContext, callback: CallbackQuery = None):
    data = await state.get_data()
    tg_id = callback.from_user.id if callback else message.from_user.id
    await state.clear()
    
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == tg_id))
        user = result.scalar_one_or_none()
        
        record = Finance(
            type=FinanceType(data["fin_type"]),
            amount=data["amount"],
            category=data.get("category"),
            project_id=data.get("project_id"),
            description=data.get("description"),
            created_by=user.id if user else None,
        )
        session.add(record)
        await session.commit()
    
    is_income = data["fin_type"] == FinanceType.INCOME.value
    emoji = "💵" if is_income else "💸"
    label = "Приход" if is_income else "Расход"
    
    text = f"✅ {emoji} {label}: <b>${data['amount']:,.0f}</b>"
    if data.get("category"):
        text += f" ({data['category']})"
    
    target = callback.message if callback else message
    if callback:
        await target.edit_text(text, reply_markup=finance_menu_kb(), parse_mode="HTML")
        await callback.answer()
    else:
        await target.answer(text, reply_markup=finance_menu_kb(), parse_mode="HTML")


# ==================== Monthly Report ====================

@router.callback_query(F.data == "fin:month")
async def fin_month(callback: CallbackQuery):
    today = date.today()
    month_start = today.replace(day=1)
    
    async with async_session() as session:
        # Income by category
        inc_result = await session.execute(
            select(Finance.category, func.sum(Finance.amount))
            .where(and_(
                Finance.type == FinanceType.INCOME,
                Finance.record_date >= month_start
            ))
            .group_by(Finance.category)
            .order_by(func.sum(Finance.amount).desc())
        )
        income_cats = inc_result.all()
        
        # Expense by category
        exp_result = await session.execute(
            select(Finance.category, func.sum(Finance.amount))
            .where(and_(
                Finance.type == FinanceType.EXPENSE,
                Finance.record_date >= month_start
            ))
            .group_by(Finance.category)
            .order_by(func.sum(Finance.amount).desc())
        )
        expense_cats = exp_result.all()
    
    total_income = sum(a for _, a in income_cats)
    total_expense = sum(a for _, a in expense_cats)
    
    lines = [f"📊 <b>Финансы — {today.strftime('%B %Y')}</b>\n"]
    
    lines.append("💵 <b>Приход:</b>")
    if income_cats:
        for cat, amount in income_cats:
            cat_name = cat or "Без категории"
            lines.append(f"  • {cat_name}: ${amount:,.0f}")
        lines.append(f"  <b>Итого: ${total_income:,.0f}</b>")
    else:
        lines.append("  Нет записей")
    
    lines.append("\n💸 <b>Расход:</b>")
    if expense_cats:
        for cat, amount in expense_cats:
            cat_name = cat or "Без категории"
            lines.append(f"  • {cat_name}: ${amount:,.0f}")
        lines.append(f"  <b>Итого: ${total_expense:,.0f}</b>")
    else:
        lines.append("  Нет записей")
    
    lines.append(f"\n═══════════════")
    lines.append(f"💰 Баланс: <b>${total_income - total_expense:,.0f}</b>")
    
    await callback.message.edit_text("\n".join(lines), reply_markup=finance_menu_kb(), parse_mode="HTML")
    await callback.answer()


# ==================== By Project ====================

@router.callback_query(F.data == "fin:by_project")
async def fin_by_project(callback: CallbackQuery):
    today = date.today()
    month_start = today.replace(day=1)
    
    async with async_session() as session:
        result = await session.execute(
            select(
                Project.emoji, Project.name,
                func.sum(func.case(
                    (Finance.type == FinanceType.INCOME, Finance.amount),
                    else_=0
                )).label("income"),
                func.sum(func.case(
                    (Finance.type == FinanceType.EXPENSE, Finance.amount),
                    else_=0
                )).label("expense"),
            )
            .join(Finance, Finance.project_id == Project.id)
            .where(Finance.record_date >= month_start)
            .group_by(Project.id, Project.emoji, Project.name)
            .order_by(func.sum(Finance.amount).desc())
        )
        rows = result.all()
    
    if not rows:
        text = "📊 <b>По проектам</b>\n\nНет данных за этот месяц"
    else:
        lines = [f"📊 <b>По проектам — {today.strftime('%B %Y')}</b>\n"]
        for emoji, name, income, expense in rows:
            inc = income or 0
            exp = expense or 0
            lines.append(f"{emoji} <b>{name}</b>")
            lines.append(f"  💵 +${inc:,.0f}  💸 -${exp:,.0f}  📊 ${inc-exp:,.0f}")
        text = "\n".join(lines)
    
    await callback.message.edit_text(text, reply_markup=finance_menu_kb(), parse_mode="HTML")
    await callback.answer()
