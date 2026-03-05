"use client";

import { useState, useRef, useEffect } from "react";
import { api, type Message } from "@/lib/api";

// Parse <think>...</think> blocks from model output
function parseThinking(content: string): { thinking: string; response: string } {
  const thinkMatch = content.match(/^<think>([\s\S]*?)<\/think>\s*([\s\S]*)$/);
  if (thinkMatch) {
    return { thinking: thinkMatch[1].trim(), response: thinkMatch[2].trim() };
  }
  // Still streaming thinking (no closing tag yet)
  const openThink = content.match(/^<think>([\s\S]*)$/);
  if (openThink) {
    return { thinking: openThink[1].trim(), response: "" };
  }
  return { thinking: "", response: content };
}

function MessageBubble({ msg }: { msg: Message }) {
  const [showThinking, setShowThinking] = useState(false);

  if (msg.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded-lg px-4 py-3 text-sm whitespace-pre-wrap bg-[var(--accent)] text-white">
          {msg.content}
        </div>
      </div>
    );
  }

  const { thinking, response } = parseThinking(msg.content);
  const isStillThinking = thinking && !response && msg.content.includes("<think>") && !msg.content.includes("</think>");

  return (
    <div className="flex justify-start">
      <div className="max-w-[80%] rounded-lg px-4 py-3 text-sm bg-[var(--bg-secondary)] border border-[var(--border)]">
        {thinking && (
          <div className="mb-2">
            <button
              onClick={() => setShowThinking(!showThinking)}
              className="flex items-center gap-1.5 text-xs text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
            >
              <span className={"transform transition-transform " + (showThinking ? "rotate-90" : "")}>▶</span>
              {isStillThinking ? (
                <span className="flex items-center gap-1.5">
                  <span className="inline-block w-1.5 h-1.5 bg-amber-500 rounded-full animate-pulse" />
                  Thinking...
                </span>
              ) : (
                "Thought process"
              )}
            </button>
            {showThinking && (
              <div className="mt-2 pl-3 border-l-2 border-[var(--border)] text-xs text-[var(--text-secondary)] whitespace-pre-wrap">
                {thinking}
              </div>
            )}
          </div>
        )}
        <div className="whitespace-pre-wrap">
          {response || (!thinking && !msg.content && (
            <span className="inline-block w-2 h-4 bg-[var(--text-secondary)] animate-pulse" />
          ))}
        </div>
      </div>
    </div>
  );
}

export function Chat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [model, setModel] = useState("reasoning");
  const [isStreaming, setIsStreaming] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isStreaming) return;

    const userMessage: Message = { role: "user", content: input.trim() };
    const newMessages = [...messages, userMessage];
    setMessages(newMessages);
    setInput("");
    setIsStreaming(true);

    const assistantMessage: Message = { role: "assistant", content: "" };
    setMessages([...newMessages, assistantMessage]);

    try {
      await api.chatStream(
        {
          model,
          messages: newMessages,
          temperature: 0.7,
          max_tokens: 4096,
          stream: true,
        },
        (chunk) => {
          assistantMessage.content += chunk;
          setMessages((prev) => [...prev.slice(0, -1), { ...assistantMessage }]);
        },
      );
    } catch (err) {
      assistantMessage.content = `Error: ${err}`;
      setMessages((prev) => [...prev.slice(0, -1), { ...assistantMessage }]);
    } finally {
      setIsStreaming(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  return (
    <div className="flex flex-col h-screen">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-3 border-b border-[var(--border)]">
        <h2 className="font-semibold">Chat</h2>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5 text-xs text-[var(--text-secondary)]">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
            Local
          </div>
          <select
            value={model}
            onChange={(e) => setModel(e.target.value)}
            className="bg-[var(--bg-tertiary)] border border-[var(--border)] rounded-lg px-3 py-1.5 text-sm"
          >
            <optgroup label="Local (Free)">
              <option value="reasoning">Reasoning (Qwen3 32B)</option>
              <option value="coding">Coding (Qwen3 32B)</option>
              <option value="fast">Fast (Qwen3 14B)</option>
              <option value="local">Ollama (7B)</option>
            </optgroup>
            <optgroup label="Cloud (Paid)">
              <option value="claude">Claude (Anthropic)</option>
              <option value="deepseek">DeepSeek V3</option>
              <option value="gemini">Gemini 2.5 Pro</option>
            </optgroup>
          </select>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        {messages.length === 0 ? (
          <div className="flex items-center justify-center h-full text-[var(--text-secondary)]">
            <div className="text-center">
              <h3 className="text-xl font-semibold mb-2 text-[var(--text-primary)]">
                Athanor
              </h3>
              <p className="mb-4">Local-first AI. Your models, your hardware, your data.</p>
              <div className="flex gap-2 justify-center text-xs">
                <span className="px-2 py-1 rounded bg-[var(--bg-secondary)] border border-[var(--border)]">reasoning</span>
                <span className="px-2 py-1 rounded bg-[var(--bg-secondary)] border border-[var(--border)]">coding</span>
                <span className="px-2 py-1 rounded bg-[var(--bg-secondary)] border border-[var(--border)]">fast</span>
              </div>
            </div>
          </div>
        ) : (
          messages.map((msg, i) => <MessageBubble key={i} msg={msg} />)
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <form onSubmit={handleSubmit} className="px-6 py-4 border-t border-[var(--border)]">
        <div className="flex gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Type a message... (Enter to send, Shift+Enter for newline)"
            rows={1}
            className="flex-1 bg-[var(--bg-secondary)] border border-[var(--border)] rounded-lg px-4 py-3 text-sm resize-none focus:outline-none focus:border-[var(--accent)]"
          />
          <button
            type="submit"
            disabled={!input.trim() || isStreaming}
            className="px-6 py-3 bg-[var(--accent)] hover:bg-[var(--accent-hover)] disabled:opacity-50 disabled:cursor-not-allowed rounded-lg text-sm font-medium transition-colors"
          >
            {isStreaming ? "..." : "Send"}
          </button>
        </div>
      </form>
    </div>
  );
}
