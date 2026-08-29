from __future__ import annotations

from caldav_assistant.internal.localization import LocaleService


class Settings:
    def __init__(self, locale: str):
        self.locale = locale

    def get(self, key, default=None):
        if key == "ui.locale":
            return self.locale
        return default


def test_command_support_states_have_simplified_chinese_messages():
    locale = LocaleService(Settings("zh-CN"))

    unsupported = locale.t(
        "cli.unsupported_command",
        command="foo",
    )
    disabled = locale.t(
        "cli.command_supported_extension_disabled",
        command="run",
        extension="developer_tools",
    )
    failed = locale.t(
        "cli.command_supported_extension_error",
        command="run",
        extension="developer_tools",
    )

    assert unsupported == "不支持的命令：foo。输入 'help' 查看当前可用命令。"
    assert "受支持" in disabled
    assert "已禁用" in disabled
    assert "extension enable developer_tools" in disabled
    assert "加载失败" in failed
    assert "extension errors developer_tools" in failed
