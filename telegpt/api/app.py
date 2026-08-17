import os
import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
from groq import Groq
from upstash_redis import Redis

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
UPSTASH_URL = os.environ.get("KV_REST_API_URL")
UPSTASH_TOKEN = os.environ.get("KV_REST_API_TOKEN")

groq = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
db = Redis(url=UPSTASH_URL, token=UPSTASH_TOKEN) if UPSTASH_URL and UPSTASH_TOKEN else None

def decode_val(val):
    return val.decode('utf-8') if isinstance(val, bytes) else str(val or "")

class handler(BaseHTTPRequestHandler):

    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        user_id = params.get('user_id', [''])[0]

        if parsed.path.startswith('/api/app/chats'):
            raw_chats = db.smembers(f"user:{user_id}:chats_list") if db else []
            chats = [decode_val(c) for c in raw_chats] if raw_chats else ["Основной чат"]
            active = decode_val(db.get(f"user:{user_id}:active_chat")) if db else chats[0]
            self._send_json({"chats": sorted(chats), "active": active})
            return

        if parsed.path.startswith('/api/app/history'):
            chat_name = params.get('chat_name', [''])[0]
            raw = db.get(f"user:{user_id}:chat:{chat_name}") if db else None
            history = json.loads(decode_val(raw)) if raw else []
            self._send_json({"history": history})
            return

        self._send_json({"error": "Not Found"}, 404)

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = json.loads(self.rfile.read(length).decode('utf-8'))
        user_id = body.get('user_id')

        parsed = urlparse(self.path)

        if parsed.path == '/api/app/chats/switch':
            name = body.get('chat_name')
            if db: db.set(f"user:{user_id}:active_chat", name)
            self._send_json({"ok": True})
            return

        if parsed.path == '/api/app/chats/create':
            name = body.get('chat_name')
            if db:
                db.sadd(f"user:{user_id}:chats_list", name)
                db.set(f"user:{user_id}:active_chat", name)
            self._send_json({"ok": True})
            return

        if parsed.path == '/api/app/chats/rename':
            old_n, new_n = body.get('old_name'), body.get('new_name')
            if db:
                raw_h = db.get(f"user:{user_id}:chat:{old_n}")
                db.delete(f"user:{user_id}:chat:{old_n}")
                db.srem(f"user:{user_id}:chats_list", old_n)
                if raw_h: db.set(f"user:{user_id}:chat:{new_n}", raw_h)
                db.sadd(f"user:{user_id}:chats_list", new_n)
                db.set(f"user:{user_id}:active_chat", new_n)
            self._send_json({"ok": True})
            return

        if parsed.path == '/api/app/chats/delete':
            name = body.get('chat_name')
            if db:
                db.delete(f"user:{user_id}:chat:{name}")
                db.srem(f"user:{user_id}:chats_list", name)
            self._send_json({"ok": True})
            return

        if parsed.path == '/api/app/message':
            chat_name = body.get('chat_name')
            prompt = body.get('prompt')
            model = body.get('model', 'llama-3.3-70b-versatile')

            raw_h = db.get(f"user:{user_id}:chat:{chat_name}") if db else None
            history = json.loads(decode_val(raw_h)) if raw_h else []

            messages = [{"role": m["role"], "content": m["content"]} for m in history]
            messages.append({"role": "user", "content": prompt})

            res = groq.chat.completions.create(model=model, messages=messages)
            answer = res.choices[0].message.content

            history.append({"role": "user", "content": prompt})
            history.append({"role": "assistant", "content": answer})
            if db:
                db.set(f"user:{user_id}:chat:{chat_name}", json.dumps(history[-10:]))

            self._send_json({"answer": answer})
            return

        self._send_json({"error": "Not Found"}, 404)
          
