import os
import re
import asyncio
import html
import uuid
import subprocess

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

# Яскравість watermark
WATERMARK_OPACITY = 85


# =========================================================
# ПОТОЧНИЙ БРЕНД
# =========================================================

current_brand = {}


# =========================================================
# АЛЬБОМИ
# =========================================================

media_groups = {}
processing_groups = set()


# =========================================================
# WATERMARK ДЛЯ ФОТО
# =========================================================

def add_watermark(input_path, output_path):

    image = Image.open(
        input_path
    ).convert("RGBA")

    overlay = Image.new(
        "RGBA",
        image.size,
        (255, 255, 255, 0)
    )

    draw = ImageDraw.Draw(
        overlay
    )

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

    text_width = (
        bbox[2] - bbox[0]
    )

    text_height = (
        bbox[3] - bbox[1]
    )

    x = (
        width - text_width
    ) / 2

    y = (
        height - text_height
    ) / 2

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

    result.convert(
        "RGB"
    ).save(
        output_path,
        quality=95
    )


# =========================================================
# ОТРИМАТИ РОЗМІР ВІДЕО
# =========================================================

def get_video_size(video_path):

    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "csv=s=x:p=0",
        video_path,
    ]

    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    if result.returncode != 0:
        raise RuntimeError(
            "FFprobe не зміг прочитати відео:\n"
            + result.stderr
        )

    value = result.stdout.strip()

    width, height = map(
        int,
        value.split("x")
    )

    return width, height


# =========================================================
# СТВОРИТИ WATERMARK ДЛЯ ВІДЕО
# =========================================================

def create_video_watermark(
    width,
    height,
    watermark_path
):

    image = Image.new(
        "RGBA",
        (width, height),
        (255, 255, 255, 0)
    )

    draw = ImageDraw.Draw(
        image
    )

    font_size = int(
        min(width, height) * 0.06
    )

    font_size = max(
        font_size,
        24
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

    text_width = (
        bbox[2] - bbox[0]
    )

    text_height = (
        bbox[3] - bbox[1]
    )

    x = (
        width - text_width
    ) / 2

    y = (
        height - text_height
    ) / 2

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

    image.save(
        watermark_path
    )


# =========================================================
# WATERMARK ДЛЯ ВІДЕО
# =========================================================

def add_video_watermark(
    input_path,
    output_path
):

    watermark_path = (
        f"watermark_{uuid.uuid4().hex}.png"
    )

    try:

        width, height = get_video_size(
            input_path
        )

        create_video_watermark(
            width,
            height,
            watermark_path
        )

        command = [
            "ffmpeg",
            "-y",
            "-i",
            input_path,
            "-i",
            watermark_path,

            "-filter_complex",
            (
                "[1:v]format=rgba[wm];"
                "[0:v][wm]"
                "overlay=0:0"
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
            "18",

            "-pix_fmt",
            "yuv420p",

            "-c:a",
            "aac",

            "-b:a",
            "192k",

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
                "FFMPEG ERROR:"
            )

            print(
                result.stderr
            )

            raise RuntimeError(
                "FFmpeg не зміг обробити відео"
            )

    finally:

        if os.path.exists(
            watermark_path
        ):
            os.remove(
                watermark_path
            )


# =========================================================
# ЦІНА
# =========================================================

def parse_price(value):

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

    result = price * 1.10

    if result.is_integer():

        return str(
            int(result)
        )

    return (
        f"{result:.2f}"
        .rstrip("0")
        .rstrip(".")
    )


# =========================================================
# ЗНАЙТИ ВСІ ЦІНИ
# =========================================================

def extract_prices(text):

    pattern = (
        r"(\d{1,3}"
        r"(?:[.\s,]\d{3})*|\d+)"
        r"\s*€"
    )

    results = []

    if not text:
        return results

    lines = text.splitlines()

    for line in lines:

        matches = list(
            re.finditer(
                pattern,
                line
            )
        )

        if not matches:
            continue

        # Якщо в одному рядку одна ціна
        if len(matches) == 1:

            match = matches[0]

            raw_price = match.group(1)

            price = parse_price(
                raw_price
            )

            if price is None:
                continue

            final_price = increase_price(
                price
            )

            # Все, що залишилось у рядку
            # після видалення ціни
            label = (
                line[:match.start()]
                +
                line[match.end():]
            )

            label = re.sub(
                r"\s+",
                " ",
                label
            ).strip()

            # Прибираємо зайві тире,
            # двокрапки та крапки
            label = re.sub(
                r"^[\s\-–—:|]+|[\s\-–—:|.,]+$",
                "",
                label
            ).strip()

            results.append(
                (
                    final_price,
                    label
                )
            )

        # Якщо в одному рядку декілька цін
        else:

            for match in matches:

                raw_price = match.group(1)

                price = parse_price(
                    raw_price
                )

                if price is None:
                    continue

                final_price = increase_price(
                    price
                )

                results.append(
                    (
                        final_price,
                        ""
                    )
                )

    return results


# =========================================================
# СУМІСНІСТЬ З ОДНІЄЮ ЦІНОЮ
# =========================================================

def extract_price(text):

    prices = extract_prices(
        text
    )

    if not prices:
        return None, text

    final_price = prices[0][0]

    # Видаляємо першу ціну
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
        return final_price, text

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
# БРЕНД
# =========================================================

def clean_brand_text(text):

    if not text:
        return ""

    # Для назви бренду прибираємо ціни
    clean_text = re.sub(
        r"(\d{1,3}(?:[.\s,]\d{3})*|\d+)\s*€",
        "",
        text
    )

    clean_text = re.sub(
        r"\s+",
        " ",
        clean_text
    ).strip()

    return clean_text


def make_hashtag(brand_text):

    if not brand_text:
        return ""

    parts = brand_text.split(
        maxsplit=1
    )

    brand = parts[0]

    brand = re.sub(
        r"[^a-zA-Zа-яА-ЯіїєґІЇЄҐ0-9]",
        "",
        brand
    )

    if not brand:
        return ""

    return "#" + brand.lower()


# =========================================================
# CAPTION
# =========================================================

def build_caption(
    brand_text,
    source_text=""
):

    if not brand_text:
        brand_text = ""

    hashtag = make_hashtag(
        brand_text
    )

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

    # =====================================================
    # ВСІ ЦІНИ
    # =====================================================

    prices = extract_prices(
        source_text
    )

    if prices:

        lines.append("")

        for final_price, label in prices:

            if label:

                lines.append(
                    f"🏷️{final_price}€ {label}"
                )

            else:

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

    return (
        "<i>"
        +
        html.escape(
            plain_caption
        )
        +
        "</i>"
    )


# =========================================================
# ТЕКСТ — ВСТАНОВЛЕННЯ НОВОГО БРЕНДУ
# =========================================================

async def handle_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    text = update.message.text

    if not text:
        return

    chat_id = (
        update.effective_chat.id
    )

    brand_text = clean_brand_text(
        text
    )

    if brand_text:

        current_brand[
            chat_id
        ] = brand_text

        print(
            f"New brand for "
            f"{chat_id}: "
            f"{brand_text}"
        )


# =========================================================
# ОДНЕ ФОТО
# =========================================================

async def process_single_photo(
    update,
    context
):

    chat_id = (
        update.effective_chat.id
    )

    brand_text = current_brand.get(
        chat_id,
        ""
    )

    source_caption = (
        update.message.caption
        or ""
    )

    caption = build_caption(
        brand_text,
        source_caption
    )

    photo = (
        update.message.photo[-1]
    )

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

        if os.path.exists(
            input_file
        ):
            os.remove(
                input_file
            )

        if os.path.exists(
            output_file
        ):
            os.remove(
                output_file
            )


# =========================================================
# ОДНЕ ВІДЕО
# =========================================================

async def process_single_video(
    update,
    context
):

    chat_id = (
        update.effective_chat.id
    )

    brand_text = current_brand.get(
        chat_id,
        ""
    )

    source_caption = (
        update.message.caption
        or ""
    )

    caption = build_caption(
        brand_text,
        source_caption
    )

    # =====================================================
    # VIDEO АБО DOCUMENT
    # =====================================================

    if update.message.video:

        media_file = (
            update.message.video
        )

    elif (
        update.message.document
        and update.message.document.mime_type
        and update.message.document.mime_type.startswith(
            "video/"
        )
    ):

        media_file = (
            update.message.document
        )

    else:

        return

    unique_id = uuid.uuid4().hex

    input_file = (
        f"input_{unique_id}.mp4"
    )

    output_file = (
        f"watermarked_{unique_id}.mp4"
    )

    file = await context.bot.get_file(
        media_file.file_id
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

        if not os.path.exists(
            output_file
        ):

            raise RuntimeError(
                "Watermarked video "
                "не був створений"
            )

        if os.path.getsize(
            output_file
        ) == 0:

            raise RuntimeError(
                "Watermarked video "
                "порожній"
            )

        with open(
            output_file,
            "rb"
        ) as video_file:

            await update.message.reply_video(
                video=video_file,
                caption=caption,
                parse_mode=ParseMode.HTML,
                supports_streaming=True
            )

    except Exception as e:

        print(
            "VIDEO PROCESSING ERROR:"
        )

        print(
            repr(e)
        )

    finally:

        if os.path.exists(
            input_file
        ):
            os.remove(
                input_file
            )

        if os.path.exists(
            output_file
        ):
            os.remove(
                output_file
            )


# =========================================================
# АЛЬБОМ
# =========================================================

async def process_album(
    media_group_id,
    context
):

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

    source_caption = (
        first_message.caption
        or ""
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

            # =============================================
            # PHOTO
            # =============================================

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

            # =============================================
            # VIDEO
            # =============================================

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

    except Exception as e:

        print(
            "ALBUM PROCESSING ERROR:"
        )

        print(
            repr(e)
        )

    finally:

        for f in opened_files:

            try:
                f.close()
            except:
                pass

        for file_name in temp_files:

            if os.path.exists(
                file_name
            ):

                os.remove(
                    file_name
                )

        media_groups.pop(
            media_group_id,
            None
        )

        processing_groups.discard(
            media_group_id
        )


# =========================================================
# ФОТО
# =========================================================

async def handle_photo(
    update,
    context
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
# ВІДЕО
# =========================================================

async def handle_video(
    update,
    context
):

    media_group_id = (
        update.message.media_group_id
    )

    # Звичайне відео

    if not media_group_id:

        await process_single_video(
            update,
            context
        )

        return

    # Відео в альбомі

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
# DOCUMENT — ВІДЕО ЯК ФАЙЛ
# =========================================================

async def handle_video_document(
    update,
    context
):

    document = update.message.document

    if not document:
        return

    if not document.mime_type:
        return

    if not document.mime_type.startswith(
        "video/"
    ):
        return

    await process_single_video(
        update,
        context
    )


# =========================================================
# MAIN
# =========================================================

def main():

    if not TOKEN:

        raise RuntimeError(
            "BOT_TOKEN не знайдений "
            "у Variables Railway"
        )

    app = (
        Application
        .builder()
        .token(TOKEN)
        .build()
    )

    # =====================================================
    # ТЕКСТ — НОВИЙ БРЕНД
    # =====================================================

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_text
        )
    )

    # =====================================================
    # ФОТО
    # =====================================================

    app.add_handler(
        MessageHandler(
            filters.PHOTO,
            handle_photo
        )
    )

    # =====================================================
    # ВІДЕО
    # =====================================================

    app.add_handler(
        MessageHandler(
            filters.VIDEO,
            handle_video
        )
    )

    # =====================================================
    # ВІДЕО, ПЕРЕСЛАНЕ ЯК DOCUMENT
    # =====================================================

    app.add_handler(
        MessageHandler(
            filters.Document.VIDEO,
            handle_video_document
        )
    )

    app.run_polling()


if __name__ == "__main__":
    main()
