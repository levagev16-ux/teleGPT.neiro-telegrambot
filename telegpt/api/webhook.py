import os
import json
import requests
from http.server import BaseHTTPRequestHandler
from groq import Groq

# Получение переменных окружения
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
groq = Groq(api_key=GROQ_API_KEY)

# Модель Groq
MODEL = "openai/gpt-oss-20b"


def telegram_send(chat_id, text, reply_to=None):
    data = {
        "chat_id": chat_id,
        "text": text
    }

    if reply_to:
        data["reply_to_message_id"] = reply_to

    try:
        response = requests.post(
            f"{TELEGRAM_API}/sendMessage",
            json=data,
            timeout=30
        )
        print("TELEGRAM LOG:", response.status_code, response.text)
    except Exception as e:
        print("TELEGRAM SEND ERROR:", repr(e))


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
        reasoning_effort="low"
    )

    return response.choices[0].message.content


class handler(BaseHTTPRequestHandler):

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)

        try:
            update = json.loads(post_data.decode('utf-8'))
        except Exception as e:
            print("JSON ERROR:", repr(e))
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Invalid JSON")
            return

        print("UPDATE:", update)

        message = update.get("message")
        if not message:
            self._send_ok()
            return

        chat = message.get("chat", {})
        chat_id = chat.get("id")
        chat_type = chat.get("type")
        message_id = message.get("message_id")
        text = message.get("text")

        if not text:
            self._send_ok()
            return

        text = text.strip()
        prompt = None

        # --- ЛИЧНЫЙ ЧАТ ---
        if chat_type == "private":
            if text.startswith("/ask "):
                prompt = text[5:].strip()
            elif text == "/ask":
                telegram_send(chat_id, "Напиши вопрос после /ask 🙂")
                self._send_ok()
                return
            else:
                prompt = text

        # --- ГРУППА ---
        elif chat_type in ("group", "supergroup"):
            if text.startswith("/ask "):
                prompt = text[5:].strip()
            elif text.startswith("/ask@"):
                command, separator, question = text.partition(" ")
                mentioned_username = command[5:]
                try:
                    bot_info = requests.get(f"{TELEGRAM_API}/getMe", timeout=10).json()
                    bot_username = bot_info.get("result", {}).get("username", "")
                except Exception as e:
                    print("getMe ERROR:", repr(e))
                    self._send_ok()
                    return

                if (
                    mentioned_username.lower() == bot_username.lower()
                    and separator
                    and question.strip()
                ):
                    prompt = question.strip()

            elif text == "/ask":
                telegram_send(chat_id, "Напиши вопрос после /ask 🙂")
                self._send_ok()
                return
            else:
                self._send_ok()
                return

            if not prompt:
                self._send_ok()
                return

        else:
            self._send_ok()
            return

        # --- GROQ (openai/gpt-oss-120b) ---
        try:
            print("GROQ PROMPT:", prompt)
            answer = ask_groq(prompt)
            print("GROQ ANSWER:", answer)
        except Exception as e:
            print("GROQ ERROR:", repr(e))
            telegram_send(chat_id, f"❌ Ошибка при обращении к AI:\n{str(e)[:1000]}")
            self._send_ok()
            return

        if not answer:
            answer = "AI вернул пустой ответ."

        # --- ОТПРАВКА В TELEGRAM ---
        for i in range(0, len(answer), 4000):
            telegram_send(chat_id, answer[i:i + 4000], message_id)

        self._send_ok()

    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain; charset=utf-8')
        self.end_headers()
        self.wfile.write("Telegram webhook is working!".encode('utf-8'))

    def _send_ok(self):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True}).encode('utf-8'))
