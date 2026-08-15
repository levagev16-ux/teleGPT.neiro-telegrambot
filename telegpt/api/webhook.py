import os
import requests
from groq import Groq

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

groq = Groq(api_key=GROQ_API_KEY)

MODEL = "openai/gpt-oss-120b"


def send_message(chat_id, text):
    response = requests.post(
        f"{TELEGRAM_API}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text
        },
        timeout=30
    )

    print("TELEGRAM:", response.status_code, response.text)


def ask_ai(prompt):
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

    return response.choices[0].message.content


def handler(request):
    print("========== WEBHOOK ==========")

    if request.method != "POST":
        return {
            "statusCode": 200,
            "body": "Telegram webhook is working!"
        }

    update = request.get_json()

    print("UPDATE:", update)

    message = update.get("message")

    if not message:
        return {
            "statusCode": 200,
            "body": "OK"
        }

    chat = message.get("chat", {})
    chat_id = chat.get("id")
    chat_type = chat.get("type")
    text = message.get("text")

    if not text:
        return {
            "statusCode": 200,
            "body": "OK"
        }

    text = text.strip()

    # =========================
    # ЛИЧКА
    # =========================

    if chat_type == "private":

        if text.startswith("/ask "):
            prompt = text[5:].strip()

        elif text == "/ask":
            send_message(
                chat_id,
                "Напиши вопрос после /ask 🙂"
            )

            return {
                "statusCode": 200,
                "body": "OK"
            }

        else:
            prompt = text

    # =========================
    # ГРУППА
    # =========================

    elif chat_type in ("group", "supergroup"):

        prompt = None

        if text.startswith("/ask "):
            prompt = text[5:].strip()

        elif text.startswith("/ask@"):

            command, separator, question = text.partition(" ")

            username = command[5:]

            me = requests.get(
                f"{TELEGRAM_API}/getMe",
                timeout=10
            ).json()

            bot_username = me["result"]["username"]

            if (
                username.lower() == bot_username.lower()
                and separator
            ):
                prompt = question.strip()

        elif text == "/ask":

            send_message(
                chat_id,
                "Напиши вопрос после /ask 🙂"
            )

            return {
                "statusCode": 200,
                "body": "OK"
            }

        if not prompt:
            return {
                "statusCode": 200,
                "body": "IGNORED"
            }

    else:
        return {
            "statusCode": 200,
            "body": "IGNORED"
        }

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

        return {
            "statusCode": 200,
            "body": "GROQ ERROR"
        }

    # =========================
    # TELEGRAM
    # =========================

    for i in range(0, len(answer), 4000):

        send_message(
            chat_id,
            answer[i:i + 4000]
        )

    return {
        "statusCode": 200,
        "body": "OK"
    }
