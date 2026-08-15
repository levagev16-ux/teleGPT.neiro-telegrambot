import os
import requests
from flask import Flask, request, jsonify
from groq import Groq

app = Flask(__name__)

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

groq = Groq(api_key=GROQ_API_KEY)

MODEL = "openai/gpt-oss-120b"


def send_message(chat_id, text):
    r = requests.post(
        f"{TELEGRAM_API}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text
        },
        timeout=30
    )

    print("TELEGRAM SEND:", r.status_code, r.text)


def ask_ai(prompt):
    print("GROQ PROMPT:", prompt)

    response = groq.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": "You are a helpful AI assistant."
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

    answer = response.choices[0].message.content

    print("GROQ ANSWER:", answer)

    return answer


@app.route("/api/webhook", methods=["POST"])
def webhook():

    print("========== WEBHOOK ==========")

    update = request.get_json(silent=True)

    print("UPDATE:", update)

    if not update:
        return jsonify({"ok": True})

    message = update.get("message")

    if not message:
        return jsonify({"ok": True})

    chat = message.get("chat", {})
    chat_id = chat.get("id")
    chat_type = chat.get("type")

    text = message.get("text")

    print("CHAT:", chat_id)
    print("TYPE:", chat_type)
    print("TEXT:", text)

    if not text:
        return jsonify({"ok": True})

    text = text.strip()

    # =========================
    # PRIVATE CHAT
    # =========================

    if chat_type == "private":

        if text.startswith("/ask "):
            prompt = text[5:].strip()

        elif text == "/ask":
            send_message(
                chat_id,
                "Напиши вопрос после /ask 🙂"
            )
            return jsonify({"ok": True})

        else:
            prompt = text

    # =========================
    # GROUP
    # =========================

    elif chat_type in ("group", "supergroup"):

        prompt = None

        if text.startswith("/ask "):
            prompt = text[5:].strip()

        elif text.startswith("/ask@"):

            command, separator, question = text.partition(" ")

            bot_username = command[5:]

            me = requests.get(
                f"{TELEGRAM_API}/getMe",
                timeout=10
            ).json()

            real_username = me["result"]["username"]

            if (
                bot_username.lower() == real_username.lower()
                and separator
            ):
                prompt = question.strip()

        elif text == "/ask":

            send_message(
                chat_id,
                "Напиши вопрос после /ask 🙂"
            )

            return jsonify({"ok": True})

        elif text.startswith("/ask@"):

            send_message(
                chat_id,
                "Напиши вопрос после команды 🙂"
            )

            return jsonify({"ok": True})

        if not prompt:
            return jsonify({"ok": True})

    else:
        return jsonify({"ok": True})

    # =========================
    # GROQ
    # =========================

    try:

        answer = ask_ai(prompt)

    except Exception as e:

        print("GROQ ERROR:", repr(e))

        send_message(
            chat_id,
            "❌ Ошибка Groq:\n" + str(e)[:1000]
        )

        return jsonify({"ok": True})

    # =========================
    # TELEGRAM
    # =========================

    if not answer:
        answer = "AI вернул пустой ответ."

    for i in range(0, len(answer), 4000):

        send_message(
            chat_id,
            answer[i:i + 4000]
        )

    return jsonify({"ok": True})
