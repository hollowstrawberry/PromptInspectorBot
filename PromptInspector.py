import io
import os
from discord import Intents, Message, ApplicationContext, File
from discord.ext import commands
from dotenv import load_dotenv
from PIL import Image

load_dotenv()

intents = Intents.default() | Intents.message_content | Intents.members
client = commands.Bot(intents=intents)

@client.message_command(name="View Parameters")
async def message_command(ctx: ApplicationContext, message: Message):
    attachments = [a for a in message.attachments if a.content_type.startswith("image/")]
    if not attachments:
        await ctx.respond(ephemeral=True)
        return
    metadata = []
    for attachment in attachments:
        image_data = await attachment.read()
        try:
            with Image.open(io.BytesIO(image_data)) as img:
                metadata.append(img.info['parameters'])
        except:
            pass
    if metadata and all(m for m in metadata):
        response = "\n\n".join(metadata)
        if len(response) < 1980:
            await ctx.respond(f"```yaml\n{response}```", ephemeral=True)
        else:
            filename = f"{message.id}.yaml"
            with open(filename, "w") as f:
                f.write(response)
            with open(filename, "rb") as f:
                await ctx.respond(file=File(f, "parameters.yaml"), ephemeral=True)
            os.remove(filename)
    else:
        await ctx.respond(f"This post contains no image metadata.", ephemeral=True)

@client.event
async def on_ready():
    print(f"Logged in as {client.user}!")

client.run(os.environ["BOT_TOKEN"])
