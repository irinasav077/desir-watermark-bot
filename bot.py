import os
import re
import asyncio
import html
import subprocess
import uuid

from PIL import Image, ImageDraw, ImageFont

from telegram import (
    Update,
    InputMediaPhoto,
    InputMediaVideo,
)

from telegram.constants import ParseMode

from telegram.ext import (
    Application,
    MessageHandler,
    ContextTypes,
    filters,
)


TOKEN = os.getenv("BOT_TOKEN")

WATERMARK_TEXT = "DESIR\n-edit-"

# Було 80 — зробили трохи яскравіше
WATERMARK_OPACITY = 85

# Тут зберігається ОСТАННІЙ бренд для кожного чату.
# Він діє, поки користувач не напише новий.
current_brand = {}

# Альбоми
media_groups = {}

# Щоб один альбом не запускався декілька разів
processing_groups = set()


# =========================================================
# WATERMARK ДЛЯ ФОТО
# =========================================================

def create_watermark_png(path, font_size):
    """
    Створює прозорий PNG з watermark.
    Він використовується і для фото, і для відео.
    """

    try:
        font = ImageFont.truetype(
            "Mont-Light.ttf",
            font_size
        )
    except:
        font = ImageFont.load_default()

    dummy = Image.new(
        "RGBA",
        (2000, 1000),
        (255, 255, 255, 0)
    )

    draw = ImageDraw.Draw(dummy)

    bbox = draw.multiline_textbbox(
        (0, 0),
        WATERMARK_TEXT,
        font=font,
        align="center"
    )

    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    watermark = Image.new(
        "RGBA",
        (
            text_width + 40,
            text_height + 40
        ),
        (255, 255, 255, 0)
    )

    watermark_draw = ImageDraw.Draw(watermark)

    watermark_draw.multiline_text(
        (
            20 - bbox[0],
            20 - bbox[1]
        ),
        WATERMARK_TEXT,
        font=font,
        fill=(
            255,
            255,
            255,
            WATERMARK_OPACITY
        ),
        align="center"
    )

    watermark.save(path)


def add_watermark(
    input_path,
    output_path
):
    image = Image.open(
        input_path
    ).convert("RGBA")

    overlay = Image.new(
        "RGBA",
        image.size,
        (255, 255, 255, 0)
    )

    draw = ImageDraw.Draw(overlay)

    width, height = image.size

    font_size = int(
        min(width, height) * 0.06
    )

    try:
        font = ImageFont.truetype(
            "Mont-Light.ttf",
            font_size
        )
    except:
        font = ImageFont.load_default()

    bbox = draw.multiline_textbbox(
        (0, 0),
        WATERMARK_TEXT,
        font=font,
        align="center"
    )

    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    x = (width - text_width) / 2
    y = (height - text_height) / 2

    draw.multiline_text(
        (x, y),
        WATERMARK_TEXT,
        font=font,
        fill=(
            255,
            255,
            255,
            WATERMARK_OPACITY
        ),
        align="center"
    )

    result = Image.alpha_composite(
        image,
        overlay
    )

    result.convert("RGB").save(
        output_path,
        quality=95
    )


# =========================================================
# WATERMARK ДЛЯ ВІДЕО
# =========================================================

def add_video_watermark(
    input_path,
    output_path
):
    """
    Накладає watermark по центру відео.
    """

    watermark_file = f"wm_{uuid.uuid4().hex}.png"

    try:

        # Тимчасово створюємо watermark
        # розміром 6% від умовного базового розміру.
        # FFmpeg масштабуватиме його під відео.
        create_watermark_png(
            watermark_file,
            90
        )

        command = [
            "ffmpeg",
            "-y",

            "-i",
            input_path,

            "-i",
            watermark_file,

            "-filter_complex",
            (
                "[1:v]format=rgba,"
                "scale=iw*0.55:-1[wm];"
                "[0:v][wm]"
                "overlay="
                "(main_w-overlay_w)/2:"
                "(main_h-overlay_h)/2"
            ),

            "-map",
            "0:v:0",

            "-map",
            "0:a?",

            "-c:v",
            "libx264",

            "-preset",
            "veryfast",

            "-crf",
            "20",

            "-c:a",
            "aac",

            "-movflags",
            "+faststart",

            output_path
        ]

        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        if result.returncode != 0:
            print(
                "FFMPEG ERROR:",
                result.stderr
            )

            raise RuntimeError(
                "Не вдалося накласти watermark на відео"
            )

    finally:

        if os.path.exists(
            watermark_file
        ):
            os.remove(
                watermark_file
            )


# =========================================================
# ЦІНА
# =========================================================

def parse_price(value):
    """
    1.000 -> 1000
    1,000 -> 1000
    1 000 -> 1000
    1000 -> 1000
    """

    value = value.strip()

    value = value.replace(
        " ",
        ""
    )

    if re.fullmatch(
        r"\d{1,3}(?:[.,]\d{3})+",
        value
    ):
        value = (
            value
            .replace(".", "")
            .replace(",", "")
        )

    try:
        return float(value)

    except ValueError:
        return None


def increase_price(price):
    """
    +10%
    """

    result = price * 1.10

    if result.is_integer():
        return str(int(result))

    return (
        f"{result:.2f}"
        .rstrip("0")
        .rstrip(".")
    )


def extract_price(text):
    """
    Знаходить:
    1000€
    1.000€
    1,000€
    1 000€
    """

    pattern = (
        r"(\d{1,3}"
        r"(?:[.\s,]\d{3})*|\d+)"
        r"\s*€"
    )

    match = re.search(
        pattern,
        text
    )

    if not match:
        return None, text

    raw_price = match.group(1)

    price = parse_price(
        raw_price
    )

    if price is None:
        return None, text

    final_price = increase_price(
        price
    )

    # Видаляємо початкову ціну
    clean_text = (
        text[:match.start()]
        +
        text[match.end():]
    )

    clean_text = re.sub(
        r"\s+",
        " ",
        clean_text
    ).strip()

    return final_price, clean_text


# =========================================================
# ФОРМУВАННЯ ТЕКСТУ
# =========================================================

def clean_brand_text(text):
    """
    Забирає ціну з назви бренду,
    але залишає сам текст.
    """

    _, clean_text = extract_price(
        text
    )

    clean_text = clean_text.strip()

    return clean_text


def make_hashtag(brand_text):
    """
    Prada -> #prada
    PRADA -> #prada
    """

    if not brand_text:
        return ""

    words = brand_text.split(
        maxsplit=1
    )

    brand = words[0]

    brand = re.sub(
        r"[^a-zA-Zа-яА-ЯіїєґІЇЄҐ0-9]",
        "",
        brand
    )

    if not brand:
        return ""

    return "#" + brand.lower()


def build_caption(
    brand_text,
    price_text=None
):
    """
    Приклад:

    Prada new collection✨
    1000€

    -->

    #prada new collection✨

    🏷️1100€
    + доставка 📦
    Для консультації та замовлення:
    💌@irasavchenkoo
    """

    if not brand_text:
        brand_text = ""

    final_price = None

    if price_text:
        final_price, _ = extract_price(
            price_text
        )

    # Бренд
    hashtag = make_hashtag(
        brand_text
    )

    # Все після першого слова
    parts = brand_text.split(
        maxsplit=1
    )

    if len(parts) > 1:
        rest = parts[1].strip()
    else:
        rest = ""

    if hashtag and rest:
        first_line = (
            f"{hashtag} {rest}"
        )
    else:
        first_line = hashtag

    lines = []

    if first_line:
        lines.append(
            first_line
        )

    if final_price:
        lines.append("")
        lines.append(
            f"🏷️{final_price}€"
        )
        lines.append(
            "+ доставка 📦"
        )

    lines.append("")
    lines.append(
        "Для консультації та замовлення:"
    )
    lines.append(
        "💌@irasavchenkoo"
    )

    plain_caption = "\n".join(
        lines
    )

    # Захист від HTML
    safe_caption = html.escape(
        plain_caption
    )

    # Реальний курсив
    return f"<i>{safe_caption}</i>"


# =========================================================
# ТЕКСТ КОРИСТУВАЧА
# =========================================================

async def handle_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    """
    Коли ти пишеш:

    Prada new collection✨

    бот запам'ятовує це як
    поточний бренд.

    Він залишається активним,
    поки ти не напишеш новий.
    """

    text = update.message.text

    if not text:
        return

    chat_id = update.effective_chat.id

    # Якщо в тексті є ціна,
    # зберігаємо тільки назву/опис без ціни.
    brand_text = clean_brand_text(
        text
    )

    if brand_text:
        current_brand[chat_id] = (
            brand_text
        )

        print(
            f"Brand for {chat_id}: "
            f"{brand_text}"
        )


# =========================================================
# ОДНЕ ФОТО
# =========================================================

async def process_single_photo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat_id = update.effective_chat.id

    brand_text = current_brand.get(
        chat_id,
        ""
    )

    # Якщо ціна була в caption самого фото
    source_caption = (
        update.message.caption or ""
    )

    if source_caption:
        final_price, _ = extract_price(
            source_caption
        )
    else:
        final_price = None

    caption = build_caption(
        brand_text,
        source_caption
    )

    photo = update.message.photo[-1]

    unique_id = uuid.uuid4().hex

    input_file = (
        f"input_{unique_id}.jpg"
    )

    output_file = (
        f"watermarked_{unique_id}.jpg"
    )

    file = await context.bot.get_file(
        photo.file_id
    )

    await file.download_to_drive(
        input_file
    )

    try:

        add_watermark(
            input_file,
            output_file
        )

        with open(
            output_file,
            "rb"
        ) as img:

            await update.message.reply_photo(
                photo=img,
                caption=caption,
                parse_mode=ParseMode.HTML
            )

    finally:

        if os.path.exists(input_file):
            os.remove(input_file)

        if os.path.exists(output_file):
            os.remove(output_file)


# =========================================================
# ОДНЕ ВІДЕО
# =========================================================

async def process_single_video(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    chat_id = update.effective_chat.id

    brand_text = current_brand.get(
        chat_id,
        ""
    )

    source_caption = (
        update.message.caption or ""
    )

    caption = build_caption(
        brand_text,
        source_caption
    )

    video = update.message.video

    unique_id = uuid.uuid4().hex

    input_file = (
        f"input_{unique_id}.mp4"
    )

    output_file = (
        f"watermarked_{unique_id}.mp4"
    )

    file = await context.bot.get_file(
        video.file_id
    )

    await file.download_to_drive(
        input_file
    )

    try:

        await asyncio.to_thread(
            add_video_watermark,
            input_file,
            output_file
        )

        with open(
            output_file,
            "rb"
        ) as video_file:

            await update.message.reply_video(
                video=video_file,
                caption=caption,
                parse_mode=ParseMode.HTML
            )

    finally:

        if os.path.exists(input_file):
            os.remove(input_file)

        if os.path.exists(output_file):
            os.remove(output_file)


# =========================================================
# АЛЬБОМ
# =========================================================

async def process_album(
    media_group_id,
    context
):

    # Даємо Telegram зібрати весь альбом
    await asyncio.sleep(3)

    if media_group_id not in media_groups:
        return

    messages = media_groups[
        media_group_id
    ]

    messages.sort(
        key=lambda x: x.message_id
    )

    first_message = messages[0]

    chat_id = first_message.chat_id

    brand_text = current_brand.get(
        chat_id,
        ""
    )

    # Якщо ціна була в caption першого
    # повідомлення альбому
    source_caption = (
        first_message.caption or ""
    )

    caption = build_caption(
        brand_text,
        source_caption
    )

    media = []

    opened_files = []

    temp_files = []

    try:

        for index, msg in enumerate(
            messages
        ):

            # -------------------------
            # ФОТО
            # -------------------------

            if msg.photo:

                photo = msg.photo[-1]

                unique_id = (
                    uuid.uuid4().hex
                )

                input_file = (
                    f"input_{unique_id}.jpg"
                )

                output_file = (
                    f"watermarked_{unique_id}.jpg"
                )

                file = await context.bot.get_file(
                    photo.file_id
                )

                await file.download_to_drive(
                    input_file
                )

                add_watermark(
                    input_file,
                    output_file
                )

                temp_files.append(
                    input_file
                )

                temp_files.append(
                    output_file
                )

                f = open(
                    output_file,
                    "rb"
                )

                opened_files.append(f)

                if index == 0:

                    media.append(
                        InputMediaPhoto(
                            media=f,
                            caption=caption,
                            parse_mode=ParseMode.HTML
                        )
                    )

                else:

                    media.append(
                        InputMediaPhoto(
                            media=f
                        )
                    )

            # -------------------------
            # ВІДЕО В АЛЬБОМІ
            # -------------------------

            elif msg.video:

                video = msg.video

                unique_id = (
                    uuid.uuid4().hex
                )

                input_file = (
                    f"input_{unique_id}.mp4"
                )

                output_file = (
                    f"watermarked_{unique_id}.mp4"
                )

                file = await context.bot.get_file(
                    video.file_id
                )

                await file.download_to_drive(
                    input_file
                )

                await asyncio.to_thread(
                    add_video_watermark,
                    input_file,
                    output_file
                )

                temp_files.append(
                    input_file
                )

                temp_files.append(
                    output_file
                )

                f = open(
                    output_file,
                    "rb"
                )

                opened_files.append(f)

                if index == 0:

                    media.append(
                        InputMediaVideo(
                            media=f,
                            caption=caption,
                            parse_mode=ParseMode.HTML
                        )
                    )

                else:

                    media.append(
                        InputMediaVideo(
                            media=f
                        )
                    )

        if media:

            await first_message.reply_media_group(
                media
            )

    finally:

        for f in opened_files:
            f.close()

        for file_name in temp_files:

            if os.path.exists(file_name):
                os.remove(file_name)

        media_groups.pop(
            media_group_id,
            None
        )

        processing_groups.discard(
            media_group_id
        )


# =========================================================
# ОБРОБКА ФОТО
# =========================================================

async def handle_photo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    media_group_id = (
        update.message.media_group_id
    )

    if not media_group_id:

        await process_single_photo(
            update,
            context
        )

        return

    if media_group_id not in media_groups:

        media_groups[
            media_group_id
        ] = []

    media_groups[
        media_group_id
    ].append(
        update.message
    )

    if media_group_id not in processing_groups:

        processing_groups.add(
            media_group_id
        )

        asyncio.create_task(
            process_album(
                media_group_id,
                context
            )
        )


# =========================================================
# ОБРОБКА ВІДЕО
# =========================================================

async def handle_video(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    media_group_id = (
        update.message.media_group_id
    )

    # Якщо це звичайне відео
    if not media_group_id:

        await process_single_video(
            update,
            context
        )

        return

    # Якщо відео є частиною альбому
    if media_group_id not in media_groups:

        media_groups[
            media_group_id
        ] = []

    media_groups[
        media_group_id
    ].append(
        update.message
    )

    if media_group_id not in processing_groups:

        processing_groups.add(
            media_group_id
        )

        asyncio.create_task(
            process_album(
                media_group_id,
                context
            )
        )


# =========================================================
# MAIN
# =========================================================

def main():

    app = (
        Application
        .builder()
        .token(TOKEN)
        .build()
    )

    # Текст = встановлення нового бренду
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_text
        )
    )

    # Фото
    app.add_handler(
        MessageHandler(
            filters.PHOTO,
            handle_photo
        )
    )

    # Відео
    app.add_handler(
        MessageHandler(
            filters.VIDEO,
            handle_video
        )
    )

    app.run_polling()


if __name__ == "__main__":
    main()
