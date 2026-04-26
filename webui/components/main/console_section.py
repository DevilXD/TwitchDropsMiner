from __future__ import annotations

from nicegui import ui

from translate import _
from constants import CONFIG_PATH

_MAX_CONSOLE_LOG_SIZE = 10 * 1024 * 1024  # 10 MB


class ConsoleSection:
    def __init__(self) -> None:
        self._console_log_path = CONFIG_PATH / "console.log"
        self._console_log: list[str] = self._load()
        self._log_instances: list = []

    def build(self) -> None:
        with ui.card().props("flat bordered").classes("w-full gap-1"):
            ui.label(_("gui", "output")).classes("font-bold text-sm mb-1")
            log = ui.log(max_lines=200).classes("h-64 w-full font-mono text-xs")
            for line in self._console_log:
                log.push(line)
            self._log_instances.append(log)
            ui.context.client.on_disconnect(
                lambda: (
                    self._log_instances.remove(log)
                    if log in self._log_instances
                    else None
                )
            )

    def push(self, lines: list[str]) -> None:
        self._console_log.extend(lines)
        if len(self._console_log) > 200:
            del self._console_log[:-200]
        self._save(lines)
        for log in self._log_instances:
            for line in lines:
                log.push(line)

    def _load(self) -> list[str]:
        try:
            lines = self._console_log_path.read_text(encoding="utf-8").splitlines()
            return lines[-200:]
        except (FileNotFoundError, OSError):
            return []

    def _save(self, lines: list[str]) -> None:
        try:
            CONFIG_PATH.mkdir(parents=True, exist_ok=True)
            with self._console_log_path.open("a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            if self._console_log_path.stat().st_size > _MAX_CONSOLE_LOG_SIZE:
                all_lines = self._console_log_path.read_text(
                    encoding="utf-8"
                ).splitlines()
                keep = all_lines[len(all_lines) // 2 :]
                self._console_log_path.write_text(
                    "\n".join(keep) + "\n", encoding="utf-8"
                )
        except OSError:
            pass
