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
groq = Groq(api_key=GROQ_API_KEY)

db = Redis(url=UPSTASH_URL, token=UPSTASH_TOKEN) if UPSTASH_URL and UPSTASH_TOKEN else None

# Получаем юзернейм бота при запуске (или задайте вручную)
BOT_USERNAME = None
try:
    bot_info = requests.get(f"{TELEGRAM_API}/getMe").json()
    if bot_info.get("ok"):
        BOT_USERNAME = bot_info["result"]["username"].lower()
except Exception:
    BOT_USERNAME = "neirogpt234_bot"


# ---- TELEGRAM API & TEXT HELPERS ----

def escape_markdown(text):
    """Экранирует спецсимволы Markdown, чтобы подчёркивания и звездочки не «съедались»"""
    if not text:
        return ""
    for char in ['_', '*', '`', '[']:
        text = text.replace(char, f"\\{char}")
    return text


def clean_command(text):
    """Убирает юзернейм бота из команды (например /start@neirogpt234_bot -> /start)"""
    if text.startswith("/"):
        parts = text.split(maxsplit=1)
        cmd = parts[0].split("@")[0]
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
    telegram_request("sendMessage", data)


def telegram_edit_message(chat_id, message_id, text, reply_markup=None):
    data = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    if reply_markup:
        data["reply_markup"] = reply_markup
    telegram_request("editMessageText", data)


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
        models_data = groq.models.list()
        return [m.id for m in models_data.data]
    except Exception as e:
        print(f"Ошибка получения моделей: {e}")
        return [
            "openai/gpt-oss-120b", "openai/gpt-oss-20b",
            "llama-3.3-70b-versatile", "llama-3.1-8b-instant",
            "whisper-large-v3-turbo", "whisper-large-v3",
            "openai/gpt-oss-safeguard-20b"
        ]


def get_categorized_models():
    all_models = fetch_all_groq_models()

    text_models = [m for m in all_models if not any(x in m for x in ["whisper", "prompt-guard", "safeguard", "orpheus"])]
    voice_models = [m for m in all_models if "whisper" in m]
    mod_models = [m for m in all_models if any(x in m for x in ["safeguard", "prompt-guard"])]

    if not voice_models:
        voice_models = ["whisper-large-v3-turbo", "whisper-large-v3"]
    if not mod_models:
        mod_models = ["openai/gpt-oss-safeguard-20b"]

    return text_models, voice_models, mod_models


# ---- DATABASE SETTINGS HELPERS ----

def get_user_setting(user_id, key, default="auto"):
    if not db:
        return default
    val = db.get(f"user:{user_id}:{key}")
    if not val:
        return default
    return val if isinstance(val, str) else val.decode('utf-8')


def set_user_setting(user_id, key, value):
    if db:
        db.set(f"user:{user_id}:{key}", value)


def get_user_active_chat(user_id):
    if not db:
        return "chat_1"
    active = db.get(f"user:{user_id}:active_chat")
    if not active:
        active = "chat_1"
        db.set(f"user:{user_id}:active_chat", active)
        db.sadd(f"user:{user_id}:chats_list", active)
    return active if isinstance(active, str) else active.decode('utf-8')


def get_chat_history(user_id, chat_name):
    if not db:
        return []
    history = db.get(f"user:{user_id}:chat:{chat_name}")
    if not history:
        return []
    if isinstance(history, bytes):
        history = history.decode('utf-8')
    return json.loads(history)


def save_chat_history(user_id, chat_name, history):
    if db:
        db.set(f"user:{user_id}:chat:{chat_name}", json.dumps(history[-10:]))


# ---- MENU KEYBOARDS ----

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

def get_system_prompt_for_model(model_name):
    m_lower = model_name.lower()

    if "gemma" in m_lower:
        name = "Gemma"
        creator = "Google"
    elif "llama" in m_lower:
        name = "Llama"
        creator = "Meta"
    elif "qwen" in m_lower:
        name = "Qwen"
        creator = "Alibaba"
    elif "gpt-oss" in m_lower:
        name = "GPT-OSS"
        creator = "OpenAI"
    elif "mixtral" in m_lower or "mistral" in m_lower:
        name = "Mistral"
        creator = "Mistral AI"
    else:
        name = model_name
        creator = "Groq"

    return (
        f"Ты — виртуальный помощник {name}, созданный компанией {creator}. "
        f"Твоя задача — отвечать на вопросы пользователей и помогать в самых разных задачах. "
        f"Если тебя спрашивают кто ты, ты должен строго отвечать: "
        f"«Я — виртуальный помощник {name}, созданный компанией {creator}. Моя задача — отвечать на ваши вопросы и помогать в самых разных задачах. Чем могу быть полезен?»"
    )


def transcribe_voice(user_id, file_id):
    file_url = get_telegram_file_url(file_id)
    if not file_url:
        raise Exception("Не удалось скачать аудиофайл.")

    audio_data = requests.get(file_url).content
    selected_model = get_user_setting(user_id, "model_voice", "auto")

    _, voice_models, _ = get_categorized_models()
    models_to_try = [selected_model] if selected_model != "auto" else voice_models

    last_err = None
    for m in models_to_try:
        try:
            transcription = groq.audio.transcriptions.create(
                file=("voice.ogg", audio_data, "audio/ogg"),
                model=m,
                response_format="json"
            )
            return transcription.text, m
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

    target_model = selected_model if selected_model != "auto" else (text_models[0] if text_models else "llama-3.3-70b-versatile")
    system_instruction = get_system_prompt_for_model(target_model)

    messages = [{"role": "system", "content": system_instruction}]
    for msg in history:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": prompt})

    if selected_model != "auto":
        response = groq.chat.completions.create(
            model=selected_model,
            messages=messages,
            max_completion_tokens=2048,
            reasoning_effort="low" if "gpt-oss" in selected_model else None
        )
        return response.choices[0].message.content, selected_model, False

    last_error = None
    for model_name in text_models:
        try:
            current_system = get_system_prompt_for_model(model_name)
            messages[0] = {"role": "system", "content": current_system}

            response = groq.chat.completions.create(
                model=model_name,
                messages=messages,
                max_completion_tokens=2048,
                reasoning_effort="low" if "gpt-oss" in model_name else None
            )
            answer = response.choices[0].message.content
            if answer:
                is_fallback = (model_name != text_models[0])
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
            self._handle_callback(callback_query)
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

        # КОМАНДЫ ПРИВЕТСТВИЯ И НАСТРОЙКИ МОДЕЛЕЙ
        if text.startswith("/start"):
            telegram_send(chat_id, "👋 Привет! Я AI-помощник.\nИспользуй `/setmodel` для выбора моделей или просто отправь сообщение.", message_id)
            self._send_ok()
            return

        if text.startswith("/setmodel") or text.startswith("/models"):
            kb = build_main_settings_keyboard(user_id)
            telegram_send(chat_id, "⚙️ *Настройки моделей AI*\n\nВыберите категорию для настройки:", reply_markup=kb)
            self._send_ok()
            return

        # ГОЛОСОВЫЕ СООБЩЕНИЯ
        if voice:
            try:
                telegram_send(chat_id, "🎙 *Распознаю голос...*", message_id)
                transcribed_text, used_voice_model = transcribe_voice(user_id, voice.get("file_id"))
                safe_trans = escape_markdown(transcribed_text)
                telegram_send(chat_id, f"🗣 *Расшифровка (`{used_voice_model}`):*\n_{safe_trans}_", message_id)
            except Exception as e:
                telegram_send(chat_id, f"❌ Ошибка распознавания: {e}", message_id)
                self._send_ok()
                return

        if not text:
            self._send_ok()
            return

        # МОДЕРАЦИЯ
        if text.startswith("/moderation"):
            check_text = text[11:].strip()
            if not check_text:
                telegram_send(chat_id, "Использование: `/moderation <текст>`", message_id)
                self._send_ok()
                return
            result, mod_m = check_moderation(user_id, check_text)
            telegram_send(chat_id, f"🛡 *Модерация (`{mod_m}`):*\n\n{result}", message_id)
            self._send_ok()
            return

        # УПРАВЛЕНИЕ ЧАТАМИ
        if text.startswith("/newchat"):
            parts = text.split(maxsplit=1)
            if len(parts) > 1 and parts[1].strip():
                new_chat_name = parts[1].strip()
            else:
                count = len(db.smembers(f'user:{user_id}:chats_list')) if db else 0
                new_chat_name = f"chat_{count + 1}"

            if db:
                db.set(f"user:{user_id}:active_chat", new_chat_name)
                db.sadd(f"user:{user_id}:chats_list", new_chat_name)
            
            safe_name = escape_markdown(new_chat_name)
            telegram_send(chat_id, f"✅ Чат переключён на: *{safe_name}*", message_id)
            self._send_ok()
            return

        elif text.startswith("/chats"):
            if not db:
                telegram_send(chat_id, "База данных недоступна.", message_id)
                self._send_ok()
                return
            active = get_user_active_chat(user_id)
            raw_chats = db.smembers(f"user:{user_id}:chats_list")
            
            chats_list = []
            for c in raw_chats:
                name = c.decode('utf-8') if isinstance(c, bytes) else str(c)
                safe_n = escape_markdown(name)
                if name == active:
                    chats_list.append(f"👉 *{safe_n}* (активный)")
                else:
                    chats_list.append(f"🔹 {safe_n}")

            msg = "📋 *Ваши диалоги:*\n\n" + "\n".join(chats_list) + "\n\nПереключить: `/newchat <название>`"
            telegram_send(chat_id, msg, message_id)
            self._send_ok()
            return

        elif text.startswith("/history"):
            active_chat = get_user_active_chat(user_id)
            history = get_chat_history(user_id, active_chat)
            safe_active = escape_markdown(active_chat)
            if not history:
                telegram_send(chat_id, f"📭 История диалога *{safe_active}* пуста.", message_id)
            else:
                formatted = [f"📜 *История диалога ({safe_active}):*"]
                for m in history:
                    role_str = '👤 Вы' if m['role'] == 'user' else '🤖 AI'
                    formatted.append(f"*{role_str}:* {m['content']}")
                telegram_send(chat_id, "\n\n".join(formatted), message_id)
            self._send_ok()
            return

        elif text.startswith("/deletechat"):
            parts = text.split(maxsplit=1)
            active_chat = get_user_active_chat(user_id)
            target_chat = parts[1].strip() if len(parts) > 1 else active_chat
            if db:
                db.delete(f"user:{user_id}:chat:{target_chat}")
                db.srem(f"user:{user_id}:chats_list", target_chat)
                if target_chat == active_chat:
                    db.set(f"user:{user_id}:active_chat", "chat_1")
                    db.sadd(f"user:{user_id}:chats_list", "chat_1")
            
            safe_target = escape_markdown(target_chat)
            telegram_send(chat_id, f"🗑 Диалог *{safe_target}* удалён.", message_id)
            self._send_ok()
            return

        # ИЗВЛЕЧЕНИЕ ТЕКСТА ЗАПРОСА В ЛИЧНЫХ СООБЩЕНИЯХ И ГРУППАХ
        prompt = None

        if chat_type == "private":
            prompt = text[5:].strip() if text.startswith("/ask ") else text
        elif chat_type in ("group", "supergroup"):
            # Проверяем условия для группы:
            is_reply_to_bot = False
            reply_msg = message.get("reply_to_message")
            if reply_msg and reply_msg.get("from", {}).get("is_bot"):
                is_reply_to_bot = True

            bot_mentioned = BOT_USERNAME and f"@{BOT_USERNAME}" in raw_text.lower()

            if text.startswith("/ask "):
                prompt = text[5:].strip()
            elif bot_mentioned:
                # Удаляем из текста юзернейм бота
                clean_txt = re.sub(f"@{BOT_USERNAME}", "", raw_text, flags=re.IGNORECASE).strip()
                prompt = clean_txt
            elif is_reply_to_bot:
                prompt = raw_text.strip()

        if not prompt:
            self._send_ok()
            return

        active_chat = get_user_active_chat(user_id)
        history = get_chat_history(user_id, active_chat)

        # ЗАПРОС К AI
        try:
            answer, used_model, is_fallback = ask_groq_with_fallback(user_id, history, prompt)
        except Exception as e:
            telegram_send(chat_id, f"❌ Ошибка Groq AI:\n{str(e)[:1000]}", message_id)
            self._send_ok()
            return

        prefix = ""
        if is_fallback:
            prefix = f"⚠️ *Внимание! Основная модель недоступна. Автопереключение на:* `{used_model}`\n\n"

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

        if data == "main_menu":
            kb = build_main_settings_keyboard(user_id)
            telegram_edit_message(chat_id, message_id, "⚙️ *Настройки моделей AI*\n\nВыберите категорию для настройки:", reply_markup=kb)

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
            telegram_answer_callback(cb_id, "⚡ Режим AUTO включён для всех категорий!")
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
            telegram_answer_callback(cb_id, "Меню закрыто")
            telegram_edit_message(chat_id, message_id, "❌ Настройки закрыты.")

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
