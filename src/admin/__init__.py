"""管理者向けポータル（FastAPI + Jinja2）。OI-14 の収益化運用ダッシュボード。

別の compose サービス `admin` として公開APIと分離して起動する
（uvicorn src.admin.app:app）。認証は ADMIN_PASSWORD による簡易パスワード方式。
"""
