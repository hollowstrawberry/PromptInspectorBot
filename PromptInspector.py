import gzip
import io
import os
import asyncio
import discord
from typing import List
from collections import OrderedDict
from discord import Intents, Message, Member, Embed
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

bot = commands.Bot(intents=INTENTS, command_prefix="pi!", auto_sync_commands=False)


def read_info_from_image_stealth(image):
    # trying to read stealth pnginfo
    width, height = image.size
    pixels = image.load()

    has_alpha = True if image.mode == 'RGBA' else False
    mode = None
    compressed = False
    binary_data = ''
    buffer_a = ''
    buffer_rgb = ''
    index_a = 0
    index_rgb = 0
    sig_confirmed = False
    confirming_signature = True
    reading_param_len = False
    reading_param = False
    read_end = False
    for x in range(width):
        for y in range(height):
            if has_alpha:
                r, g, b, a = pixels[x, y]
                buffer_a += str(a & 1)
                index_a += 1
            else:
                r, g, b = pixels[x, y]
            buffer_rgb += str(r & 1)
            buffer_rgb += str(g & 1)
            buffer_rgb += str(b & 1)
            index_rgb += 3
            if confirming_signature:
                if index_a == len('stealth_pnginfo') * 8:
                    decoded_sig = bytearray(int(buffer_a[i:i + 8], 2) for i in
                                            range(0, len(buffer_a), 8)).decode('utf-8', errors='ignore')
                    if decoded_sig in {'stealth_pnginfo', 'stealth_pngcomp'}:
                        confirming_signature = False
                        sig_confirmed = True
                        reading_param_len = True
                        mode = 'alpha'
                        if decoded_sig == 'stealth_pngcomp':
                            compressed = True
                        buffer_a = ''
                        index_a = 0
                    else:
                        read_end = True
                        break
                elif index_rgb == len('stealth_pnginfo') * 8:
                    decoded_sig = bytearray(int(buffer_rgb[i:i + 8], 2) for i in
                                            range(0, len(buffer_rgb), 8)).decode('utf-8', errors='ignore')
                    if decoded_sig in {'stealth_rgbinfo', 'stealth_rgbcomp'}:
                        confirming_signature = False
                        sig_confirmed = True
                        reading_param_len = True
                        mode = 'rgb'
                        if decoded_sig == 'stealth_rgbcomp':
                            compressed = True
                        buffer_rgb = ''
                        index_rgb = 0
            elif reading_param_len:
                if mode == 'alpha':
                    if index_a == 32:
                        param_len = int(buffer_a, 2)
                        reading_param_len = False
                        reading_param = True
                        buffer_a = ''
                        index_a = 0
                else:
                    if index_rgb == 33:
                        pop = buffer_rgb[-1]
                        buffer_rgb = buffer_rgb[:-1]
                        param_len = int(buffer_rgb, 2)
                        reading_param_len = False
                        reading_param = True
                        buffer_rgb = pop
                        index_rgb = 1
            elif reading_param:
                if mode == 'alpha':
                    if index_a == param_len:
                        binary_data = buffer_a
                        read_end = True
                        break
                else:
                    if index_rgb >= param_len:
                        diff = param_len - index_rgb
                        if diff < 0:
                            buffer_rgb = buffer_rgb[:diff]
                        binary_data = buffer_rgb
                        read_end = True
                        break
            else:
                # impossible
                read_end = True
                break
        if read_end:
            break
    if sig_confirmed and binary_data != '':
        # Convert binary string to UTF-8 encoded text
        byte_data = bytearray(int(binary_data[i:i + 8], 2) for i in range(0, len(binary_data), 8))
        try:
            if compressed:
                decoded_data = gzip.decompress(bytes(byte_data)).decode('utf-8')
            else:
                decoded_data = byte_data.decode('utf-8', errors='ignore')
            return decoded_data
        except:
            pass
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


async def read_attachment_metadata(i: int, attachment: discord.Attachment, metadata: OrderedDict):
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


@bot.message_command(name="View Parameters")
async def message_command(ctx: discord.ApplicationContext, message: Message):
    """Get raw list of parameters for every image in this post."""
    attachments = [a for a in message.attachments if a.filename.lower().endswith(".png")]
    if not attachments:
        await ctx.respond("This post contains no images.", ephemeral=True)
        return
    await ctx.defer(ephemeral=True)
    metadata = OrderedDict()
    tasks = [read_attachment_metadata(i, attachment, metadata) for i, attachment in enumerate(attachments)]
    await asyncio.gather(*tasks)
    if not metadata:
        await ctx.respond(f"This post contains no image generation data.\nTell {message.author.mention} to install [this extension](<https://github.com/ashen-sensored/sd_webui_stealth_pnginfo>).", ephemeral=True)
        return
    response = "\n\n".join(metadata.values())
    if len(response) < 1980:
        await ctx.respond(f"```yaml\n{response}```", ephemeral=True)
    else:
        with io.StringIO() as f:
            f.write(response)
            f.seek(0)
            await ctx.respond(file=discord.File(f, "parameters.yaml"), ephemeral=True)


@bot.event
async def on_message(message: Message):
    # Scan images in allowed channels
    if message.channel.id in scan_channels:
        attachments = [a for a in message.attachments if a.filename.lower().endswith(".png") and a.size < SCAN_LIMIT_BYTES]
        for i, attachment in enumerate(attachments):
            metadata = OrderedDict()
            await read_attachment_metadata(i, attachment, metadata)
            if metadata:
                await message.add_reaction('🔎')
                return
    await bot.process_commands(message)


@bot.event
async def on_raw_reaction_add(ctx: discord.RawReactionActionEvent):
    """Send image metadata in reacted post to user DMs"""
    if ctx.emoji.name != '🔎' or ctx.channel_id not in scan_channels or ctx.member.bot:
        return
    channel = bot.get_channel(ctx.channel_id)
    message = await channel.fetch_message(ctx.message_id)
    if not message:
        return
    attachments = [a for a in message.attachments if a.filename.lower().endswith(".png")]
    if not attachments:
        return
    metadata = OrderedDict()
    tasks = [read_attachment_metadata(i, attachment, metadata) for i, attachment in enumerate(attachments)]
    await asyncio.gather(*tasks)
    user_dm = await bot.get_user(ctx.user_id).create_dm()
    if not metadata:
        embed = get_embed({}, message.author)
        embed.description = f"This post contains no image generation data.\nTell {message.author.mention} to install [this extension](<https://github.com/ashen-sensored/sd_webui_stealth_pnginfo>)."
        embed.set_thumbnail(url=attachments[0].url)
        await user_dm.send(embed=embed)
        return
    for attachment, data in [(attachments[i], data) for i, data in metadata.items()]:
        embed = get_embed(get_params_from_string(data), message.author)
        embed.set_thumbnail(url=attachment.url)
        await user_dm.send(embed=embed)


@bot.group(invoke_without_command=True)
@commands.is_owner()
async def channel(ctx: commands.Context):
    """Owner command to manage channels where images are scanned."""
    await ctx.reply(f"**Usage:** ```\n{ctx.prefix}channel add <channels>\n{ctx.prefix}channel remove <channels>\n{ctx.prefix}channel list```")

@channel.command()
async def add(ctx: commands.Context, channels: List[discord.TextChannel]):
    scan_channels.update(ch.id for ch in channels)
    with open(SCAN_CHANNELS_FILENAME, 'w') as f:
        f.write('\n'.join([str(id) for id in scan_channels]))
    await ctx.reply('✅')

@channel.command()
async def remove(ctx: commands.Context, channels: List[discord.TextChannel]):
    scan_channels.difference_update(ch.id for ch in channels)
    with open(SCAN_CHANNELS_FILENAME, 'w') as f:
        f.write('\n'.join([str(id) for id in scan_channels]))
    await ctx.reply('✅')

@channel.command()
async def list(ctx: commands.Context):
    await ctx.reply('\n'.join([f'<#{id}>' for id in scan_channels]) or "*None*")


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}!")


bot.run(os.environ["BOT_TOKEN"])
