"""
ZBS CRM Bot — Daily Report & Reminders
Schedule: 09:00 report, 10:00 morning remind, hourly 1hr-before, 20:00 day-before, 11:00 overdue
"""

import os
from datetime import date, datetime, timedelta, time as dt_time
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from sqlalchemy import select, func, and_
from sqlalchemy.orm import selectinload
import pytz

from database import (
    async_session, ContentPlan, Deal, Finance,
    ContentStatus, DealStatus, FinanceType
)
from keyboards import back_to_menu_kb

router = Router()
TZ = pytz.timezone(os.environ.get("TZ", "Asia/Tashkent"))


async def generate_daily_report() -> str:
    today = date.today()
    tomorrow = today + timedelta(days=1)
    
    async with async_session() as session:
        today_r = await session.execute(
            select(ContentPlan).options(selectinload(ContentPlan.assignee), selectinload(ContentPlan.project))
            .where(ContentPlan.scheduled_date == today)
            .order_by(ContentPlan.scheduled_time.asc().nulls_last())
        )
        today_items = today_r.scalars().all()
        
        tomorrow_r = await session.execute(
            select(ContentPlan).options(selectinload(ContentPlan.assignee))
            .where(ContentPlan.scheduled_date == tomorrow)
            .order_by(ContentPlan.scheduled_time.asc().nulls_last())
        )
        tomorrow_items = tomorrow_r.scalars().all()
        
        overdue_r = await session.execute(
            select(ContentPlan).options(selectinload(ContentPlan.assignee))
            .where(and_(ContentPlan.scheduled_date < today, ContentPlan.status.in_([ContentStatus.PLANNED, ContentStatus.IN_PROGRESS])))
            .order_by(ContentPlan.scheduled_date.asc()).limit(10)
        )
        overdue = overdue_r.scalars().all()
        
        deals_r = await session.execute(
            select(Deal).options(selectinload(Deal.client))
            .where(Deal.status.in_([DealStatus.LEAD, DealStatus.NEGOTIATION, DealStatus.PROPOSAL, DealStatus.CONTRACT, DealStatus.ACTIVE]))
        )
        active_deals = deals_r.scalars().all()
        
        month_start = today.replace(day=1)
        inc = (await session.execute(select(func.coalesce(func.sum(Finance.amount), 0)).where(Finance.type == FinanceType.INCOME, Finance.record_date >= month_start))).scalar() or 0
        exp = (await session.execute(select(func.coalesce(func.sum(Finance.amount), 0)).where(Finance.type == FinanceType.EXPENSE, Finance.record_date >= month_start))).scalar() or 0
    
    wd = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    lines = [f"📊 <b>ОТЧЁТ — {wd[today.weekday()]}, {today.strftime('%d.%m.%Y')}</b>\n"]
    
    if overdue:
        lines.append(f"🚨 <b>ПРОСРОЧЕНО ({len(overdue)}):</b>")
        for c in overdue:
            a = f" → {c.assignee.full_name}" if c.assignee else ""
            lines.append(f"  ⚠️ {c.title}{a} ({(today - c.scheduled_date).days}д)")
        lines.append("")
    
    lines.append(f"📅 <b>СЕГОДНЯ ({len(today_items)}):</b>")
    if today_items:
        done = sum(1 for c in today_items if c.status == ContentStatus.PUBLISHED)
        for c in today_items:
            s = "✅" if c.status == ContentStatus.PUBLISHED else "⬜"
            t = c.scheduled_time.strftime("%H:%M") if c.scheduled_time else "—"
            a = f" → {c.assignee.full_name}" if c.assignee else ""
            lines.append(f"  {s} {t} {c.title}{a}")
        lines.append(f"  Готово: {done}/{len(today_items)}")
    else:
        lines.append("  ✨ Пусто")
    lines.append("")
    
    if tomorrow_items:
        lines.append(f"📆 <b>ЗАВТРА ({len(tomorrow_items)}):</b>")
        for c in tomorrow_items:
            a = f" → {c.assignee.full_name}" if c.assignee else ""
            t = c.scheduled_time.strftime("%H:%M") if c.scheduled_time else ""
            lines.append(f"  📝 {t} {c.title}{a}")
        lines.append("")
    
    if active_deals:
        total = sum(d.amount or 0 for d in active_deals)
        lines.append(f"💼 <b>СДЕЛКИ:</b> {len(active_deals)} — ${total:,.0f}")
    
    lines.append(f"💰 <b>{today.strftime('%B')}:</b> +${inc:,.0f} -${exp:,.0f} = ${inc - exp:,.0f}")
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


# ==================== REMINDERS ====================

async def _get_items_for_date(target_date):
    async with async_session() as session:
        result = await session.execute(
            select(ContentPlan).options(selectinload(ContentPlan.assignee))
            .where(and_(
                ContentPlan.scheduled_date == target_date,
                ContentPlan.status.in_([ContentStatus.PLANNED, ContentStatus.IN_PROGRESS]),
                ContentPlan.assignee_id.isnot(None)
            ))
        )
        return result.scalars().all()


def _group_by_user(items):
    by_user = {}
    for c in items:
        if c.assignee and c.assignee.telegram_id and c.assignee.telegram_id != 0:
            by_user.setdefault(c.assignee.telegram_id, []).append(c)
    return by_user


async def send_morning_report(bot: Bot):
    """09:00 — Daily report to admins"""
    report = await generate_daily_report()
    for aid in [int(x.strip()) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()]:
        try:
            await bot.send_message(aid, report, parse_mode="HTML")
        except Exception as e:
            print(f"Report failed {aid}: {e}")


async def send_morning_reminders(bot: Bot):
    """10:00 — Remind assignees about today's tasks"""
    items = await _get_items_for_date(date.today())
    for tg_id, tasks in _group_by_user(items).items():
        lines = ["⏰ <b>Сегодня у тебя:</b>\n"]
        for c in tasks:
            t = c.scheduled_time.strftime("%H:%M") if c.scheduled_time else ""
            lines.append(f"  📝 {t} {c.title}")
        try:
            await bot.send_message(tg_id, "\n".join(lines), parse_mode="HTML")
        except Exception as e:
            print(f"Morning remind failed {tg_id}: {e}")


async def send_day_before_reminders(bot: Bot):
    """20:00 — Remind assignees about tomorrow's tasks"""
    tomorrow = date.today() + timedelta(days=1)
    wd = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    items = await _get_items_for_date(tomorrow)
    for tg_id, tasks in _group_by_user(items).items():
        lines = [f"📅 <b>Завтра ({wd[tomorrow.weekday()]} {tomorrow.strftime('%d.%m')}):</b>\n"]
        for c in tasks:
            t = c.scheduled_time.strftime("%H:%M") if c.scheduled_time else ""
            lines.append(f"  📝 {t} {c.title}")
        try:
            await bot.send_message(tg_id, "\n".join(lines), parse_mode="HTML")
        except Exception as e:
            print(f"Day-before remind failed {tg_id}: {e}")


async def send_hourly_reminders(bot: Bot):
    """Every hour — notify if task starts in next hour"""
    now = datetime.now(TZ)
    today = now.date()
    current_h = now.hour
    next_h = current_h + 1
    
    if next_h > 23:
        return
    
    async with async_session() as session:
        result = await session.execute(
            select(ContentPlan).options(selectinload(ContentPlan.assignee))
            .where(and_(
                ContentPlan.scheduled_date == today,
                ContentPlan.scheduled_time.isnot(None),
                ContentPlan.status.in_([ContentStatus.PLANNED, ContentStatus.IN_PROGRESS]),
                ContentPlan.assignee_id.isnot(None)
            ))
        )
        items = result.scalars().all()
    
    for c in items:
        if c.scheduled_time and c.scheduled_time.hour == next_h:
            if c.assignee and c.assignee.telegram_id and c.assignee.telegram_id != 0:
                text = f"🔔 <b>Через час ({c.scheduled_time.strftime('%H:%M')}):</b>\n\n{c.title}"
                try:
                    await bot.send_message(c.assignee.telegram_id, text, parse_mode="HTML")
                except Exception as e:
                    print(f"Hourly remind failed: {e}")


async def send_overdue_alerts(bot: Bot):
    """11:00 — Alert admins about overdue"""
    today = date.today()
    async with async_session() as session:
        result = await session.execute(
            select(ContentPlan).options(selectinload(ContentPlan.assignee))
            .where(and_(ContentPlan.scheduled_date < today, ContentPlan.status.in_([ContentStatus.PLANNED, ContentStatus.IN_PROGRESS])))
            .order_by(ContentPlan.scheduled_date.asc())
        )
        overdue = result.scalars().all()
    
    if not overdue:
        return
    
    lines = [f"🚨 <b>Просрочено ({len(overdue)}):</b>\n"]
    for c in overdue:
        a = f" → {c.assignee.full_name}" if c.assignee else ""
        lines.append(f"⚠️ {c.title}{a} ({(today - c.scheduled_date).days}д)")
    
    text = "\n".join(lines)
    for aid in [int(x.strip()) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()]:
        try:
            await bot.send_message(aid, text, parse_mode="HTML")
        except Exception as e:
            print(f"Overdue alert failed: {e}")
