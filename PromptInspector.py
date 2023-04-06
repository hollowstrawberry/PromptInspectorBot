import io
import os
import asyncio
from collections import OrderedDict
from discord import Intents, Message, ApplicationContext, Attachment, File
from discord.ext import commands
from dotenv import load_dotenv
from PIL import Image

load_dotenv()

intents = Intents.default() | Intents.message_content | Intents.members
client = commands.Bot(intents=intents)

def read_info_from_image_stealth(image):
    width, height = image.size
    pixels = image.load()
    binary_data = ''
    buffer = ''
    index = 0
    sig_confirmed = False
    confirming_signature = True
    reading_param_len = False
    reading_param = False
    read_end = False
    for x in range(width):
        for y in range(height):
            _, _, _, a = pixels[x, y]
            buffer += str(a & 1)
            if confirming_signature:
                if index == len('stealth_pnginfo') * 8 - 1:
                    if buffer == ''.join(format(byte, '08b') for byte in 'stealth_pnginfo'.encode('utf-8')):
                        confirming_signature = False
                        sig_confirmed = True
                        reading_param_len = True
                        buffer = ''
                        index = 0
                    else:
                        read_end = True
                        break
            elif reading_param_len:
                if index == 32:
                    param_len = int(buffer, 2)
                    reading_param_len = False
                    reading_param = True
                    buffer = ''
                    index = 0
            elif reading_param:
                if index == param_len:
                    binary_data = buffer
                    read_end = True
                    break
            else:
                # impossible
                read_end = True
                break

            index += 1
        if read_end:
            break
    if sig_confirmed and binary_data != '':
        # Convert binary string to UTF-8 encoded text
        decoded_data = bytearray(int(binary_data[i:i + 8], 2) for i in range(0, len(binary_data), 8)).decode('utf-8',errors='ignore')
        return decoded_data
    return None

async def read_attachment_metadata(i: int, attachment: Attachment, metadata: OrderedDict):
    print("Downloading", i)
    try:
        image_data = await attachment.read()
        with Image.open(io.BytesIO(image_data)) as img:
            info = read_info_from_image_stealth(img)
            if info and "Steps" in info:
                metadata[i] = info
    except Exception as error:
        print(f"{type(error).__name__}: {error}")
    else:
        print("Downloaded", i)

@client.message_command(name="View Parameters")
async def message_command(ctx: ApplicationContext, message: Message):
    attachments = [a for a in message.attachments if a.filename.lower().endswith(".png")]
    if not attachments:
        await ctx.respond("This post contains no images.", ephemeral=True)
        return
    await ctx.defer(ephemeral=True)
    metadata = OrderedDict()
    tasks = [read_attachment_metadata(i, attachment, metadata) for i, attachment in enumerate(attachments)]
    await asyncio.gather(*tasks)
    if metadata:
        response = "\n\n".join(metadata.values())
        if len(response) < 1980:
            await ctx.respond(f"```yaml\n{response}```", ephemeral=True)
        else:
            with io.StringIO() as f:
                f.write(response)
                f.seek(0)
                await ctx.respond(file=File(f, "parameters.yaml"), ephemeral=True)
    else:
        await ctx.respond("This post contains no image generation data.\nTell the author to install [this extension](<https://github.com/ashen-sensored/sd_webui_stealth_pnginfo>).", ephemeral=True)

@client.event
async def on_ready():
    print(f"Logged in as {client.user}!")

client.run(os.environ["BOT_TOKEN"])
