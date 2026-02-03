from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


LOG_DIR = Path("logs")
OUTPUT_DIR = Path("outputs")


def ensure_dirs() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def setup_logger(name: str = "screener") -> logging.Logger:
    ensure_dirs()
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    logfile = LOG_DIR / f"{timestamp}.log"

    file_handler = logging.FileHandler(logfile)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.propagate = False
    return logger


def safe_div(numerator: float | int, denominator: float | int) -> float:
    if denominator == 0:
        return 0.0
    return float(numerator) / float(denominator)


def now_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")


def serialize(obj: Any) -> Any:
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, Path):
        return str(obj)
    return obj


def save_json(data: Any, path: Path) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=serialize))


def save_text(text: str, path: Path) -> None:
    path.write_text(text)


def chunk_markdown(message: str, limit: int = 1900) -> list[str]:
    paragraphs = message.split("\n\n")
    chunks: list[str] = []
    current = []
    current_len = 0
    fence_open = False

    def fence_count(text: str) -> int:
        return text.count("```")

    for paragraph in paragraphs:
        paragraph = paragraph.strip("\n")
        if not paragraph:
            continue
        para_len = len(paragraph)
        if current and current_len + para_len + 2 > limit:
            if fence_open:
                current.append("```")
                chunks.append("\n\n".join(current))
                current = ["```"]
                current_len = len("```")
            else:
                chunks.append("\n\n".join(current))
                current = []
                current_len = 0
        if current:
            current.append(paragraph)
            current_len += para_len + 2
        else:
            current = [paragraph]
            current_len = para_len
        if fence_count(paragraph) % 2 == 1:
            fence_open = not fence_open

    if current:
        if fence_open:
            current.append("```")
        chunks.append("\n\n".join(current))
    return chunks


def read_tickers(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line.strip().upper() for line in path.read_text().splitlines() if line.strip()]


def iter_with_pause(items: Iterable[str], pause_sec: float) -> Iterable[str]:
    for item in items:
        yield item
        if pause_sec > 0:
            import time

            time.sleep(pause_sec)


def env_or_default(key: str, default: str) -> str:
    return os.getenv(key, default)
