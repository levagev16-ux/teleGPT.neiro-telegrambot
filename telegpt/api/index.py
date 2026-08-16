import os
import json
import re
import requests
from http.server import BaseHTTPRequestHandler
from groq import Groq
from upstash_redis import Redis

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

UPSTASH_URL = os.environ.get("KV_REST_API_URL")
UPSTASH_TOKEN = os.environ.get("KV_REST_API_TOKEN")

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
groq = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

db = Redis(url=UPSTASH_URL, token=UPSTASH_TOKEN) if UPSTASH_URL and UPSTASH_TOKEN else None

BOT_USERNAME = None
try:
    bot_info = requests.get(f"{TELEGRAM_API}/getMe", timeout=10).json()
    if bot_info.get("ok"):
        BOT_USERNAME = bot_info["result"]["username"].lower()
except Exception:
    BOT_USERNAME = "neirogpt234_bot"


# ---- TELEGRAM API & TEXT HELPERS ----

def escape_markdown(text):
    if not text:
        return ""
    for char in ['_', '*', '`', '[']:
        text = str(text).replace(char, f"\\{char}")
    return text


def clean_command(text):
    if not text:
        return ""
    text = text.strip()
    if text.startswith("/"):
        parts = text.split(maxsplit=1)
        cmd = parts[0].split("@")[0].lower()
        rest = " " + parts[1] if len(parts) > 1 else ""
        return cmd + rest
    return text


def telegram_request(method, payload):
    try:
        res = requests.post(f"{TELEGRAM_API}/{method}", json=payload, timeout=30)
        return res.json()
    except Exception as e:
        print(f"TELEGRAM API ERROR ({method}):", repr(e))
        return None


def telegram_send(chat_id, text, reply_to=None, reply_markup=None):
    data = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_to:
        data["reply_to_message_id"] = reply_to
    if reply_markup:
        data["reply_markup"] = reply_markup
    return telegram_request("sendMessage", data)


def telegram_edit_message(chat_id, message_id, text, reply_markup=None):
    data = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    if reply_markup:
        data["reply_markup"] = reply_markup
    return telegram_request("editMessageText", data)


def telegram_answer_callback(callback_query_id, text=""):
    telegram_request("answerCallbackQuery", {"callback_query_id": callback_query_id, "text": text})


def get_telegram_file_url(file_id):
    res = telegram_request("getFile", {"file_id": file_id})
    if res and res.get("ok"):
        file_path = res["result"]["file_path"]
        return f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
    return None


# ---- GROQ MODELS FETCHING & CATEGORIZATION ----

def fetch_all_groq_models():
    try:
        if not groq:
            raise Exception("Groq API client не инициализирован.")
        models_data = groq.models.list()
        return [m.id for m in models_data.data]
    except Exception as e:
        print(f"Ошибка получения моделей: {e}")
        return [
            "llama-3.3-70b-versatile", "llama-3.1-8b-instant",
            "openai/gpt-oss-120b", "openai/gpt-oss-20b",
            "whisper-large-v3-turbo", "whisper-large-v3",
            "openai/gpt-oss-safeguard-20b"
        ]


def get_categorized_models():
    all_models = fetch_all_groq_models()

    text_models = [m for m in all_models if not any(x in m for x in ["whisper", "prompt-guard", "safeguard", "orpheus"])]
    voice_models = [m for m in all_models if "whisper" in m]
    mod_models = [m for m in all_models if any(x in m for x in ["safeguard", "prompt-guard"])]

    if not text_models:
        text_models = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]
    if not voice_models:
        voice_models = ["whisper-large-v3-turbo", "whisper-large-v3"]
    if not mod_models:
        mod_models = ["openai/gpt-oss-safeguard-20b"]

    return text_models, voice_models, mod_models


# ---- DATABASE SETTINGS & CHAT MANAGEMENT ----

def decode_val(val):
    if val is None:
        return ""
    if isinstance(val, bytes):
        return val.decode('utf-8')
    return str(val)


def get_user_setting(user_id, key, default="auto"):
    if not db:
        return default
    try:
        val = db.get(f"user:{user_id}:{key}")
        if not val:
            return default
        return decode_val(val)
    except Exception as e:
        print(f"DB Error (get_user_setting): {e}")
        return default


def set_user_setting(user_id, key, value):
    if db:
        try:
            db.set(f"user:{user_id}:{key}", value)
        except Exception as e:
            print(f"DB Error (set_user_setting): {e}")


def get_user_active_chat(user_id):
    if not db:
        return "Новый чат 1"
    try:
        active = db.get(f"user:{user_id}:active_chat")
        if not active:
            active = "Новый чат 1"
            db.set(f"user:{user_id}:active_chat", active)
            db.sadd(f"user:{user_id}:chats_list", active)
        return decode_val(active)
    except Exception as e:
        print(f"DB Error (get_user_active_chat): {e}")
        return "Новый чат 1"


def get_user_chats_list(user_id):
    if not db:
        return ["Новый чат 1"]
    try:
        raw_chats = db.smembers(f"user:{user_id}:chats_list")
        if not raw_chats:
            db.sadd(f"user:{user_id}:chats_list", "Новый чат 1")
            return ["Новый чат 1"]
        chats = [decode_val(c) for c in raw_chats]
        chats.sort()
        return chats
    except Exception as e:
        print(f"DB Error (get_user_chats_list): {e}")
        return ["Новый чат 1"]


def get_chat_history(user_id, chat_name):
    if not db:
        return []
    try:
        history = db.get(f"user:{user_id}:chat:{chat_name}")
        if not history:
            return []
        history_str = decode_val(history)
        return json.loads(history_str)
    except Exception as e:
        print(f"DB Error (get_chat_history): {e}")
        return []


def save_chat_history(user_id, chat_name, history):
    if db:
        try:
            db.set(f"user:{user_id}:chat:{chat_name}", json.dumps(history[-10:]))
        except Exception as e:
            print(f"DB Error (save_chat_history): {e}")


def rename_user_chat(user_id, old_name, new_name):
    if not db or not old_name or not new_name:
        return False
    try:
        history = get_chat_history(user_id, old_name)
        db.delete(f"user:{user_id}:chat:{old_name}")
        db.srem(f"user:{user_id}:chats_list", old_name)

        db.set(f"user:{user_id}:chat:{new_name}", json.dumps(history))
        db.sadd(f"user:{user_id}:chats_list", new_name)

        active = get_user_active_chat(user_id)
        if active == old_name:
            db.set(f"user:{user_id}:active_chat", new_name)
        return True
    except Exception as e:
        print(f"DB Error (rename_user_chat): {e}")
        return False


def purge_chat_data(user_id, chat_name):
    if not db:
        return
    try:
        db.delete(f"user:{user_id}:chat:{chat_name}")
        db.srem(f"user:{user_id}:chats_list", chat_name)

        active = get_user_active_chat(user_id)
        if active == chat_name:
            remaining = get_user_chats_list(user_id)
            new_active = remaining[0] if remaining else "Новый чат 1"
            db.set(f"user:{user_id}:active_chat", new_active)
            db.sadd(f"user:{user_id}:chats_list", new_active)
    except Exception as e:
        print(f"DB Error (purge_chat_data): {e}")


def cleanup_orphan_chats(user_id):
    if not db:
        return 0

    deleted_count = 0
    try:
        valid_chats = set(get_user_chats_list(user_id))
        keys = db.keys(f"user:{user_id}:chat:*")
        if not keys:
            return 0

        for key in keys:
            key_str = decode_val(key)
            chat_name = key_str.replace(f"user:{user_id}:chat:", "")
            if chat_name not in valid_chats:
                db.delete(key_str)
                deleted_count += 1
    except Exception as e:
        print(f"Ошибка при очистке ключей: {e}")

    return deleted_count


# ---- KEYBOARD BUILDERS WITH PAGINATION ----

ITEMS_PER_PAGE = 5

def build_chats_menu_keyboard(user_id, page=1):
    active = get_user_active_chat(user_id)
    all_chats = get_user_chats_list(user_id)

    total_chats = len(all_chats)
    total_pages = max(1, (total_chats + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    current_page_chats = all_chats[start_idx:end_idx]

    buttons = []
    
    # Список чатов
    for c in current_page_chats:
        prefix = "👉 " if c == active else "💬 "
        clean_c = c[:20]
        buttons.append([{"text": f"{prefix}{clean_c}", "callback_data": f"sw_ch_{clean_c}_{page}"}])

    # Навигация пагинации
    nav_row = []
    if page > 1:
        nav_row.append({"text": "⬅️ Назад", "callback_data": f"chats_p_{page - 1}"})
    nav_row.append({"text": f"📄 {page}/{total_pages}", "callback_data": "noop"})
    if page < total_pages:
        nav_row.append({"text": "Вперёд ➡️", "callback_data": f"chats_p_{page + 1}"})
    buttons.append(nav_row)

    # Функциональные кнопки
    buttons.append([{"text": "➕ Новый чат", "callback_data": "action_new_chat"}])
    buttons.append([
        {"text": "📜 История", "callback_data": "action_view_history"},
        {"text": "🗑 Удалить текущий", "callback_data": f"confirm_del_{active[:20]}"}
    ])
    buttons.append([{"text": "🧹 Очистить старые чаты", "callback_data": "action_clean_orphans"}])
    buttons.append([{"text": "❌ Закрыть", "callback_data": "close_menu"}])

    return {"inline_keyboard": buttons}


def build_delete_confirm_keyboard(chat_name):
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Да, удалить", "callback_data": f"do_del_{chat_name[:20]}"},
                {"text": "❌ Отмена", "callback_data": "chats_p_1"}
            ]
        ]
    }


def build_main_settings_keyboard(user_id):
    text_m = get_user_setting(user_id, "model_text", "auto")
    voice_m = get_user_setting(user_id, "model_voice", "auto")
    mod_m = get_user_setting(user_id, "model_mod", "auto")

    keyboard = {
        "inline_keyboard": [
            [{"text": f"📝 Текстовые: [{text_m}]", "callback_data": "cat_text"}],
            [{"text": f"🎙 Голосовые: [{voice_m}]", "callback_data": "cat_voice"}],
            [{"text": f"🛡 Модерация: [{mod_m}]", "callback_data": "cat_mod"}],
            [{"text": "⚡ Установить AUTO для всего", "callback_data": "set_all_auto"}],
            [{"text": "❌ Закрыть", "callback_data": "close_menu"}]
        ]
    }
    return keyboard


def build_category_keyboard(user_id, category_type):
    text_models, voice_models, mod_models = get_categorized_models()

    if category_type == "text":
        models = text_models
        current = get_user_setting(user_id, "model_text", "auto")
        prefix = "set_txt_"
    elif category_type == "voice":
        models = voice_models
        current = get_user_setting(user_id, "model_voice", "auto")
        prefix = "set_voc_"
    else:
        models = mod_models
        current = get_user_setting(user_id, "model_mod", "auto")
        prefix = "set_mod_"

    buttons = []
    auto_mark = "✅ " if current == "auto" else ""
    buttons.append([{"text": f"{auto_mark}⚡ AUTO (Автовыбор)", "callback_data": f"{prefix}auto"}])

    for m in models:
        mark = "✅ " if current == m else ""
        buttons.append([{"text": f"{mark}{m}", "callback_data": f"{prefix}{m}"}])

    buttons.append([{"text": "⬅️ Назад в меню", "callback_data": "main_menu"}])
    return {"inline_keyboard": buttons}


# ---- AI LOGIC & SYSTEM PROMPTS ----

def generate_chat_title_ai(first_message):
    try:
        if not groq:
            return None
        prompt = (
            f"Придумай очень короткое название (2-4 слова) на русском языке для диалога, который начинается с этого сообщения: "
            f"\"{first_message}\". Ответь ТОЛЬКО названием, без кавычек и лишних слов."
        )
        res = groq.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            max_completion_tokens=20
        )
        title = res.choices[0].message.content.strip().replace('"', '').replace("'", "")
        return title[:25] if title else None
    except Exception as e:
        print(f"Ошибка генерации имени чата: {e}")
        return None


def get_system_prompt_for_model(model_name):
    m_lower = model_name.lower()

    if "gemma" in m_lower:
        name, creator = "Gemma", "Google"
    elif "llama" in m_lower:
        name, creator = "Llama", "Meta"
    elif "qwen" in m_lower:
        name, creator = "Qwen", "Alibaba"
    elif "gpt" in m_lower:
        name, creator = "GPT", "OpenAI"
    elif "mixtral" in m_lower or "mistral" in m_lower:
        name, creator = "Mistral", "Mistral AI"
    else:
        name, creator = model_name, "Groq"

    return (
        f"Ты — полезный ассистент {name}, работающий через Groq API ({creator}). "
        f"Отвечай пользователю прямо, грамотно и точно по сути его вопроса."
    )


def transcribe_voice(user_id, file_id):
    file_url = get_telegram_file_url(file_id)
    if not file_url:
        raise Exception("Не удалось скачать голосовое сообщение из Telegram.")

    res = requests.get(file_url, timeout=30)
    if res.status_code != 200:
        raise Exception(f"Ошибка загрузки аудиофайла: {res.status_code}")

    audio_bytes = res.content
    selected_model = get_user_setting(user_id, "model_voice", "auto")

    _, voice_models, _ = get_categorized_models()
    models_to_try = [selected_model] if selected_model != "auto" else voice_models

    last_err = None
    for m in models_to_try:
        try:
            transcription = groq.audio.transcriptions.create(
                file=("voice.ogg", audio_bytes),
                model=m,
                response_format="json"
            )
            text_result = transcription.text.strip() if hasattr(transcription, "text") else str(transcription)
            if text_result:
                return text_result, m
        except Exception as e:
            last_err = e
            continue

    raise Exception(f"Ошибка распознавания голоса: {last_err}")


def check_moderation(user_id, text_to_check):
    selected_model = get_user_setting(user_id, "model_mod", "auto")
    _, _, mod_models = get_categorized_models()

    models_to_try = [selected_model] if selected_model != "auto" else mod_models

    last_err = None
    for m in models_to_try:
        try:
            response = groq.chat.completions.create(
                model=m,
                messages=[{"role": "user", "content": text_to_check}]
            )
            return response.choices[0].message.content, m
        except Exception as e:
            last_err = e
            continue

    return f"Ошибка модерации: {last_err}", None


def ask_groq_with_fallback(user_id, history, prompt):
    selected_model = get_user_setting(user_id, "model_text", "auto")
    text_models, _, _ = get_categorized_models()

    models_to_try = [selected_model] if selected_model != "auto" else text_models

    last_error = None
    for model_name in models_to_try:
        try:
            system_instruction = get_system_prompt_for_model(model_name)
            messages = [{"role": "system", "content": system_instruction}]

            for msg in history:
                messages.append({"role": msg["role"], "content": msg["content"]})

            messages.append({"role": "user", "content": prompt})

            response = groq.chat.completions.create(
                model=model_name,
                messages=messages,
                max_completion_tokens=2048
            )

            answer = response.choices[0].message.content
            if answer:
                is_fallback = (selected_model == "auto" and model_name != text_models[0])
                return answer, model_name, is_fallback
        except Exception as e:
            last_error = e
            continue

    raise Exception(f"Все модели недоступны. Ошибка: {last_error}")


# ---- MAIN HANDLER ----

class handler(BaseHTTPRequestHandler):

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)

        try:
            update = json.loads(post_data.decode('utf-8'))
        except Exception:
            self._send_ok()
            return

        # 1. ОБРАБОТКА ИНТЕРАКТИВНЫХ КНОПОК
        callback_query = update.get("callback_query")
        if callback_query:
            try:
                self._handle_callback(callback_query)
            except Exception as e:
                print(f"Callback error: {e}")
            self._send_ok()
            return

        # 2. ОБРАБОТКА СООБЩЕНИЙ
        message = update.get("message")
        if not message:
            self._send_ok()
            return

        chat = message.get("chat", {})
        chat_id = chat.get("id")
        user_id = message.get("from", {}).get("id", chat_id)
        chat_type = chat.get("type")
        message_id = message.get("message_id")

        raw_text = message.get("text", "").strip()
        text = clean_command(raw_text)
        voice = message.get("voice")

        # ОСНОВНЫЕ И ДОПОЛНИТЕЛЬНЫЕ КОМАНДЫ БОТА
        if text.startswith("/start") or text.startswith("/help"):
            help_msg = (
                "👋 *Привет! Я мультимодальный AI-помощник.*\n\n"
                "📌 *Основные команды:*\n"
                "• `/chats` — Управление диалогами (создание, переключение, удаление)\n"
                "• `/newchat <имя>` — Создать новый чат со своим именем\n"
                "• `/rename <новое_имя>` — Переименовать текущий чат\n"
                "• `/setmodel` или `/models` — Настройки моделей AI\n"
                "• `/clear` — Очистить историю текущего чата\n"
                "• `/info` или `/status` — Информация о боте и активной модели\n"
                "• `/moderation <текст>` — Проверить текст моделью модерации\n\n"
                "💬 Отправьте текст или голосовое сообщение, чтобы начать!"
            )
            telegram_send(chat_id, help_msg, message_id)
            self._send_ok()
            return

        if text.startswith("/setmodel") or text.startswith("/models"):
            kb = build_main_settings_keyboard(user_id)
            telegram_send(chat_id, "⚙️ *Настройки моделей AI*\n\nВыберите категорию:", reply_markup=kb)
            self._send_ok()
            return

        if text.startswith("/chats"):
            kb = build_chats_menu_keyboard(user_id, page=1)
            active = escape_markdown(get_user_active_chat(user_id))
            telegram_send(chat_id, f"📋 *Управление диалогами*\n\nТекущий активный чат: *{active}*", reply_markup=kb)
            self._send_ok()
            return

        if text.startswith("/rename"):
            parts = raw_text.split(maxsplit=1)
            if len(parts) < 2 or not parts[1].strip():
                telegram_send(chat_id, "⚠️ Укажите новое имя чата:\n`/rename Мой новый чат`", message_id)
                self._send_ok()
                return
            new_title = parts[1].strip()[:30]
            current_active = get_user_active_chat(user_id)
            if rename_user_chat(user_id, current_active, new_title):
                telegram_send(chat_id, f"✏️ Чат переименован в: *{escape_markdown(new_title)}*", message_id)
            else:
                telegram_send(chat_id, "❌ Не удалось переименовать чат.", message_id)
            self._send_ok()
            return

        if text.startswith("/clear"):
            active = get_user_active_chat(user_id)
            if db:
                db.delete(f"user:{user_id}:chat:{active}")
            telegram_send(chat_id, f"🧹 История чата *{escape_markdown(active)}* очищена!", message_id)
            self._send_ok()
            return

        if text.startswith("/info") or text.startswith("/status"):
            active = get_user_active_chat(user_id)
            txt_m = get_user_setting(user_id, "model_text", "auto")
            voc_m = get_user_setting(user_id, "model_voice", "auto")
            mod_m = get_user_setting(user_id, "model_mod", "auto")
            chats_cnt = len(get_user_chats_list(user_id))

            info_text = (
                f"📊 *Статус и информация:*\n\n"
                f"• *Активный чат:* `{escape_markdown(active)}`\n"
                f"• *Всего чатов:* `{chats_cnt}`\n"
                f"• *Модель текста:* `{txt_m}`\n"
                f"• *Модель голоса:* `{voc_m}`\n"
                f"• *Модель модерации:* `{mod_m}`"
            )
            telegram_send(chat_id, info_text, message_id)
            self._send_ok()
            return

        # РАСПОЗНАВАНИЕ И ОБРАБОТКА ГОЛОСА
        if voice:
            try:
                telegram_send(chat_id, "🎙 *Распознаю голос...*", message_id)
                transcribed_text, used_voice_model = transcribe_voice(user_id, voice.get("file_id"))
                safe_trans = escape_markdown(transcribed_text)
                telegram_send(chat_id, f"🗣 *Расшифровка (`{used_voice_model}`):*\n_{safe_trans}_", message_id)
                prompt = transcribed_text
            except Exception as e:
                telegram_send(chat_id, f"❌ Ошибка распознавания голоса: {e}", message_id)
                self._send_ok()
                return
        else:
            prompt = None

        # МОДЕРАЦИЯ
        if text.startswith("/moderation"):
            check_text = raw_text[11:].strip()
            if not check_text:
                telegram_send(chat_id, "Использование: `/moderation <текст>`", message_id)
                self._send_ok()
                return
            result, mod_m = check_moderation(user_id, check_text)
            telegram_send(chat_id, f"🛡 *Модерация (`{mod_m}`):*\n\n{result}", message_id)
            self._send_ok()
            return

        # ИЗВЛЕЧЕНИЕ ТЕКСТА ЗАПРОСА (ЕСЛИ НЕ ГОЛОС)
        if not prompt:
            if chat_type == "private":
                if text.startswith("/newchat"):
                    parts = raw_text.split(maxsplit=1)
                    if len(parts) > 1 and parts[1].strip():
                        new_chat_name = parts[1].strip()[:30]
                    else:
                        new_chat_name = f"Новый чат {len(get_user_chats_list(user_id)) + 1}"

                    if db:
                        try:
                            db.set(f"user:{user_id}:active_chat", new_chat_name)
                            db.sadd(f"user:{user_id}:chats_list", new_chat_name)
                        except Exception as e:
                            print(f"DB error /newchat: {e}")
                    telegram_send(chat_id, f"✅ Создан и выбран чат: *{escape_markdown(new_chat_name)}*", message_id)
                    self._send_ok()
                    return

                prompt = raw_text[5:].strip() if text.startswith("/ask") else raw_text

            elif chat_type in ("group", "supergroup"):
                is_reply_to_bot = False
                reply_msg = message.get("reply_to_message")
                if reply_msg and reply_msg.get("from", {}).get("is_bot"):
                    is_reply_to_bot = True

                bot_mentioned = BOT_USERNAME and f"@{BOT_USERNAME}" in raw_text.lower()

                if text.startswith("/ask"):
                    prompt = raw_text[5:].strip()
                elif bot_mentioned:
                    clean_txt = re.sub(f"@{BOT_USERNAME}", "", raw_text, flags=re.IGNORECASE).strip()
                    prompt = clean_txt
                elif is_reply_to_bot:
                    prompt = raw_text.strip()

        if not prompt:
            self._send_ok()
            return

        active_chat = get_user_active_chat(user_id)
        history = get_chat_history(user_id, active_chat)

        # АВТОМАТИЧЕСКОЕ ИМЕНОВАНИЕ ЧАТА ЧЕРЕЗ AI ПРИ ПЕРВОМ СООБЩЕНИИ
        if not history and active_chat.startswith("Новый чат"):
            ai_title = generate_chat_title_ai(prompt)
            if ai_title:
                rename_user_chat(user_id, active_chat, ai_title)
                active_chat = ai_title

        # ЗАПРОС К AI (GROQ)
        try:
            answer, used_model, is_fallback = ask_groq_with_fallback(user_id, history, prompt)
        except Exception as e:
            telegram_send(chat_id, f"❌ Ошибка Groq AI:\n{str(e)[:1000]}", message_id)
            self._send_ok()
            return

        prefix = ""
        if is_fallback:
            prefix = f"⚠️ *Основная модель недоступна. Переключение на:* `{used_model}`\n\n"

        full_response = prefix + answer

        # СОХРАНЕНИЕ КОНТЕКСТА
        history.append({"role": "user", "content": prompt})
        history.append({"role": "assistant", "content": answer})
        save_chat_history(user_id, active_chat, history)

        for i in range(0, len(full_response), 4000):
            telegram_send(chat_id, full_response[i:i + 4000], message_id)

        self._send_ok()

    def _handle_callback(self, cb):
        cb_id = cb.get("id")
        data = cb.get("data", "")
        msg = cb.get("message", {})
        chat_id = msg.get("chat", {}).get("id")
        message_id = msg.get("message_id")
        user_id = cb.get("from", {}).get("id", chat_id)

        if data == "noop":
            telegram_answer_callback(cb_id)
            return

        # ПАГИНАЦИЯ И МЕНЮ ЧАТОВ
        if data.startswith("chats_p_"):
            page = int(data.split("_")[2])
            kb = build_chats_menu_keyboard(user_id, page=page)
            active = escape_markdown(get_user_active_chat(user_id))
            telegram_edit_message(chat_id, message_id, f"📋 *Управление диалогами*\n\nТекущий активный чат: *{active}*", reply_markup=kb)

        elif data.startswith("sw_ch_"):
            parts = data.split("_")
            target_chat = parts[2]
            page = int(parts[3]) if len(parts) > 3 else 1

            if db:
                try:
                    db.set(f"user:{user_id}:active_chat", target_chat)
                except Exception as e:
                    print(f"DB Error switch_chat: {e}")

            telegram_answer_callback(cb_id, f"Переключено на: {target_chat}")
            kb = build_chats_menu_keyboard(user_id, page=page)
            telegram_edit_message(chat_id, message_id, f"📋 *Управление диалогами*\n\nТекущий активный чат: *{escape_markdown(target_chat)}*", reply_markup=kb)

        elif data == "action_new_chat":
            count = len(get_user_chats_list(user_id)) + 1
            new_name = f"Новый чат {count}"
            if db:
                try:
                    db.set(f"user:{user_id}:active_chat", new_name)
                    db.sadd(f"user:{user_id}:chats_list", new_name)
                except Exception as e:
                    print(f"DB Error action_new_chat: {e}")
            telegram_answer_callback(cb_id, f"Создан чат: {new_name}")
            kb = build_chats_menu_keyboard(user_id, page=1)
            msg_text = (
                f"✅ Создан и выбран: *{escape_markdown(new_name)}*\n\n"
                f"💡 При первом сообщении нейросеть автоматически переименует его по смыслу темы.\n"
                f"Или укажите своё имя через команду: `/newchat Имя`"
            )
            telegram_edit_message(chat_id, message_id, msg_text, reply_markup=kb)

        elif data.startswith("confirm_del_"):
            target_chat = data[12:]
            kb = build_delete_confirm_keyboard(target_chat)
            telegram_edit_message(chat_id, message_id, f"⚠️ *Вы точно хотите удалить чат «{escape_markdown(target_chat)}»?*\nВся история этого диалога будет безвозвратно очищена.", reply_markup=kb)

        elif data.startswith("do_del_"):
            target_chat = data[7:]
            purge_chat_data(user_id, target_chat)
            telegram_answer_callback(cb_id, f"Чат {target_chat} удалён!")
            kb = build_chats_menu_keyboard(user_id, page=1)
            active = escape_markdown(get_user_active_chat(user_id))
            telegram_edit_message(chat_id, message_id, f"🗑 Чат *{escape_markdown(target_chat)}* успешно удалён.\n\nТекущий активный чат: *{active}*", reply_markup=kb)

        elif data == "action_clean_orphans":
            deleted_count = cleanup_orphan_chats(user_id)
            telegram_answer_callback(cb_id, f"Очищено {deleted_count} устаревших ключей!")
            kb = build_chats_menu_keyboard(user_id, page=1)
            active = escape_markdown(get_user_active_chat(user_id))
            telegram_edit_message(chat_id, message_id, f"🧹 Сканирование завершено!\nУдалено устаревших ключей из базы: *{deleted_count}*\n\nТекущий активный чат: *{active}*", reply_markup=kb)

        elif data == "action_view_history":
            active_chat = get_user_active_chat(user_id)
            history = get_chat_history(user_id, active_chat)
            safe_active = escape_markdown(active_chat)
            if not history:
                telegram_answer_callback(cb_id, "История пуста")
                telegram_send(chat_id, f"📭 История диалога *{safe_active}* пуста.")
            else:
                formatted = [f"📜 *История диалога ({safe_active}):*"]
                for m in history:
                    role_str = '👤 Вы' if m['role'] == 'user' else '🤖 AI'
                    formatted.append(f"*{role_str}:* {m['content']}")
                telegram_send(chat_id, "\n\n".join(formatted))

        # МЕНЮ МОДЕЛЕЙ
        elif data == "main_menu":
            kb = build_main_settings_keyboard(user_id)
            telegram_edit_message(chat_id, message_id, "⚙️ *Настройки моделей AI*\n\nВыберите категорию:", reply_markup=kb)

        elif data == "cat_text":
            kb = build_category_keyboard(user_id, "text")
            telegram_edit_message(chat_id, message_id, "📝 *Выбор текстовой модели (Чат):*", reply_markup=kb)

        elif data == "cat_voice":
            kb = build_category_keyboard(user_id, "voice")
            telegram_edit_message(chat_id, message_id, "🎙 *Выбор модели распознавания голоса:*", reply_markup=kb)

        elif data == "cat_mod":
            kb = build_category_keyboard(user_id, "mod")
            telegram_edit_message(chat_id, message_id, "🛡 *Выбор модели модерации:*", reply_markup=kb)

        elif data == "set_all_auto":
            set_user_setting(user_id, "model_text", "auto")
            set_user_setting(user_id, "model_voice", "auto")
            set_user_setting(user_id, "model_mod", "auto")
            telegram_answer_callback(cb_id, "⚡ AUTO применён!")
            kb = build_main_settings_keyboard(user_id)
            telegram_edit_message(chat_id, message_id, "⚙️ *Настройки моделей AI*\n\n✅ AUTO применён ко всем категориям!", reply_markup=kb)

        elif data.startswith("set_txt_"):
            m = data[8:]
            set_user_setting(user_id, "model_text", m)
            telegram_answer_callback(cb_id, f"Текстовая модель: {m}")
            kb = build_category_keyboard(user_id, "text")
            telegram_edit_message(chat_id, message_id, "📝 *Выбор текстовой модели (Чат):*", reply_markup=kb)

        elif data.startswith("set_voc_"):
            m = data[8:]
            set_user_setting(user_id, "model_voice", m)
            telegram_answer_callback(cb_id, f"Голосовая модель: {m}")
            kb = build_category_keyboard(user_id, "voice")
            telegram_edit_message(chat_id, message_id, "🎙 *Выбор модели распознавания голоса:*", reply_markup=kb)

        elif data.startswith("set_mod_"):
            m = data[8:]
            set_user_setting(user_id, "model_mod", m)
            telegram_answer_callback(cb_id, f"Модель модерации: {m}")
            kb = build_category_keyboard(user_id, "mod")
            telegram_edit_message(chat_id, message_id, "🛡 *Выбор модели модерации:*", reply_markup=kb)

        elif data == "close_menu":
            telegram_answer_callback(cb_id, "Закрыто")
            telegram_edit_message(chat_id, message_id, "❌ Меню закрыто.")

    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain; charset=utf-8')
        self.end_headers()
        self.wfile.write("Vercel Webhook is ONLINE!".encode('utf-8'))

    def _send_ok(self):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True}).encode('utf-8'))
    
