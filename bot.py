import os
import asyncio
import re

from PIL import Image, ImageDraw, ImageFont

from telegram import (
    Update,
    InputMediaPhoto,
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

# Було 80 — робимо трохи яскравіше
WATERMARK_OPACITY = 85

# Текст, який бот очікує перед фото
pending_text = {}

# Альбоми
media_groups = {}
processing_groups = set()


# =========================================================
# WATERMARK
# =========================================================

def add_watermark(input_path, output_path):
    image = Image.open(input_path).convert("RGBA")

    overlay = Image.new(
        "RGBA",
        image.size,
        (255, 255, 255, 0)
    )

    draw = ImageDraw.Draw(overlay)

    width, height = image.size

    font_size = int(min(width, height) * 0.06)

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
        fill=(255, 255, 255, WATERMARK_OPACITY),
        align="center"
    )

    result = Image.alpha_composite(image, overlay)

    result.convert("RGB").save(
        output_path,
        quality=95
    )


# =========================================================
# ЦІНА
# =========================================================

def parse_price(price_text):
    """
    Перетворює:
    1.000 -> 1000
    1.050 -> 1050
    3.500 -> 3500
    1000 -> 1000
    """

    cleaned = price_text.strip()

    # Якщо є крапка між цифрами — це розділювач тисяч
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", cleaned):
        cleaned = cleaned.replace(".", "")

    # Якщо кома — також розділювач тисяч
    elif re.fullmatch(r"\d{1,3}(?:,\d{3})+", cleaned):
        cleaned = cleaned.replace(",", "")

    try:
        return float(cleaned)
    except ValueError:
        return None


def increase_price(price):
    """
    Додаємо 10%.
    Наприклад:
    1000 -> 1100
    950 -> 1045
    1200 -> 1320
    1050 -> 1155
    """

    final_price = price * 1.10

    # Для наших цін залишаємо ціле число
    if final_price.is_integer():
        return str(int(final_price))

    return f"{final_price:.2f}".rstrip("0").rstrip(".")


def extract_price(text):
    """
    Шукає ціну у форматах:
    1000€
    1.000€
    1 000€
    1,000€
    1000 €
    """

    pattern = r"(\d{1,3}(?:[.\s,]\d{3})*|\d+)\s*€"

    match = re.search(pattern, text)

    if not match:
        return None, text

    raw_price = match.group(1)

    # Прибираємо пробіли
    raw_price = raw_price.replace(" ", "")

    price = parse_price(raw_price)

    if price is None:
        return None, text

    final_price = increase_price(price)

    # Видаляємо початкову ціну з тексту
    text_without_price = (
        text[:match.start()] +
        text[match.end():]
    )

    return final_price, text_without_price.strip()


# =========================================================
# ФОРМУВАННЯ ПІДПИСУ
# =========================================================

def build_caption(source_text):
    """
    Наприклад:

    Prada new collection✨ 1000€

    перетворюється на:

    #prada new collection✨

    🏷️1100€
    + доставка 📦
    Для консультації та замовлення:
    💌@irasavchenkoo
    """

    if not source_text:
        source_text = ""

    text = source_text.strip()

    # -----------------------------------------------------
    # Витягуємо ціну
    # -----------------------------------------------------

    final_price, text_without_price = extract_price(text)

    # -----------------------------------------------------
    # Очищаємо зайві пробіли
    # -----------------------------------------------------

    text_without_price = re.sub(
        r"\s+",
        " ",
        text_without_price
    ).strip()

    # -----------------------------------------------------
    # Перший текст — бренд
    # -----------------------------------------------------

    words = text_without_price.split(maxsplit=1)

    if not words:
        brand = ""
        rest = ""
    else:
        brand = words[0]
        rest = words[1] if len(words) > 1 else ""

    # -----------------------------------------------------
    # Формуємо hashtag
    # -----------------------------------------------------

    brand_clean = re.sub(
        r"[^a-zA-Zа-яА-ЯіїєґІЇЄҐ0-9]",
        "",
        brand
    ).lower()

    if brand_clean:
        hashtag = f"#{brand_clean}"
    else:
        hashtag = ""

    # -----------------------------------------------------
    # Назва / collection після бренду
    # -----------------------------------------------------

    if rest:
        first_line = f"{hashtag} {rest}".strip()
    else:
        first_line = hashtag

    # -----------------------------------------------------
    # Формуємо фінальний caption
    # -----------------------------------------------------

    lines = []

    if first_line:
        lines.append(first_line)

    if final_price:
        lines.append("")
        lines.append(f"🏷️{final_price}€")
        lines.append("+ доставка 📦")

    lines.append("")
    lines.append("Для консультації та замовлення:")
    lines.append("💌@irasavchenkoo")

    return "\n".join(lines)


# =========================================================
# ОДНЕ ФОТО
# =========================================================

async def process_single_photo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    photo = update.message.photo[-1]

    input_file = f"{photo.file_id}.jpg"
    output_file = f"watermarked_{photo.file_id}.jpg"

    # Беремо текст, який був надісланий перед фото
    chat_id = update.effective_chat.id

    source_text = pending_text.pop(chat_id, "")

    caption = build_caption(source_text)

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

        with open(output_file, "rb") as img:

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
# АЛЬБОМ
# =========================================================

async def process_album(
    media_group_id,
    context: ContextTypes.DEFAULT_TYPE
):

    # Даємо Telegram час передати всі фото альбому
    await asyncio.sleep(3)

    if media_group_id not in media_groups:
        return

    messages = media_groups[media_group_id]

    messages.sort(
        key=lambda x: x.message_id
    )

    # Текст бренду беремо з першого повідомлення
    first_message = messages[0]

    chat_id = first_message.chat_id

    source_text = pending_text.pop(
        chat_id,
        ""
    )

    caption = build_caption(
        source_text
    )

    media = []
    opened_files = []
    temp_files = []

    try:

        for index, msg in enumerate(messages):

            photo = msg.photo[-1]

            input_file = f"{photo.file_id}.jpg"
            output_file = f"watermarked_{photo.file_id}.jpg"

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

            temp_files.append(input_file)
            temp_files.append(output_file)

            f = open(
                output_file,
                "rb"
            )

            opened_files.append(f)

            # Caption ставимо тільки на перше фото
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

    # Звичайне одне фото
    if not media_group_id:

        await process_single_photo(
            update,
            context
        )

        return

    # Альбом
    if media_group_id not in media_groups:

        media_groups[media_group_id] = []

    media_groups[media_group_id].append(
        update.message
    )

    # Запускаємо обробку тільки один раз
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
# ТЕКСТ ПЕРЕД ФОТО
# =========================================================

async def handle_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    text = update.message.text

    if not text:
        return

    chat_id = update.effective_chat.id

    # Запам'ятовуємо останній текст
    # для наступного фото/альбому
    pending_text[chat_id] = text.strip()


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

    # Текст обробляємо перед фото
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

    app.run_polling()


if __name__ == "__main__":
    main()
