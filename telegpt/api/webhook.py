import os
import json
import requests
from groq import Groq


TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

groq = Groq(api_key=GROQ_API_KEY)

MODEL = "openai/gpt-oss-120b"


def telegram_send(chat_id, text, reply_to=None):
    data = {
        "chat_id": chat_id,
        "text": text
    }

    if reply_to:
        data["reply_to_message_id"] = reply_to

    response = requests.post(
        f"{TELEGRAM_API}/sendMessage",
        json=data,
        timeout=30
    )

    print("TELEGRAM:", response.status_code, response.text)


def ask_groq(prompt):
    response = groq.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": "You are a helpful AI assistant in Telegram. Answer clearly and naturally."
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

    print("========== TELEGRAM WEBHOOK ==========")

    # Проверяем HTTP метод
    if request.method != "POST":
        return {
            "statusCode": 200,
            "body": "Telegram webhook is working!"
        }

    try:
        update = request.get_json()
    except Exception as e:
        print("JSON ERROR:", repr(e))

        return {
            "statusCode": 400,
            "body": "Invalid JSON"
        }

    print("UPDATE:", update)

    if not update:
        return {
            "statusCode": 200,
            "body": "OK"
        }

    message = update.get("message")

    if not message:
        return {
            "statusCode": 200,
            "body": "OK"
        }

    chat = message.get("chat", {})
    chat_id = chat.get("id")
    chat_type = chat.get("type")
    message_id = message.get("message_id")

    text = message.get("text")

    if not text:
        return {
            "statusCode": 200,
            "body": "OK"
        }

    text = text.strip()

    print("CHAT TYPE:", chat_type)
    print("TEXT:", text)

    prompt = None

    # ==========================================
    # ЛИЧНЫЙ ЧАТ
    # ==========================================

    if chat_type == "private":

        # /ask вопрос
        if text.startswith("/ask "):
            prompt = text[5:].strip()

        # /ask
        elif text == "/ask":

            telegram_send(
                chat_id,
                "Напиши вопрос после /ask 🙂"
            )

            return {
                "statusCode": 200,
                "body": "OK"
            }

        # Обычный текст БЕЗ /ask
        else:
            prompt = text

    # ==========================================
    # ГРУППА
    # ==========================================

    elif chat_type in ("group", "supergroup"):

        # /ask вопрос
        if text.startswith("/ask "):
            prompt = text[5:].strip()

        # /ask@username_bot вопрос
        elif text.startswith("/ask@"):

            command, separator, question = text.partition(" ")

            mentioned_username = command[5:]

            try:
                bot_info = requests.get(
                    f"{TELEGRAM_API}/getMe",
                    timeout=10
                ).json()

                bot_username = bot_info["result"]["username"]

            except Exception as e:
                print("getMe ERROR:", repr(e))

                return {
                    "statusCode": 200,
                    "body": "OK"
                }

            if (
                mentioned_username.lower() == bot_username.lower()
                and separator
                and question.strip()
            ):
                prompt = question.strip()

        # Просто /ask
        elif text == "/ask":

            telegram_send(
                chat_id,
                "Напиши вопрос после /ask 🙂"
            )

            return {
                "statusCode": 200,
                "body": "OK"
            }

        # Всё остальное игнорируем
        else:
            return {
                "statusCode": 200,
                "body": "IGNORED"
            }

        if not prompt:
            return {
                "statusCode": 200,
                "body": "IGNORED"
            }

    # Каналы и прочее игнорируем
    else:
        return {
            "statusCode": 200,
            "body": "IGNORED"
        }

    # ==========================================
    # GROQ
    # ==========================================

    try:

        print("GROQ PROMPT:", prompt)

        answer = ask_groq(prompt)

        print("GROQ ANSWER:", answer)

    except Exception as e:

        print("GROQ ERROR:", repr(e))

        telegram_send(
            chat_id,
            "❌ Ошибка при обращении к AI:\n" + str(e)[:1000]
        )

        return {
            "statusCode": 200,
            "body": "GROQ ERROR"
        }

    if not answer:
        answer = "AI вернул пустой ответ."

    # ==========================================
    # ОТПРАВКА В TELEGRAM
    # ==========================================

    # Telegram позволяет максимум около 4096 символов
    for i in range(0, len(answer), 4000):

        telegram_send(
            chat_id,
            answer[i:i + 4000],
            message_id
        )

    return {
        "statusCode": 200,
        "body": json.dumps({"ok": True})
    }
