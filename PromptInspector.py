import io
import os
import asyncio
from collections import OrderedDict
from discord import ApplicationContext, Intents, Message, Attachment, File, Embed, Member, RawReactionActionEvent
from discord.ext import commands
from dotenv import load_dotenv
from PIL import Image

load_dotenv()

SCAN_LIMIT_BYTES = 10 * 1024**2
SCAN_CHANNELS_FILENAME = "scan_channels.txt"
INTENTS = Intents.default() | Intents.message_content | Intents.members

if os.path.exists(SCAN_CHANNELS_FILENAME):
    with open(SCAN_CHANNELS_FILENAME, 'r') as sf:
        scan_channels = set(int(c) for c in sf.read().split('\n') if c.strip())
else:
    with open(SCAN_CHANNELS_FILENAME, 'w'):
        scan_channels = set()

bot = commands.Bot(intents=INTENTS, command_prefix="pi!")

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
            try:
                _, _, _, a = pixels[x, y]
            except:
                return None
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
        decoded_data = bytearray(int(binary_data[i:i + 8], 2) for i in range(0, len(binary_data), 8)).decode('utf-8', errors='ignore')
        return decoded_data
    return None

def get_params_from_string(param_str):
    output_dict = {}
    parts = param_str.split('Steps: ')
    prompts = parts[0]
    params = 'Steps: ' + parts[1]
    if 'Negative prompt: ' in prompts:
        output_dict['Prompt'] = prompts.split('Negative prompt: ')[0]
        output_dict['Negative Prompt'] = prompts.split('Negative prompt: ')[1]
        if len(output_dict['Negative Prompt']) > 1000:
            output_dict['Negative Prompt'] = output_dict['Negative Prompt'][:1000] + '...'
    else:
        output_dict['Prompt'] = prompts
    if len(output_dict['Prompt']) > 1000:
        output_dict['Prompt'] = output_dict['Prompt'][:1000] + '...'
    params = params.split(', ')
    for param in params:
        try:
            key, value = param.split(': ')
            output_dict[key] = value
        except ValueError:
            pass
    return output_dict

def get_embed(embed_dict: dict, author: Member):
    embed = Embed(title="Here's your image!", color=author.color)
    for key, value in embed_dict.items():
        embed.add_field(name=key, value=value, inline='Prompt' not in key)
    pfp = author.avatar if author.avatar else author.default_avatar_url
    embed.set_footer(text=f'Posted by {author.name}#{author.discriminator}', icon_url=pfp)
    return embed

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

# Get raw list of parameters for every image in requested post
@bot.message_command(name="View Parameters")
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
        await ctx.respond(f"This post contains no image generation data.\nTell {message.author.mention} to install [this extension](<https://github.com/ashen-sensored/sd_webui_stealth_pnginfo>).", ephemeral=True)

@bot.event
async def on_message(message: Message):
    # Scan images in allowed channels
    if message.channel.id in scan_channels:
        for i, attachment in enumerate(a for a in message.attachments if a.filename.lower().endswith(".png") and a.size < SCAN_LIMIT_BYTES):
            metadata = OrderedDict()
            await read_attachment_metadata(i, attachment, metadata)
            if metadata:
                await message.add_reaction('🔎')
                return
    # Owner commands
    if not message.content.startswith('pi!') or not await bot.is_owner(message.author):
        return
    args = message.content.split('pi!')[1].split(' ')
    if args[0] == "channeladd":
        scan_channels.update(int(ch) for ch in args[1:])
        with open(SCAN_CHANNELS_FILENAME, 'w') as f:
            f.write('\n'.join([str(ch) for ch in scan_channels]))
        await message.reply('✅')
    elif args[0] == "channelremove":
        scan_channels.difference_update(int(ch) for ch in args[1:])
        with open(SCAN_CHANNELS_FILENAME, 'w') as f:
            f.write('\n'.join([str(ch) for ch in scan_channels]))
        await message.reply('✅')
    elif args[0] == "channellist":
        with open(SCAN_CHANNELS_FILENAME, 'r') as f:
            ids = f.read().split("\n")
        await message.reply('\n'.join([f'<#{int(i)}>' for i in ids if i.strip()]) or "*None*")


# Send embed of parameters for first valid image in DMs
@bot.event
async def on_raw_reaction_add(ctx: RawReactionActionEvent):
    if ctx.emoji.name == '🔎' and ctx.channel_id in scan_channels and not ctx.member.bot:
        channel = bot.get_channel(ctx.channel_id)
        message = await channel.fetch_message(ctx.message_id)
        if not message:
            return
        attachments = [a for a in message.attachments if a.filename.lower().endswith(".png")]
        if not attachments:
            return
        for i, attachment in enumerate(attachments):
            metadata = OrderedDict()
            await read_attachment_metadata(i, attachment, metadata)
            if metadata:
                embed = get_embed(get_params_from_string(metadata[0]), message.author)
                embed.description = "You can also *right click a message -> Apps -> View Parameters*"
                embed.set_thumbnail(url=attachment.url)
                user_dm = await bot.get_user(ctx.user_id).create_dm()
                await user_dm.send(embed=embed)
                return
        embed = get_embed({}, message.author)
        embed.description = f"This post contains no image generation data.\nTell {message.author.mention} to install [this extension](<https://github.com/ashen-sensored/sd_webui_stealth_pnginfo>)."
        embed.set_thumbnail(url=attachments[0].url)
        user_dm = await bot.get_user(ctx.user_id).create_dm()
        await user_dm.send(embed=embed)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}!")

bot.run(os.environ["BOT_TOKEN"])
