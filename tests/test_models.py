"""src/models.py のテスト"""

from src.models import RawAttachment, RawMessage


def _make_message(**kwargs) -> RawMessage:
    defaults = dict(
        id="111",
        guild_id="g-111",
        channel_id="222",
        channel_name="general",
        author_id="333",
        author_name="Alice",
        content="こんにちは",
        timestamp="2024-01-15T12:00:00+00:00",
        has_attachment=False,
        is_pinned=False,
        reaction_count=0,
        thread_id=None,
        thread_name=None,
    )
    return RawMessage(**{**defaults, **kwargs})


class TestRawMessage:
    def test_basic_fields(self):
        msg = _make_message()
        assert msg.id == "111"
        assert msg.guild_id == "g-111"
        assert msg.channel_name == "general"
        assert msg.content == "こんにちは"

    def test_thread_fields_are_none_by_default(self):
        msg = _make_message()
        assert msg.thread_id is None
        assert msg.thread_name is None

    def test_thread_fields_can_be_set(self):
        msg = _make_message(thread_id="999", thread_name="雑談スレ")
        assert msg.thread_id == "999"
        assert msg.thread_name == "雑談スレ"

    def test_empty_content_is_allowed(self):
        """添付のみメッセージは content が空文字になる"""
        msg = _make_message(content="", has_attachment=True)
        assert msg.content == ""
        assert msg.has_attachment is True

    def test_reaction_count(self):
        msg = _make_message(reaction_count=5)
        assert msg.reaction_count == 5


class TestRawAttachment:
    def test_basic_fields(self):
        att = RawAttachment(
            id="att-1",
            message_id="msg-1",
            url="https://cdn.discordapp.com/attachments/1/2/photo.png",
            filename="photo.png",
            content_type="image/png",
        )
        assert att.id == "att-1"
        assert att.filename == "photo.png"
        assert att.content_type == "image/png"

    def test_content_type_can_be_none(self):
        """content_type が不明な場合は None"""
        att = RawAttachment(
            id="att-2",
            message_id="msg-1",
            url="https://example.com/file",
            filename="file.bin",
            content_type=None,
        )
        assert att.content_type is None
