from pyrogram import Client
from pytgcalls import PyTgCalls
import asyncio

api_id = 123456  # Замени на свой
api_hash = "your_api_hash"
bot_token = "your_bot_token"

app = Client("my_bot", api_id=api_id, api_hash=api_hash, bot_token=bot_token)
pytgcalls = PyTgCalls(app)

@app.on_message()
async def handler(client, message):
    await message.reply("Бот работает!")

async def main():
    await app.start()
    await pytgcalls.start()
    print("Бот запущен")
    await idle()
    await app.stop()

if __name__ == "__main__":
    from pyrogram.idle import idle
    asyncio.run(main())
