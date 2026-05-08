/* Shared chat rendering helpers used by Admin + Team copilot pages. */
(function initSharedChat(global) {
  function getChat(chatId) {
    return document.getElementById(chatId);
  }

  function clearEmptyState(chatId) {
    const chat = getChat(chatId);
    const card = chat?.querySelector(".chat-empty-state");
    if (card) card.remove();
  }

  function ensureEmptyState(chatId) {
    const chat = getChat(chatId);
    if (!chat) return;
    const hasMessages = chat.querySelector(".chat-message-row, .copilot-answer-block, .copilot-typing-row");
    if (hasMessages) {
      clearEmptyState(chatId);
      return;
    }
    if (chat.querySelector(".chat-empty-state")) return;
    const card = document.createElement("article");
    card.className = "chat-empty-state";
    card.innerHTML = `
      <strong>Start a finance conversation</strong>
      Ask about overdue invoices, top balances, high-risk customers, or region trends.
    `;
    chat.appendChild(card);
  }

  function appendBubble(chatId, role, text) {
    const chat = getChat(chatId);
    if (!chat) return null;
    clearEmptyState(chatId);
    const row = document.createElement("div");
    row.className = `chat-message-row ${role} chat-enter`;
    if (role === "bot") {
      const avatar = document.createElement("span");
      avatar.className = "copilot-avatar small";
      avatar.setAttribute("aria-hidden", "true");
      avatar.textContent = "✦";
      const div = document.createElement("div");
      div.className = `chat-bubble ${role}`;
      div.textContent = text;
      row.append(avatar, div);
    } else {
      const div = document.createElement("div");
      div.className = `chat-bubble ${role}`;
      div.textContent = text;
      row.appendChild(div);
    }
    chat.appendChild(row);
    const ts = document.createElement("span");
    ts.className = "chat-timestamp";
    ts.textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    row.appendChild(ts);
    chat.scrollTop = chat.scrollHeight;
    return row;
  }

  function showTyping(chatId) {
    const chat = getChat(chatId);
    if (!chat) return null;
    clearEmptyState(chatId);
    const row = document.createElement("div");
    row.className = "copilot-typing-row chat-enter";
    const avatar = document.createElement("span");
    avatar.className = "copilot-avatar";
    avatar.textContent = "✦";
    const dots = document.createElement("div");
    dots.className = "typing-dots";
    for (let i = 0; i < 3; i += 1) dots.appendChild(document.createElement("span"));
    const label = document.createElement("span");
    label.className = "typing-label";
    label.textContent = "Analyzing financial data...";
    row.append(avatar, dots, label);
    chat.appendChild(row);
    chat.scrollTop = chat.scrollHeight;
    return row;
  }

  global.CopilotChat = {
    clearEmptyState,
    ensureEmptyState,
    appendBubble,
    showTyping,
  };
})(window);
