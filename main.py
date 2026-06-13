import os
import json
import httpx
from fastapi import FastAPI, Request
from openai import OpenAI
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

app = FastAPI()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

client = OpenAI(
    api_key=GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1"
)

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

DB_FILE = "memory.json"
system_prompt_cache = None


def get_system_prompt():
    global system_prompt_cache
    if system_prompt_cache is None:
        result = supabase.table("config").select("value").eq("key", "system_prompt").single().execute()
        system_prompt_cache = result.data["value"]
    return system_prompt_cache


def load_memory():
    if not os.path.exists(DB_FILE):
        return {}
    with open(DB_FILE, "r") as f:
        return json.load(f)


def save_memory(memory):
    with open(DB_FILE, "w") as f:
        json.dump(memory, f, indent=2)


def get_context(chat_id):
    memory = load_memory()
    return memory.get(str(chat_id), [])


def add_message(chat_id, role, text):
    memory = load_memory()
    chat_id = str(chat_id)
    if chat_id not in memory:
        memory[chat_id] = []
    memory[chat_id].append({"role": role, "text": text})
    save_memory(memory)


async def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    async with httpx.AsyncClient() as http:
        await http.post(url, json={"chat_id": chat_id, "text": text})


@app.on_event("startup")
async def set_webhook():
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook"
    async with httpx.AsyncClient() as http:
        r = await http.post(url, json={"url": f"{WEBHOOK_URL}/webhook"})
        print("Webhook set:", r.json())


def ask_llm(chat_id, user_text):
    history = get_context(chat_id)
    messages = [
        {
            "role": "system",
            "content": get_system_prompt()
        }
    ]

    for msg in history[-20:]:
        if msg["role"] in ["user", "assistant"]:
            messages.append({
                "role": msg["role"],
                "content": msg["text"]
            })

    messages.append({
        "role": "user",
        "content": user_text
    })

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages
    )

    return response.choices[0].message.content


@app.post("/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    message = data.get("message")
    if not message:
        return {"ok": True}

    chat_id = message["chat"]["id"]
    user_text = message.get("text", "")

    if not user_text:
        await send_message(chat_id, "I can only handle text messages for now.")
        return {"ok": True}

    if user_text == "/start":
        await send_message(chat_id, "Hey! I'm your Hashimi auto spare parts sales agent. How may I help you.")
        return {"ok": True}

    if user_text == "/reset":
        memory = load_memory()
        memory[str(chat_id)] = []
        save_memory(memory)
        await send_message(chat_id, "Memory cleared!")
        return {"ok": True}

    add_message(chat_id, "user", user_text)
    reply = ask_llm(chat_id, user_text)
    add_message(chat_id, "assistant", reply)
    await send_message(chat_id, reply)
    return {"ok": True}