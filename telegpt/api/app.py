import os
import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

try:
    from groq import Groq
except ImportError:
    Groq = None

try:
    from upstash_redis import Redis
except ImportError:
    Redis = None

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
UPSTASH_URL = os.environ.get("KV_REST_API_URL")
UPSTASH_TOKEN = os.environ.get("KV_REST_API_TOKEN")

groq = Groq(api_key=GROQ_API_KEY) if Groq and GROQ_API_KEY else None
db = Redis(url=UPSTASH_URL, token=UPSTASH_TOKEN) if Redis and UPSTASH_URL and UPSTASH_TOKEN else None

def decode_val(val):
    return val.decode('utf-8') if isinstance(val, bytes) else str(val or "")

class handler(BaseHTTPRequestHandler):

    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def do_OPTIONS(self):
        self._send_json({"status": "ok"}, 200)

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        user_id = params.get('user_id', ['browser_user'])[0]

        if 'models' in parsed.path:
            models_list = []
            if groq:
                try:
                    res = groq.models.list()
                    models_list = [
                        m.id for m in res.data 
                        if getattr(m, 'active', True) and not m.id.startswith('whisper')
                    ]
                    models_list.sort()
                except Exception as e:
                    print(f"Error fetching models: {e}")
            
            self._send_json({"models": models_list})
            return

        if 'chats' in parsed.path:
            raw_chats = db.smembers(f"user:{user_id}:chats_list") if db else []
            chats = [decode_val(c) for c in raw_chats] if raw_chats else ["Основной чат"]
            active = decode_val(db.get(f"user:{user_id}:active_chat")) if db else chats[0]
            self._send_json({"chats": sorted(chats), "active": active})
            return

        if 'history' in parsed.path:
            chat_name = params.get('chat_name', [''])[0]
            raw = db.get(f"user:{user_id}:chat:{chat_name}") if db else None
            history = json.loads(decode_val(raw)) if raw else []
            self._send_json({"history": history})
            return

        self._send_json({"error": f"Route not found: {parsed.path}"}, 404)

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        raw_body = self.rfile.read(length).decode('utf-8') if length > 0 else "{}"
        try:
            body = json.loads(raw_body)
        except Exception:
            body = {}

        user_id = body.get('user_id', 'browser_user')
        parsed = urlparse(self.path)

        if 'switch' in parsed.path:
            name = body.get('chat_name')
            if db and name: 
                db.set(f"user:{user_id}:active_chat", name)
            self._send_json({"ok": True})
            return

        if 'create' in parsed.path:
            name = body.get('chat_name')
            if db and name:
                db.sadd(f"user:{user_id}:chats_list", name)
                db.set(f"user:{user_id}:active_chat", name)
            self._send_json({"ok": True})
            return

        if 'delete' in parsed.path:
            name = body.get('chat_name')
            if db and name:
                db.delete(f"user:{user_id}:chat:{name}")
                db.srem(f"user:{user_id}:chats_list", name)
            self._send_json({"ok": True})
            return

        if 'message' in parsed.path:
            chat_name = body.get('chat_name', 'Основной чат')
            prompt = body.get('prompt')
            model = body.get('model', 'llama-3.3-70b-versatile')

            if not Groq:
                self._send_json({"error": "Библиотека groq не установлена на Vercel"}, 200)
                return
            if not GROQ_API_KEY:
                self._send_json({"error": "Ключ GROQ_API_KEY не задан в Environment Variables Vercel"}, 200)
                return

            raw_h = db.get(f"user:{user_id}:chat:{chat_name}") if db else None
            history = json.loads(decode_val(raw_h)) if raw_h else []

            messages = [{"role": m["role"], "content": m["content"]} for m in history[-10:]]
            messages.append({"role": "user", "content": prompt})

            try:
                res = groq.chat.completions.create(model=model, messages=messages)
                answer = res.choices[0].message.content

                history.append({"role": "user", "content": prompt})
                history.append({"role": "assistant", "content": answer})

                if db:
                    db.set(f"user:{user_id}:chat:{chat_name}", json.dumps(history[-20:]))

                self._send_json({"answer": answer})
            except Exception as e:
                self._send_json({"error": f"Ошибка API Groq ({model}): {str(e)}"}, 200)
            return

        self._send_json({"error": f"POST Route not found: {parsed.path}"}, 404)
        
