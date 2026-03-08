"""
ZBS CRM Bot — Initial Data Seed
Pre-loads team members, projects, clients with real ZBS data
Run once after first deploy: python seed.py
"""

import asyncio
import os
from database import (
    init_db, async_session, engine,
    User, UserRole, Project, Client, Deal, DealStatus
)
from sqlalchemy import select, text


# ==================== TEAM ====================

TEAM = [
    # (telegram_id, username, full_name, role)
    # Admins
    (271065518, "nasyrov_robert", "Роберт", UserRole.ADMIN),
    
    # Priority content team (календарь в первую очередь)
    (None, "madvadps", "Вадим", UserRole.ADMIN),          # Основатель, подкаст, новости
    (None, "yaparalax", "Даня", UserRole.MANAGER),          # Главный монтажёр
    (None, "sarikyusupov", "Сарик", UserRole.MANAGER),      # Монтаж, ZBS Места, ведущий
    (None, "radmiruzb", "Радмир", UserRole.MEMBER),          # Рэп новости, рэп в коммерцию
    
    # Core team
    (None, "vtregubov", "Слава", UserRole.MEMBER),           # Соведущий подкаста, новости спорта
    (None, "m_milewa", "Милена", UserRole.MEMBER),            # Постит новости по каналам
    (None, "arslanito", "Арслан", UserRole.MEMBER),           # Бэкап монтажёр, руководитель продакшна
    (None, "Guaho13", "Стас", UserRole.MEMBER),               # Звукорежиссёр
    (None, "TheDirtyBandz", "Сарик Вайт", UserRole.MEMBER),      # Дизайнер
    
    # Management
    (None, "n_syuzi", "Сусанна", UserRole.ADMIN),                  # Коммерческий директор / финансы
    (None, None, "Лазиза", UserRole.MEMBER),                  # Ассистент / менеджер по продажам
    (None, None, "Нигина", UserRole.MEMBER),                   # Переводчик + SMM
    (None, None, "Самвел", UserRole.MEMBER),                   # Координатор блогеров
    
    # Plan Banan team
    (None, None, "Ирода", UserRole.MEMBER),                    # Анимация Plan Banan
    (None, None, "Мадина", UserRole.MEMBER),                   # Ведущая подкаста
]


# ==================== PROJECTS ====================

PROJECTS = [
    ("ZBS Podcast", "🎙", "Подкасты и интервью. @zbspodcast 83K. Pepsi — 2 подкаста/мес"),
    ("ZBS Newz RU", "📰", "Новости на русском. @zbsnewz 25K"),
    ("ZBS Newz UZ", "🇺🇿", "Новости на узбекском. @zbsnewz.uz 28K"),
    ("ZBS YouTube", "🎬", "YouTube контент + ZBS Места"),
    ("ZBS TikTok", "🎵", "TikTok контент"),
    ("ZBS Telegram", "✈️", "Telegram каналы: @zbsnewz 25K, кружки, новости"),
    ("Plan Banan", "🍌", "Детская анимация @planbananuz 6.7K"),
    ("#SaveCharvak", "🏔", "Экологический проект. 14 зон, март-сентябрь 2026"),
    ("Коммерция", "💼", "Коммерческие проекты и интеграции"),
]


# ==================== CLIENTS ====================

CLIENTS = [
    # (name, contact_person, contact_telegram, notes)
    ("Pepsi", None, None, "Годовой контракт: 2 подкаста/месяц"),
    ("ЖК Башкент", None, None, "Годовой контракт: 1 видео/месяц"),
    ("UzAuto Motors", None, None, "Instagram Reels с блогером @juhaina_n, Onix"),
    ("HONOR", None, None, "Кампания рекламных материалов"),
    ("Musaffo", None, None, "Потенциальный спонсор Plan Banan"),
    ("Octobank", None, None, "Потенциальный спонсор #SaveCharvak"),
    ("Paynet", None, None, "Потенциальный спонсор #SaveCharvak"),
]


# ==================== DEALS ====================

DEALS = [
    # (title, client_name, project_name, status, amount, description)
    ("Pepsi — подкасты 2026", "Pepsi", "ZBS Podcast", DealStatus.ACTIVE, 0, "Годовой контракт: 2 подкаста/месяц"),
    ("ЖК Башкент — видео 2026", "ЖК Башкент", "ZBS YouTube", DealStatus.ACTIVE, 0, "Годовой контракт: 1 видео/месяц"),
    ("UzAuto Onix — Reels", "UzAuto Motors", "Коммерция", DealStatus.ACTIVE, 0, "Instagram Reels кампания"),
    ("HONOR — материалы", "HONOR", "Коммерция", DealStatus.ACTIVE, 0, "Рекламные материалы"),
    ("Musaffo → Plan Banan", "Musaffo", "Plan Banan", DealStatus.NEGOTIATION, 0, "Спонсорство анимации"),
    ("#SaveCharvak — Octobank", "Octobank", "#SaveCharvak", DealStatus.LEAD, 0, "Спонсорство cleanup"),
    ("#SaveCharvak — Paynet", "Paynet", "#SaveCharvak", DealStatus.LEAD, 0, "Спонсорство cleanup"),
]


async def seed():
    await init_db()
    
    async with async_session() as session:
        # Check if already seeded
        result = await session.execute(select(User).limit(1))
        if result.scalar_one_or_none():
            print("⚠️ Database already has data. Skipping seed.")
            print("   To re-seed, drop tables first: DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
            return
        
        # === USERS ===
        print("👥 Seeding team...")
        user_map = {}
        for tg_id, username, name, role in TEAM:
            user = User(
                telegram_id=tg_id or 0,  # 0 = will update on first /start
                username=username,
                full_name=name,
                role=role,
            )
            session.add(user)
            await session.flush()
            user_map[name] = user.id
            print(f"   ✅ {name} ({role.value})" + (f" @{username}" if username else ""))
        
        # === PROJECTS ===
        print("\n📁 Seeding projects...")
        project_map = {}
        for name, emoji, desc in PROJECTS:
            project = Project(name=name, emoji=emoji, description=desc)
            session.add(project)
            await session.flush()
            project_map[name] = project.id
            print(f"   {emoji} {name}")
        
        # === CLIENTS ===
        print("\n👥 Seeding clients...")
        client_map = {}
        for name, contact, tg, notes in CLIENTS:
            client = Client(
                name=name,
                contact_person=contact,
                contact_telegram=tg,
                notes=notes,
            )
            session.add(client)
            await session.flush()
            client_map[name] = client.id
            print(f"   🏢 {name}")
        
        # === DEALS ===
        print("\n💼 Seeding deals...")
        for title, client_name, project_name, status, amount, desc in DEALS:
            deal = Deal(
                title=title,
                client_id=client_map[client_name],
                project_id=project_map.get(project_name),
                status=status,
                amount=amount,
                description=desc,
            )
            session.add(deal)
            print(f"   {'🟢' if status == DealStatus.ACTIVE else '🟡' if status == DealStatus.NEGOTIATION else '🔵'} {title}")
        
        await session.commit()
    
    print(f"\n{'═' * 40}")
    print(f"✅ SEED COMPLETE!")
    print(f"   👥 {len(TEAM)} team members")
    print(f"   📁 {len(PROJECTS)} projects")
    print(f"   🏢 {len(CLIENTS)} clients")
    print(f"   💼 {len(DEALS)} deals")
    print(f"{'═' * 40}")
    print(f"\n💡 Team members without telegram_id will be")
    print(f"   auto-linked when they write /start to the bot.")
    print(f"\n📱 Share this link with the team:")
    print(f"   https://t.me/YOUR_BOT_USERNAME")


if __name__ == "__main__":
    asyncio.run(seed())
