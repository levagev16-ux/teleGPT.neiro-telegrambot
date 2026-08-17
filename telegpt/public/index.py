<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
  <title>AI Mini App</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    body { background-color: var(--tg-theme-bg-color, #0f172a); color: var(--tg-theme-text-color, #ffffff); }
    .chat-bubble-user { background-color: var(--tg-theme-button-color, #2563eb); color: var(--tg-theme-button-text-color, #ffffff); }
  </style>
</head>
<body class="h-screen flex flex-col font-sans overflow-hidden">

  <!-- ШАПКА -->
  <header class="flex items-center justify-between p-3 bg-slate-800 border-b border-slate-700 relative z-20">
    <div class="flex items-center gap-2">
      <span class="text-xl">💬</span>
      <span id="current-chat-title" class="font-semibold text-base truncate max-w-[180px]">Загрузка...</span>
    </div>
    
    <button id="btn-toggle-menu" class="p-2 hover:bg-slate-700 rounded-lg transition text-slate-300">
      <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 5v.01M12 12v.01M12 19v.01M12 6a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2z"></path></svg>
    </button>
  </header>

  <!-- ВЫПАДАЮЩЕЕ МЕНЮ С ЧАТАМИ И 3 ТОЧКАМИ -->
  <div id="chats-dropdown" class="hidden absolute top-14 right-2 w-80 bg-slate-800 border border-slate-700 rounded-2xl shadow-2xl z-30 p-3 space-y-3">
    <button id="btn-create-chat" class="w-full flex items-center justify-center gap-2 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-xl font-medium transition text-sm">
      ➕ Новый чат
    </button>

    <div id="chats-list-container" class="max-h-60 overflow-y-auto space-y-1 pr-1">
      <!-- Список чатов загрузится сюда -->
    </div>
  </div>

  <!-- ОБЛАСТЬ СООБЩЕНИЙ -->
  <main id="chat-messages" class="flex-1 overflow-y-auto p-4 space-y-3">
    <div class="text-center text-xs text-slate-400 my-4">Выберите чат или отправьте сообщение</div>
  </main>

  <!-- ВВОД СООБЩЕНИЯ И ВЫБОР МОДЕЛЕЙ -->
  <footer class="p-3 bg-slate-800 border-t border-slate-700 flex items-center gap-2 z-10">
    <select id="model-select" class="bg-slate-900 border border-slate-700 text-white text-xs rounded-xl px-2 py-2.5 focus:outline-none">
      <option value="llama-3.3-70b-versatile">🤖 Llama 3.3</option>
      <option value="llama-3.1-8b-instant">⚡ Llama Instant</option>
      <option value="openai/gpt-oss-120b">🧠 GPT OSS</option>
    </select>

    <input id="message-input" type="text" placeholder="Напишите сообщение..." class="flex-1 bg-slate-900 border border-slate-700 rounded-xl px-3 py-2 text-sm text-white focus:outline-none" />

    <button id="btn-send" class="p-2.5 bg-blue-600 hover:bg-blue-500 rounded-xl text-white transition">
      <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"></path></svg>
    </button>
  </footer>

  <script>
    const tg = window.Telegram.WebApp;
    tg.expand();

    const userId = tg.initDataUnsafe?.user?.id || 12345678;
    let activeChat = "Основной чат";
    let allChats = [];

    const chatsDropdown = document.getElementById("chats-dropdown");
    const chatsContainer = document.getElementById("chats-list-container");
    const messagesContainer = document.getElementById("chat-messages");
    const messageInput = document.getElementById("message-input");

    document.getElementById("btn-toggle-menu").onclick = () => chatsDropdown.classList.toggle("hidden");

    async function loadChats() {
      const res = await fetch(`/api/app/chats?user_id=${userId}`);
      const data = await res.json();
      allChats = data.chats || ["Основной чат"];
      activeChat = data.active || allChats[0];
      document.getElementById("current-chat-title").innerText = activeChat;
      renderChatsList(allChats);
      loadHistory();
    }

    function renderChatsList(chats) {
      chatsContainer.innerHTML = "";
      chats.forEach(chat => {
        const item = document.createElement("div");
        item.className = `flex items-center justify-between p-2 rounded-xl text-xs transition ${chat === activeChat ? 'bg-slate-700 font-bold' : 'hover:bg-slate-700/50'}`;
        
        item.innerHTML = `
          <span class="truncate flex-1 cursor-pointer mr-2" onclick="switchChat('${chat}')">💬 ${chat}</span>
          <div class="relative">
            <button onclick="toggleChatActions(event, '${chat}')" class="p-1 text-slate-400 hover:text-white font-bold">⋮</button>
            <div id="actions-${chat}" class="hidden absolute right-0 mt-1 w-32 bg-slate-900 border border-slate-700 rounded-lg shadow-lg z-40">
              <button onclick="renameChat('${chat}')" class="w-full text-left px-3 py-1.5 hover:bg-slate-800 text-slate-200">✏️ Имя</button>
              <button onclick="deleteChat('${chat}')" class="w-full text-left px-3 py-1.5 hover:bg-slate-800 text-red-400">🗑 Удалить</button>
            </div>
          </div>
        `;
        chatsContainer.appendChild(item);
      });
    }

    function toggleChatActions(e, chat) {
      e.stopPropagation();
      document.querySelectorAll('[id^="actions-"]').forEach(el => el.classList.add('hidden'));
      document.getElementById(`actions-${chat}`).classList.toggle('hidden');
    }

    async function switchChat(chat) {
      activeChat = chat;
      chatsDropdown.classList.add("hidden");
      document.getElementById("current-chat-title").innerText = activeChat;
      await fetch('/api/app/chats/switch', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ user_id: userId, chat_name: chat })});
      loadChats();
    }

    async function renameChat(oldName) {
      const newName = prompt("Новое название чата:", oldName);
      if (!newName || newName === oldName) return;
      await fetch('/api/app/chats/rename', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ user_id: userId, old_name: oldName, new_name: newName })});
      loadChats();
    }

    async function deleteChat(chat) {
      if (!confirm(`Удалить чат "${chat}"?`)) return;
      await fetch('/api/app/chats/delete', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ user_id: userId, chat_name: chat })});
      loadChats();
    }

    document.getElementById("btn-create-chat").onclick = async () => {
      const chatName = prompt("Название нового чата:", `Чат ${allChats.length + 1}`);
      if (!chatName) return;
      await fetch('/api/app/chats/create', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ user_id: userId, chat_name: chatName })});
      chatsDropdown.classList.add("hidden");
      loadChats();
    };

    async function loadHistory() {
      messagesContainer.innerHTML = "";
      const res = await fetch(`/api/app/history?user_id=${userId}&chat_name=${encodeURIComponent(activeChat)}`);
      const data = await res.json();
      (data.history || []).forEach(m => appendMessage(m.role, m.content));
    }

    function appendMessage(role, text) {
      const msgDiv = document.createElement("div");
      msgDiv.className = role === 'user' ? "flex justify-end" : "flex justify-start";
      msgDiv.innerHTML = `
        <div class="${role === 'user' ? 'chat-bubble-user rounded-2xl rounded-tr-none' : 'bg-slate-800 text-slate-200 rounded-2xl rounded-tl-none'} p-3 max-w-[80%] text-sm">
          ${text}
        </div>
      `;
      messagesContainer.appendChild(msgDiv);
      messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    document.getElementById("btn-send").onclick = async () => {
      const text = messageInput.value.trim();
      if (!text) return;

      appendMessage('user', text);
      messageInput.value = "";

      const model = document.getElementById("model-select").value;
      const res = await fetch('/api/app/message', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ user_id: userId, chat_name: activeChat, prompt: text, model: model })
      });
      const data = await res.json();
      appendMessage('assistant', data.answer);
    };

    loadChats();
  </script>
</body>
</html>

