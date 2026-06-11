# リポジトリルートをコンテキストにビルドする（store.py が src/db.py を使うため）:
#   docker compose build bot
FROM python:3.11-slim

WORKDIR /app

COPY moimoichan_Discordbot/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/
COPY moimoichan_Discordbot/ .

CMD ["python", "bot.py"]
