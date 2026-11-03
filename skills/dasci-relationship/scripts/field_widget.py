"""Render a self-contained, in-conversation field picker without raw cell data."""
from __future__ import annotations

import json
from pathlib import Path


def field_items(options: list[dict], *, search: str | None = None) -> list[dict]:
    return [
        {'index': option['index'], 'name': option['display_name'],
         'kind': option['effective_kind'], 'selectable': option['selectable'],
         'reason': option['reason'], 'semantic_hint': option['semantic_hint']}
        for option in options
        if not search or search.casefold() in option['display_name'].casefold()
    ]


def render(items: list[dict], context_key: str, detail: str | None = None) -> dict:
    model = {'fields': items, 'context_key': context_key, 'detail': detail}
    data = json.dumps(model, ensure_ascii=False)
    # Keep column names inside JSON even when they contain HTML/script markup.
    for char, escaped in (('&', '\\u0026'), ('<', '\\u003c'), ('>', '\\u003e'),
                          ('\u2028', '\\u2028'), ('\u2029', '\\u2029')):
        data = data.replace(char, escaped)
    template = (Path(__file__).resolve().parents[1] / 'assets' / 'field-picker-widget.html').read_text(encoding='utf-8')
    return {'title': '选择分析字段', 'widget_code': template.replace('__FIELD_DATA__', data),
            'loading_messages': json.dumps(['正在准备完整字段列表'], ensure_ascii=False)}
