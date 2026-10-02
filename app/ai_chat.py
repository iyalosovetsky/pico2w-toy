"""Chat with the local LLM (llama.cpp, OpenAI-compatible API) on the 1.44" LCD console.

Runs on tty1 (25x18 chars with the 5x7 font). Type with a USB keyboard,
Alt+Shift switches US/UA layout.

Commands: /new - new conversation, /think - toggle model reasoning,
          /quit or Ctrl+D - back to the menu. Ctrl+C stops a running answer.
"""
import json
import os
import readline  # noqa: F401  (line editing + history for input())
import shutil
import sys
import urllib.request

# llama.cpp server (or any OpenAI-compatible API); set in /etc/default/lcd-ai-chat
AI_URL = os.environ.get("AI_URL", "http://127.0.0.1:8080")
SYSTEM_PROMPT = (
    "Ти помічник на крихітному екрані 25x18 символів. "
    "Відповідай дуже коротко: 1-3 речення, без markdown, списків і таблиць. "
    "Відповідай мовою користувача."
)
MAX_HISTORY = 20  # messages kept besides the system prompt

YELLOW, GREY, CYAN, RED, RESET = "\033[33m", "\033[90m", "\033[36m", "\033[31m", "\033[0m"


class Wrapper:
    """Word-wraps streamed text to the terminal width."""

    def __init__(self, width):
        self.width = width
        self.col = 0
        self.word = ""

    def feed(self, text):
        for ch in text:
            if ch == "\n":
                self._flush_word()
                sys.stdout.write("\n")
                self.col = 0
            elif ch == " ":
                self._flush_word()
                if 0 < self.col < self.width:
                    sys.stdout.write(" ")
                    self.col += 1
            else:
                self.word += ch
                if len(self.word) >= self.width:  # very long word: hard break
                    self._flush_word()
        sys.stdout.flush()

    def _flush_word(self):
        if not self.word:
            return
        if self.col + len(self.word) > self.width:
            sys.stdout.write("\n")
            self.col = 0
        sys.stdout.write(self.word)
        self.col += len(self.word)
        if self.col >= self.width:
            self.col = 0  # the terminal wrapped the line itself
        self.word = ""

    def finish(self):
        self._flush_word()
        if self.col:
            sys.stdout.write("\n")
        self.col = 0
        sys.stdout.flush()


def stream_chat(messages, think):
    body = json.dumps({
        "messages": messages,
        "stream": True,
        "chat_template_kwargs": {"enable_thinking": think},
    }).encode()
    req = urllib.request.Request(AI_URL + "/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                return
            delta = json.loads(data)["choices"][0].get("delta", {})
            if delta.get("reasoning_content"):
                yield "think", delta["reasoning_content"]
            if delta.get("content"):
                yield "text", delta["content"]


def answer(messages, think, width):
    """Stream one reply to the screen; returns the reply text (possibly partial)."""
    wrap = Wrapper(width)
    reply, in_think_tag, thinking_shown = "", False, False
    sys.stdout.write(CYAN)
    try:
        for kind, chunk in stream_chat(messages, think):
            if kind == "think" or in_think_tag or "<think>" in chunk:
                # reasoning: show a single "thinking" marker instead of the text
                if "<think>" in chunk:
                    in_think_tag = True
                if "</think>" in chunk:
                    in_think_tag = False
                    chunk = chunk.split("</think>", 1)[1]
                    if not chunk:
                        continue
                else:
                    if not thinking_shown:
                        sys.stdout.write(GREY + "(думаю...)" + CYAN + "\n")
                        sys.stdout.flush()
                        thinking_shown = True
                    continue
            if not reply:
                chunk = chunk.lstrip()
            reply += chunk
            wrap.feed(chunk)
    except KeyboardInterrupt:
        wrap.finish()
        sys.stdout.write(GREY + "[зупинено]" + RESET + "\n")
        return reply
    except Exception as e:  # network / server errors
        wrap.finish()
        sys.stdout.write(RED + "Помилка: " + str(e)[:60] + RESET + "\n")
        return None
    wrap.finish()
    sys.stdout.write(RESET)
    return reply


def main():
    width = shutil.get_terminal_size((25, 18)).columns
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    think = False
    sys.stdout.write("\033[2J\033[H" + YELLOW + "AI chat\n" + GREY + "/new /think /quit\n" + RESET)
    while True:
        try:
            # \001/\002 tell readline the colour codes take no space; without
            # them it miscounts the prompt width and long lines do not wrap
            text = input("\001" + YELLOW + "\002> \001" + RESET + "\002").strip()
        except KeyboardInterrupt:
            print()
            continue
        except EOFError:
            break
        if not text:
            continue
        if text in ("/quit", "/exit", "/q"):
            break
        if text == "/new":
            messages = messages[:1]
            sys.stdout.write("\033[2J\033[H" + GREY + "Нова розмова\n" + RESET)
            continue
        if text == "/think":
            think = not think
            print(GREY + "Міркування: " + ("увімк." if think else "вимк.") + RESET)
            continue
        messages.append({"role": "user", "content": text})
        reply = answer(messages, think, width)
        if reply:
            messages.append({"role": "assistant", "content": reply})
        else:
            messages.pop()  # failed request: forget the question
        if len(messages) > MAX_HISTORY + 1:
            messages = messages[:1] + messages[-MAX_HISTORY:]


if __name__ == "__main__":
    main()
