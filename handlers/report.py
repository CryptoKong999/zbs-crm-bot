"""
ZBS CRM Bot — Daily Report & Scheduler
Automated reminders and daily digest
"""

import os
import asyncio
from datetime import date, datetime, timedelta, time as dt_time
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from sqlalchemy import select, func, and_, or_
from sqlalchemy.orm import selectinload

from database import (
    async_session, ContentPlan, Task, Deal, Finance, User, Project,
    ContentStatus, TaskStatus, TaskPriority, DealStatus, FinanceType
)
from keyboards import back_to_menu_kb

router = Router()


# ==================== Daily Report ====================

async def generate_daily_report() -> str:
    """Generate daily report text"""
    today = date.today()
    tomorrow = today + timedelta(days=1)
    
    async with async_session() as session:
        # Today's content
        content_result = await session.execute(
            select(ContentPlan)
            .options(selectinload(ContentPlan.assignee), selectinload(ContentPlan.project))
            .where(ContentPlan.scheduled_date == today)
            .order_by(ContentPlan.scheduled_time.asc().nulls_last())
        )
        today_content = content_result.scalars().all()
        
        # Tomorrow's content
        tomorrow_result = await session.execute(
            select(ContentPlan)
            .options(selectinload(ContentPlan.assignee))
            .where(ContentPlan.scheduled_date == tomorrow)
            .order_by(ContentPlan.scheduled_time.asc().nulls_last())
        )
        tomorrow_content = tomorrow_result.scalars().all()
        
        # Overdue tasks
        overdue_result = await session.execute(
            select(Task)
            .options(selectinload(Task.assignee))
            .where(and_(
                Task.status.in_([TaskStatus.TODO, TaskStatus.IN_PROGRESS]),
                Task.deadline < datetime.combine(today, dt_time.min)
            ))
            .order_by(Task.deadline.asc())
        )
        overdue_tasks = overdue_result.scalars().all()
        
        # Today's deadlines
        today_deadline_result = await session.execute(
            select(Task)
            .options(selectinload(Task.assignee))
            .where(and_(
                Task.status.in_([TaskStatus.TODO, TaskStatus.IN_PROGRESS]),
                Task.deadline >= datetime.combine(today, dt_time.min),
                Task.deadline <= datetime.combine(today, dt_time.max)
            ))
        )
        today_tasks = today_deadline_result.scalars().all()
        
        # Urgent tasks
        urgent_result = await session.execute(
            select(Task)
            .options(selectinload(Task.assignee))
            .where(and_(
                Task.status.in_([TaskStatus.TODO, TaskStatus.IN_PROGRESS]),
                Task.priority == TaskPriority.URGENT
            ))
        )
        urgent_tasks = urgent_result.scalars().all()
        
        # Active deals
        deals_result = await session.execute(
            select(Deal)
            .options(selectinload(Deal.client))
            .where(Deal.status.in_([
                DealStatus.LEAD, DealStatus.NEGOTIATION, 
                DealStatus.PROPOSAL, DealStatus.CONTRACT, DealStatus.ACTIVE
            ]))
        )
        active_deals = deals_result.scalars().all()
        
        # Month finances
        month_start = today.replace(day=1)
        inc = await session.execute(
            select(func.coalesce(func.sum(Finance.amount), 0))
            .where(Finance.type == FinanceType.INCOME, Finance.record_date >= month_start)
        )
        exp = await session.execute(
            select(func.coalesce(func.sum(Finance.amount), 0))
            .where(Finance.type == FinanceType.EXPENSE, Finance.record_date >= month_start)
        )
        income = inc.scalar() or 0
        expense = exp.scalar() or 0
    
    # Build report
    weekdays = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    lines = [
        f"📊 <b>ОТЧЁТ ДНЯ — {weekdays[today.weekday()]}, {today.strftime('%d.%m.%Y')}</b>",
        f"{'═' * 30}\n",
    ]
    
    # Overdue
    if overdue_tasks:
        lines.append(f"🚨 <b>ПРОСРОЧЕНО ({len(overdue_tasks)}):</b>")
        for t in overdue_tasks[:5]:
            assignee = f" → {t.assignee.full_name}" if t.assignee else ""
            days = (today - t.deadline.date()).days
            lines.append(f"  ⚠️ {t.title}{assignee} ({days}д назад)")
        lines.append("")
    
    # Today's content
    lines.append(f"📅 <b>КОНТЕНТ СЕГОДНЯ ({len(today_content)}):</b>")
    if today_content:
        published = sum(1 for c in today_content if c.status == ContentStatus.PUBLISHED)
        for c in today_content:
            status = "✅" if c.status == ContentStatus.PUBLISHED else "⬜"
            time_str = c.scheduled_time.strftime("%H:%M") if c.scheduled_time else "—"
            assignee = f" → {c.assignee.full_name}" if c.assignee else ""
            lines.append(f"  {status} {time_str} {c.title}{assignee}")
        lines.append(f"  📊 Готово: {published}/{len(today_content)}")
    else:
        lines.append("  ✨ Ничего не запланировано")
    lines.append("")
    
    # Tomorrow preview
    if tomorrow_content:
        lines.append(f"📆 <b>ЗАВТРА ({len(tomorrow_content)}):</b>")
        for c in tomorrow_content[:5]:
            assignee = f" → {c.assignee.full_name}" if c.assignee else ""
            lines.append(f"  📝 {c.title}{assignee}")
        lines.append("")
    
    # Today's deadlines + urgent
    critical = list(set(today_tasks + urgent_tasks))
    if critical:
        lines.append(f"🔥 <b>ТРЕБУЕТ ВНИМАНИЯ ({len(critical)}):</b>")
        for t in critical:
            emoji = "⏰" if t in today_tasks else "🔴"
            assignee = f" → {t.assignee.full_name}" if t.assignee else ""
            lines.append(f"  {emoji} {t.title}{assignee}")
        lines.append("")
    
    # Deals summary
    if active_deals:
        pipeline_total = sum(d.amount or 0 for d in active_deals)
        lines.append(f"💼 <b>СДЕЛКИ:</b> {len(active_deals)} активных — ${pipeline_total:,.0f}")
        # Show deals requiring attention (proposals/negotiations)
        hot_deals = [d for d in active_deals if d.status in (DealStatus.NEGOTIATION, DealStatus.PROPOSAL)]
        for d in hot_deals[:3]:
            amount = f" ${d.amount:,.0f}" if d.amount else ""
            lines.append(f"  🟡 {d.title} ({d.client.name}){amount}")
        lines.append("")
    
    # Finance
    lines.append(f"💰 <b>ФИНАНСЫ ({today.strftime('%B')}):</b>")
    lines.append(f"  💵 +${income:,.0f}  💸 -${expense:,.0f}  📊 ${income-expense:,.0f}")
    
    return "\n".join(lines)


@router.callback_query(F.data == "menu:report")
@router.message(Command("report"))
async def daily_report(event, state=None):
    report = await generate_daily_report()
    
    if isinstance(event, CallbackQuery):
        await event.message.edit_text(report, reply_markup=back_to_menu_kb(), parse_mode="HTML")
        await event.answer()
    else:
        await event.answer(report, reply_markup=back_to_menu_kb(), parse_mode="HTML")


# ==================== Scheduler Functions ====================

async def send_morning_report(bot: Bot):
    """Send daily report to admins at 9:00 Tashkent"""
    report = await generate_daily_report()
    
    admin_ids_str = os.environ.get("ADMIN_IDS", "")
    admin_ids = [int(x.strip()) for x in admin_ids_str.split(",") if x.strip()]
    
    for admin_id in admin_ids:
        try:
            await bot.send_message(admin_id, report, parse_mode="HTML")
        except Exception as e:
            print(f"Failed to send report to {admin_id}: {e}")


async def send_deadline_reminders(bot: Bot):
    """Send reminders for upcoming deadlines"""
    today = date.today()
    tomorrow = today + timedelta(days=1)
    
    async with async_session() as session:
        # Tasks due today or tomorrow
        result = await session.execute(
            select(Task)
            .options(selectinload(Task.assignee))
            .where(and_(
                Task.status.in_([TaskStatus.TODO, TaskStatus.IN_PROGRESS]),
                Task.deadline >= datetime.combine(today, dt_time.min),
                Task.deadline <= datetime.combine(tomorrow, dt_time.max)
            ))
        )
        tasks = result.scalars().all()
        
        # Content planned for today that's not published
        content_result = await session.execute(
            select(ContentPlan)
            .options(selectinload(ContentPlan.assignee))
            .where(and_(
                ContentPlan.scheduled_date == today,
                ContentPlan.status.in_([ContentStatus.PLANNED, ContentStatus.IN_PROGRESS])
            ))
        )
        content = content_result.scalars().all()
    
    # Send task reminders
    for t in tasks:
        if t.assignee:
            is_today = t.deadline.date() == today
            emoji = "⏰" if is_today else "📅"
            when = "СЕГОДНЯ" if is_today else "ЗАВТРА"
            text = (
                f"{emoji} <b>Напоминание</b>\n\n"
                f"Задача: <b>{t.title}</b>\n"
                f"Дедлайн: <b>{when}</b> ({t.deadline.strftime('%d.%m %H:%M')})"
            )
            try:
                await bot.send_message(t.assignee.telegram_id, text, parse_mode="HTML")
            except Exception as e:
                print(f"Reminder failed for {t.assignee.full_name}: {e}")
    
    # Send content reminders
    for c in content:
        if c.assignee:
            time_str = c.scheduled_time.strftime("%H:%M") if c.scheduled_time else "сегодня"
            text = (
                f"📅 <b>Контент-напоминание</b>\n\n"
                f"<b>{c.title}</b>\n"
                f"Публикация: {time_str}\n"
                f"Статус: {'🔄 В работе' if c.status == ContentStatus.IN_PROGRESS else '📝 Запланировано'}"
            )
            try:
                await bot.send_message(c.assignee.telegram_id, text, parse_mode="HTML")
            except Exception as e:
                print(f"Content reminder failed for {c.assignee.full_name}: {e}")


async def send_overdue_alerts(bot: Bot):
    """Alert admins about overdue tasks"""
    today = date.today()
    
    async with async_session() as session:
        result = await session.execute(
            select(Task)
            .options(selectinload(Task.assignee))
            .where(and_(
                Task.status.in_([TaskStatus.TODO, TaskStatus.IN_PROGRESS]),
                Task.deadline < datetime.combine(today, dt_time.min)
            ))
            .order_by(Task.deadline.asc())
        )
        overdue = result.scalars().all()
    
    if not overdue:
        return
    
    lines = [f"🚨 <b>Просроченные задачи ({len(overdue)}):</b>\n"]
    for t in overdue:
        days = (today - t.deadline.date()).days
        assignee = f" → {t.assignee.full_name}" if t.assignee else " → не назначено"
        lines.append(f"⚠️ {t.title}{assignee} ({days}д)")
    
    text = "\n".join(lines)
    
    admin_ids_str = os.environ.get("ADMIN_IDS", "")
    admin_ids = [int(x.strip()) for x in admin_ids_str.split(",") if x.strip()]
    
    for admin_id in admin_ids:
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML")
        except Exception as e:
            print(f"Overdue alert failed for {admin_id}: {e}")
