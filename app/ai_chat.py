"""Chat with an LLM (llama.cpp or any OpenAI-compatible API) on the LCD text console (tty7).

HAT: 21x12 chars (6x10 font), a USB keyboard, Alt+Shift switches US/UA.
PicoCalc: 40x20 chars (Terminus Bold 8x16), CapsLock switches US/UA.

Providers (servers) are in ~/.config/lcdtoy/ai-chat.json, made on the first start:
  {"provider": "zen4",
   "providers": {"zen4": {"url": "http://10.80.39.14:8003"},
                 "gpt":  {"url": "https://gpt.ibotz.space", "token": "sk-...", "model": ""}}}
url - the server (its /v1/chat/completions is used), token - sent as "Authorization: Bearer",
model - for servers that need one (llama.cpp serves its own model whatever is asked).

Commands: /new - new conversation, /think - toggle model reasoning,
          /provider - list the providers, /provider NAME - switch (remembered),
          /quit or Ctrl+D - back to the menu. Ctrl+C stops a running answer.
"""
import json
import os
import readline  # noqa: F401  (line editing + history for input())
import shutil
import sys
import urllib.error
import urllib.request

CONFIG = os.path.expanduser("~/.config/lcdtoy/ai-chat.json")
# the first config's default provider: AI_URL from /etc/default/lcd-ai-chat (older installs)
DEFAULT_URL = os.environ.get("AI_URL", "http://10.80.39.14:8003")
SYSTEM_PROMPT = (
    "Ти помічник на крихітному екрані {w}x{h} символів. "
    "Відповідай дуже коротко: 1-3 речення, без markdown, списків і таблиць. "
    "Відповідай мовою користувача."
)
MAX_HISTORY = 20  # messages kept besides the system prompt

YELLOW, GREY, CYAN, RED, RESET = "\033[93m", "\033[37m", "\033[96m", "\033[91m", "\033[0m"
# the Linux console's VGA palette is dim on a small LCD: brighter colors while the chat runs
# (\033]PNRRGGBB sets color N; \033]R restores the default palette)
PALETTE = {7: "ffffff", 15: "ffffff", 11: "ffe040", 14: "70f0ff", 9: "ff7060", 8: "b0b0b0"}


def load_config():
    """The config (made with the AI_URL server as "zen4" plus a gpt.ibotz.space template)."""
    try:
        with open(CONFIG, encoding="utf-8") as f:
            cfg = json.load(f)
        if cfg.get("providers"):
            return cfg
    except (OSError, ValueError):
        pass
    cfg = {"provider": "zen4",
           "providers": {"zen4": {"url": DEFAULT_URL, "token": "", "model": ""},
                         "gpt": {"url": "https://gpt.ibotz.space", "token": "", "model": ""}}}
    save_config(cfg)
    return cfg


def save_config(cfg):
    try:
        os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
        fd = os.open(CONFIG, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # tokens inside
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
            f.write("\n")
    except OSError:
        pass


def provider(cfg):
    name = cfg.get("provider")
    if name not in cfg["providers"]:
        name = next(iter(cfg["providers"]))
    return name, cfg["providers"][name]


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


def stream_chat(prov, messages, think):
    body = {"messages": messages, "stream": True,
            "chat_template_kwargs": {"enable_thinking": think}}  # llama.cpp: Qwen's reasoning
    if prov.get("model"):
        body["model"] = prov["model"]
    headers = {"Content-Type": "application/json"}
    if prov.get("token"):
        headers["Authorization"] = "Bearer " + prov["token"]
    url = prov["url"].rstrip("/")
    if not url.endswith("/v1"):
        url += "/v1"
    req = urllib.request.Request(url + "/chat/completions", data=json.dumps(body).encode(),
                                 headers=headers)
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


def answer(prov, messages, think, width):
    """Stream one reply to the screen; returns the reply text (possibly partial)."""
    wrap = Wrapper(width)
    reply, in_think_tag, thinking_shown = "", False, False
    sys.stdout.write(CYAN)
    try:
        for kind, chunk in stream_chat(prov, messages, think):
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
    except urllib.error.HTTPError as e:
        wrap.finish()
        hint = " - потрібен token у " + CONFIG.replace(os.path.expanduser("~"), "~") \
            if e.code in (401, 403) else ""
        sys.stdout.write(RED + "Помилка HTTP %d%s" % (e.code, hint) + RESET + "\n")
        return None
    except Exception as e:  # network / server errors
        wrap.finish()
        sys.stdout.write(RED + "Помилка: " + str(e)[:80] + RESET + "\n")
        return None
    wrap.finish()
    sys.stdout.write(RESET)
    return reply


def show_providers(cfg):
    current, _ = provider(cfg)
    for name, prov in cfg["providers"].items():
        mark = "*" if name == current else " "
        key = "" if prov.get("token") else " (без токена)"
        print(GREY + "%s %s - %s%s" % (mark, name, prov.get("url", "?"), key) + RESET)
    print(GREY + "/provider НАЗВА - перемкнути" + RESET)


def main():
    size = shutil.get_terminal_size((25, 18))
    width = size.columns
    cfg = load_config()
    name, prov = provider(cfg)
    system = {"role": "system", "content": SYSTEM_PROMPT.format(w=size.columns, h=size.lines)}
    messages = [system]
    think = False
    sys.stdout.write("".join("\033]P%X%s" % (n, rgb) for n, rgb in PALETTE.items()))
    sys.stdout.write("\033[2J\033[H" + YELLOW + "AI chat: " + name + "\n" + GREY
                     + "/new /think /provider /quit\n" + RESET)
    try:
        chat(cfg, name, prov, messages, think, width)
    finally:
        sys.stdout.write("\033]R")  # the default palette back
        sys.stdout.flush()


def chat(cfg, name, prov, messages, think, width):
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
            sys.stdout.write("\033[2J\033[H" + GREY + "Нова розмова (" + name + ")\n" + RESET)
            continue
        if text == "/think":
            think = not think
            print(GREY + "Міркування: " + ("увімк." if think else "вимк.") + RESET)
            continue
        if text == "/provider" or text.startswith("/provider "):
            want = text[len("/provider"):].strip()
            if not want:
                show_providers(cfg)
            elif want not in cfg["providers"]:
                print(RED + "Немає такого: " + want + RESET)
                show_providers(cfg)
            else:
                cfg["provider"] = want
                save_config(cfg)
                name, prov = provider(cfg)
                messages = messages[:1]
                print(YELLOW + "Провайдер: " + name + " - нова розмова" + RESET)
            continue
        messages.append({"role": "user", "content": text})
        reply = answer(prov, messages, think, width)
        if reply:
            messages.append({"role": "assistant", "content": reply})
        else:
            messages.pop()  # failed request: forget the question
        if len(messages) > MAX_HISTORY + 1:
            messages = messages[:1] + messages[-MAX_HISTORY:]


if __name__ == "__main__":
    main()
