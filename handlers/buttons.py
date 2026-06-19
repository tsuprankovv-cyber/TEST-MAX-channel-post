"""
Парсинг URL-кнопок
"""
from typing import List, Dict
from core.logger import get_logger

logger = get_logger(__name__)


def parse_buttons(text: str) -> List[List[Dict]]:
    logger.info(f"[BTN] Parsing: '{text[:150]}...'")
    rows = []
    for line in text.strip().split('\n'):
        line = line.strip()
        if not line:
            continue
        for sep in [' | ', ' - ', ' → ']:
            if sep in line:
                parts = line.split(sep, 1)
                btn_text = parts[0].strip()
                btn_url = parts[1].strip()
                if btn_text and btn_url.startswith(('http://', 'https://')):
                    rows.append([{"type": "link", "text": btn_text, "url": btn_url}])
                    logger.info(f"[BTN] ✅ '{btn_text}' → {btn_url[:50]}...")
                    break
    logger.info(f"[BTN] Total: {len(rows)} rows")
    return rows
