"""
ZBS CRM Bot — Bloggers Handler
Add, list, view bloggers by language (RU/UZ)
"""

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select

from database import async_session, Blogger, User

router = Router()


class AddBlogger(StatesGroup):
    name = State()
    language = State()
    telegram = State()
    instagram = State()
    notes = State()


def bloggers_menu_kb():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🇺🇿 Узбекские", callback_data="blog:list:uz"),
        InlineKeyboardButton(text="🇷🇺 Русские", callback_data="blog:list:ru"),
    )
    builder.row(
        InlineKeyboardButton(text="📋 Все", callback_data="blog:list:all"),
        InlineKeyboardButton(text="➕ Добавить", callback_data="blog:add"),
    )
    builder.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main"))
    return builder.as_markup()


# ==================== Menu ====================

@router.callback_query(F.data == "menu:bloggers")
async def bloggers_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    
    async with async_session() as session:
        uz_count = (await session.execute(select(Blogger).where(Blogger.is_active == True, Blogger.language == "uz"))).scalars()
        ru_count = (await session.execute(select(Blogger).where(Blogger.is_active == True, Blogger.language == "ru"))).scalars()
        uz = len(list(uz_count))
        ru = len(list(ru_count))
    
    text = (
        f"🎬 <b>Блогеры</b>\n\n"
        f"🇺🇿 Узбекские: {uz}\n"
        f"🇷🇺 Русские: {ru}\n"
        f"📊 Всего: {uz + ru}"
    )
    
    await callback.message.edit_text(text, reply_markup=bloggers_menu_kb(), parse_mode="HTML")
    await callback.answer()


# ==================== List ====================

@router.callback_query(F.data.startswith("blog:list:"))
async def bloggers_list(callback: CallbackQuery):
    lang = callback.data.split(":")[2]
    
    async with async_session() as session:
        query = select(Blogger).where(Blogger.is_active == True)
        if lang != "all":
            query = query.where(Blogger.language == lang)
        query = query.order_by(Blogger.language, Blogger.name)
        result = await session.execute(query)
        bloggers = result.scalars().all()
    
    lang_titles = {"uz": "🇺🇿 Узбекские блогеры", "ru": "🇷🇺 Русские блогеры", "all": "📋 Все блогеры"}
    
    if not bloggers:
        text = f"<b>{lang_titles.get(lang, 'Блогеры')}</b>\n\n🤷 Список пуст"
    else:
        lines = [f"<b>{lang_titles.get(lang, 'Блогеры')}</b>\n"]
        current_lang = None
        
        for b in bloggers:
            if lang == "all" and b.language != current_lang:
                current_lang = b.language
                flag = "🇺🇿" if b.language == "uz" else "🇷🇺"
                lines.append(f"\n{flag} <b>{'Узбекские' if b.language == 'uz' else 'Русские'}:</b>")
            
            tg_link = f" <a href='https://t.me/{b.telegram_username}'>@{b.telegram_username}</a>" if b.telegram_username else ""
            ig_link = f" | <a href='{b.instagram_url}'>Instagram</a>" if b.instagram_url else ""
            
            lines.append(f"• <b>{b.name}</b>{tg_link}{ig_link}")
        
        text = "\n".join(lines)
    
    builder = InlineKeyboardBuilder()
    for b in bloggers:
        builder.row(InlineKeyboardButton(text=f"📋 {b.name}", callback_data=f"blog:view:{b.id}"))
    builder.row(
        InlineKeyboardButton(text="➕ Добавить", callback_data="blog:add"),
        InlineKeyboardButton(text="◀️ Назад", callback_data="menu:bloggers"),
    )
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML", disable_web_page_preview=True)
    await callback.answer()


# ==================== View ====================

@router.callback_query(F.data.startswith("blog:view:"))
async def blogger_view(callback: CallbackQuery):
    blogger_id = int(callback.data.split(":")[2])
    
    async with async_session() as session:
        result = await session.execute(select(Blogger).where(Blogger.id == blogger_id))
        b = result.scalar_one_or_none()
    
    if not b:
        await callback.answer()
        return
    
    flag = "🇺🇿" if b.language == "uz" else "🇷🇺"
    lang_name = "Узбекский" if b.language == "uz" else "Русский"
    
    lines = [f"🎬 <b>{b.name}</b> {flag}\n"]
    lines.append(f"🌐 Язык: {lang_name}")
    
    if b.telegram_username:
        lines.append(f"✈️ Telegram: <a href='https://t.me/{b.telegram_username}'>@{b.telegram_username}</a>")
    if b.instagram_url:
        lines.append(f"📸 Instagram: <a href='{b.instagram_url}'>{b.instagram_url}</a>")
    if b.notes:
        lines.append(f"\n📝 {b.notes}")
    
    builder = InlineKeyboardBuilder()
    if b.telegram_username:
        builder.row(InlineKeyboardButton(text=f"✈️ Написать в ТГ", url=f"https://t.me/{b.telegram_username}"))
    if b.instagram_url:
        builder.row(InlineKeyboardButton(text=f"📸 Instagram", url=b.instagram_url))
    builder.row(
        InlineKeyboardButton(text="✏️ Язык", callback_data=f"blog:lang:{b.id}"),
        InlineKeyboardButton(text="🗑 Удалить", callback_data=f"blog:del:{b.id}"),
    )
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="menu:bloggers"))
    
    await callback.message.edit_text("\n".join(lines), reply_markup=builder.as_markup(), parse_mode="HTML", disable_web_page_preview=True)
    await callback.answer()


# ==================== Toggle Language ====================

@router.callback_query(F.data.startswith("blog:lang:"))
async def blogger_toggle_lang(callback: CallbackQuery):
    blogger_id = int(callback.data.split(":")[2])
    
    async with async_session() as session:
        result = await session.execute(select(Blogger).where(Blogger.id == blogger_id))
        b = result.scalar_one_or_none()
        if b:
            b.language = "ru" if b.language == "uz" else "uz"
            new_lang = "🇷🇺 Русский" if b.language == "ru" else "🇺🇿 Узбекский"
            await session.commit()
    
    await callback.answer()
    # Refresh view
    callback.data = f"blog:view:{blogger_id}"
    await blogger_view(callback)


# ==================== Delete ====================

@router.callback_query(F.data.startswith("blog:del:"))
async def blogger_delete(callback: CallbackQuery):
    blogger_id = int(callback.data.split(":")[2])
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Да", callback_data=f"blog:delyes:{blogger_id}"),
        InlineKeyboardButton(text="❌ Нет", callback_data=f"blog:view:{blogger_id}"),
    )
    
    await callback.message.edit_text("🗑 Удалить блогера?", reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("blog:delyes:"))
async def blogger_delete_confirm(callback: CallbackQuery):
    blogger_id = int(callback.data.split(":")[2])
    
    async with async_session() as session:
        result = await session.execute(select(Blogger).where(Blogger.id == blogger_id))
        b = result.scalar_one_or_none()
        if b:
            b.is_active = False
            await session.commit()
    
    await callback.message.edit_text("🗑 Блогер удалён", reply_markup=bloggers_menu_kb())
    await callback.answer()


# ==================== Add ====================

@router.callback_query(F.data == "blog:add")
async def blogger_add_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AddBlogger.name)
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel"))
    
    await callback.message.edit_text("🎬 <b>Новый блогер</b>\n\nИмя:", reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()


@router.message(AddBlogger.name)
async def blogger_add_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(AddBlogger.language)
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🇺🇿 Узбекский", callback_data="blang:uz"),
        InlineKeyboardButton(text="🇷🇺 Русский", callback_data="blang:ru"),
    )
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="cancel"))
    
    await message.answer("Язык:", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("blang:"), AddBlogger.language)
async def blogger_add_lang(callback: CallbackQuery, state: FSMContext):
    lang = callback.data.split(":")[1]
    await state.update_data(language=lang)
    await state.set_state(AddBlogger.telegram)
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⏭ Пропустить", callback_data="btg:skip"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="cancel"),
    )
    
    await callback.message.edit_text("✈️ Telegram username (без @):", reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data == "btg:skip", AddBlogger.telegram)
async def blogger_skip_tg(callback: CallbackQuery, state: FSMContext):
    await state.update_data(telegram=None)
    await state.set_state(AddBlogger.instagram)
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⏭ Пропустить", callback_data="big:skip"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="cancel"),
    )
    
    await callback.message.edit_text("📸 Ссылка на Instagram:", reply_markup=builder.as_markup())
    await callback.answer()


@router.message(AddBlogger.telegram)
async def blogger_add_tg(message: Message, state: FSMContext):
    tg = message.text.replace("@", "").replace("https://t.me/", "").strip()
    await state.update_data(telegram=tg)
    await state.set_state(AddBlogger.instagram)
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⏭ Пропустить", callback_data="big:skip"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="cancel"),
    )
    
    await message.answer("📸 Ссылка на Instagram:", reply_markup=builder.as_markup())


@router.callback_query(F.data == "big:skip", AddBlogger.instagram)
async def blogger_skip_ig(callback: CallbackQuery, state: FSMContext):
    await state.update_data(instagram=None)
    await state.set_state(AddBlogger.notes)
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⏭ Пропустить", callback_data="bnote:skip"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="cancel"),
    )
    
    await callback.message.edit_text("📝 Заметка (или пропусти):", reply_markup=builder.as_markup())
    await callback.answer()


@router.message(AddBlogger.instagram)
async def blogger_add_ig(message: Message, state: FSMContext):
    ig = message.text.strip()
    if not ig.startswith("http"):
        ig = f"https://instagram.com/{ig.replace('@', '')}"
    await state.update_data(instagram=ig)
    await state.set_state(AddBlogger.notes)
    
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⏭ Пропустить", callback_data="bnote:skip"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="cancel"),
    )
    
    await message.answer("📝 Заметка (или пропусти):", reply_markup=builder.as_markup())


@router.callback_query(F.data == "bnote:skip", AddBlogger.notes)
async def blogger_skip_notes(callback: CallbackQuery, state: FSMContext):
    await state.update_data(notes=None)
    await _save_blogger(callback, state)


@router.message(AddBlogger.notes)
async def blogger_add_notes(message: Message, state: FSMContext):
    await state.update_data(notes=message.text)
    await _save_blogger(message, state)


async def _save_blogger(event, state: FSMContext):
    data = await state.get_data()
    tg_id = event.from_user.id
    await state.clear()
    
    async with async_session() as session:
        user_r = await session.execute(select(User.id).where(User.telegram_id == tg_id))
        user_id = user_r.scalar_one_or_none()
        
        blogger = Blogger(
            name=data["name"],
            language=data["language"],
            telegram_username=data.get("telegram"),
            instagram_url=data.get("instagram"),
            notes=data.get("notes"),
            added_by=user_id,
        )
        session.add(blogger)
        await session.commit()
    
    flag = "🇺🇿" if data["language"] == "uz" else "🇷🇺"
    text = f"✅ Блогер <b>{data['name']}</b> {flag} добавлен!"
    
    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, reply_markup=bloggers_menu_kb(), parse_mode="HTML")
        await event.answer()
    else:
        await event.answer(text, reply_markup=bloggers_menu_kb(), parse_mode="HTML")
