import os
from PIL import Image, ImageDraw, ImageFont
from telegram import Update
from telegram.ext import Application, MessageHandler, ContextTypes, filters

TOKEN = os.getenv("BOT_TOKEN")

WATERMARK_TEXT = "DESIR\n-edit-"


def add_watermark(input_path, output_path):
    image = Image.open(input_path).convert("RGBA")

    overlay = Image.new("RGBA", image.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)

    width, height = image.size

    font_size = int(min(width, height) * 0.35)

    try:
        font = ImageFont.truetype("arial.ttf", font_size)
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
        fill=(255, 255, 255, 80),
        align="center"
    )

    result = Image.alpha_composite(image, overlay)
    result.convert("RGB").save(output_path, quality=95)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-1]

    input_file = f"{photo.file_id}.jpg"
    output_file = f"watermarked_{photo.file_id}.jpg"

    file = await context.bot.get_file(photo.file_id)
    await file.download_to_drive(input_file)

    add_watermark(input_file, output_file)

    with open(output_file, "rb") as img:
        await update.message.reply_photo(photo=img)

    os.remove(input_file)
    os.remove(output_file)


def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(
        MessageHandler(filters.PHOTO, handle_photo)
    )

    app.run_polling()


if __name__ == "__main__":
    main()
