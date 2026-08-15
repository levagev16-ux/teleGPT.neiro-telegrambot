import os
import requests
from flask import Flask, request, jsonify
from groq import Groq

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]

MODEL = "openai/gpt-oss-120b"

groq = Groq(api_key=GROQ_API_KEY)

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"


def send_message(chat_id, text, reply_to=None):
    data = {
        "chat_id": chat_id,
        "text": text
    }

    if reply_to:
        data["reply_to_message_id"] = reply_to

    requests.post(
        f"{TELEGRAM_API}/sendMessage",
        json=data,
        timeout=30
    )


def ask_ai(prompt):
    response = groq.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": "You are a helpful AI assistant in Telegram."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        max_completion_tokens=2048,
        reasoning_effort="low",
        include_reasoning=False
    )

    return response.choices[0].message.content


@app.route("/api/webhook", methods=["POST"])
def webhook():

    update = request.get_json(silent=True)

    if not update:
        return jsonify({"ok": True})

    message = update.get("message")

    if not message:
        return jsonify({"ok": True})

    chat = message.get("chat", {})
    chat_id = chat.get("id")
    chat_type = chat.get("type")
    message_id = message.get("message_id")

    text = message.get("text")

    if not text:
        return jsonify({"ok": True})

    text = text.strip()

    # =========================
    # ЛИЧНЫЙ ЧАТ
    # =========================

    if chat_type == "private":

        # /ask текст
        if text.startswith("/ask "):
            prompt = text[5:].strip()

        # /ask без текста
        elif text == "/ask":
            send_message(
                chat_id,
                "Напиши вопрос после /ask 🙂",
                message_id
            )
            return jsonify({"ok": True})

        # Любой обычный текст БЕЗ /ask
        else:
            prompt = text

    # =========================
    # ГРУППА
    # =========================

    elif chat_type in ("group", "supergroup"):

        prompt = None

        # /ask текст
        if text.startswith("/ask "):
            prompt = text[5:].strip()

        # Получаем username бота
        elif text.startswith("/ask@"):
            command, separator, question = text.partition(" ")

            bot_username = command[5:]

            me = requests.get(
                f"{TELEGRAM_API}/getMe",
                timeout=10
            ).json()

            real_username = me.get("result", {}).get("username", "")

            # Разрешаем только /ask@ИМЯ_ЭТОГО_БОТА
            if (
                bot_username.lower() == real_username.lower()
                and separator
                and question.strip()
            ):
                prompt = question.strip()

        # Просто /ask
        elif text == "/ask":
            send_message(
                chat_id,
                "Напиши вопрос после /ask 🙂",
                message_id
            )
            return jsonify({"ok": True})

        # /ask@bot без текста
        elif text.startswith("/ask@"):
            send_message(
                chat_id,
                "Напиши вопрос после команды 🙂",
                message_id
            )
            return jsonify({"ok": True})

        # Всё остальное в группе игнорируем
        if not prompt:
            return jsonify({"ok": True})

    else:
        return jsonify({"ok": True})

    # =========================
    # AI
    # =========================

    try:
        answer = ask_ai(prompt)

    except Exception as e:
        print("GROQ ERROR:", repr(e))

        send_message(
            chat_id,
            "❌ Не удалось получить ответ от AI."
        )

        return jsonify({"ok": True})

    # Telegram message limit
    MAX_LENGTH = 4000

    for i in range(0, len(answer), MAX_LENGTH):
        send_message(
            chat_id,
            answer[i:i + MAX_LENGTH],
            message_id
        )

    return jsonify({"ok": True})