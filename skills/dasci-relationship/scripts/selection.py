"""Selection boundaries shared by table inspection and analysis."""
from __future__ import annotations

import math
import re
from typing import Any


class SelectionError(ValueError):
    def __init__(self, message: str, **payload: Any):
        super().__init__(message)
        self.payload = payload


def page_options(options: list[dict], *, page: int = 1, search: str | None = None,
                 all_items: bool = False) -> dict:
    matched = [option for option in options if not search or search.casefold() in option['name'].casefold()]
    size = max(1, len(matched)) if all_items else 20
    pages = max(1, math.ceil(len(matched) / size))
    if page < 1 or page > pages:
        raise SelectionError(f'页码超出范围（1–{pages}）。', page=page, pages=pages)
    offset = (page - 1) * size
    items = matched[offset:offset + size]
    return {'items': items, 'total': len(options), 'matched': len(matched), 'page': page,
            'pages': pages, 'page_size': size, 'start': offset + 1 if items else 0,
            'end': offset + len(items), 'has_next': page < pages, 'search': search}


def resolve_option(options: list[dict], *, name: str | None = None, index: int | None = None,
                   label: str, step: str) -> dict:
    def fail(message: str):
        raise SelectionError(message, step=step, options=options)

    if name is not None and re.fullmatch(r'#[0-9]+', name):
        number = int(name[1:])
        if index is not None and index != number:
            fail(f'{label}名称与编号指向不同对象，请重新选择。')
        index, name = number, None
    by_index = None
    if index is not None:
        by_index = next((option for option in options if option['index'] == index), None)
        if by_index is None:
            fail(f'{label}编号 {index} 超出可选范围。')
    by_name = None
    if name is not None:
        exact = [option for option in options if option['name'] == name]
        matches = exact or [option for option in options if option['name'].casefold() == name.casefold()]
        if len(matches) != 1:
            fail(f'{label}“{name}”不存在或有歧义，请使用 #编号。')
        by_name = matches[0]
    if by_name is not None and by_index is not None and by_name['index'] != by_index['index']:
        fail(f'{label}名称与编号指向不同对象，请重新选择。')
    chosen = by_name if by_name is not None else by_index
    if chosen is None:
        fail(f'请选择{label}名称或 #编号。')
    if chosen.get('selectable') is False:
        fail(f'{label}“{chosen["name"]}”不可选：{chosen["reason"]}')
    return chosen


def display_sample(value: Any, limit: int = 60) -> str:
    text = str(value)
    return text if len(text) <= limit else text[:limit - 1] + '…'


def column_option(profile: dict) -> dict:
    kind, unique = profile['effective_kind'], profile['unique']
    reason = {'id': '疑似标识符；核对业务定义后可显式修正类型。',
              'empty': '整列为空。', 'text': '高基数文本，需先按业务规则分组或编码。'}.get(kind)
    if reason is None and unique < 2:
        reason = '不足两个有效取值（常量）。'
    suggested, hint = None, None
    if kind == 'numeric' and 1 < unique <= 10:
        suggested, hint = 'categorical', '取值较少；若为类别编码，可确认 categorical 或 ordinal。'
    elif kind == 'id':
        hint = '如实际为测量值，请明确业务含义并覆盖 numeric；不直接以 ID 统计。'
    elif kind == 'categorical' and {str(level['value']) for level in profile['levels']} == {'低', '中', '高'}:
        suggested, hint = 'ordinal', '这些标签可能有业务顺序；确认有序后提供完整顺序。'
    return {**profile, 'selectable': reason is None, 'reason': reason,
            'suggested_kind': suggested, 'semantic_hint': hint}


def resolve_column(options: list[dict], *, name: str | None, index: int | None, label: str) -> dict:
    # Original names take precedence over generated display aliases. Ambiguous
    # source headers must be selected by physical index.
    if name is not None and not re.fullmatch(r'#[0-9]+', name):
        originals = [option for option in options if option['original_name'] == name]
        folded = [option for option in options if option['original_name'] is not None
                  and option['original_name'].casefold() == name.casefold()]
        matches = originals or folded
        if matches:
            if len(matches) != 1:
                raise SelectionError(f'{label}“{name}”有重名或大小写歧义，请使用 #编号。',
                                     step='needs_columns', options=options)
            if index is not None and matches[0]['index'] != index:
                raise SelectionError(f'{label}名称与编号指向不同字段。', step='needs_columns', options=options)
            return matches[0]
    # Applicability is checked after explicit type overrides, not at lookup.
    identities = [{**option, 'selectable': True} for option in options]
    chosen = resolve_option(identities, name=name, index=index, label=label, step='needs_columns')
    return next(option for option in options if option['index'] == chosen['index'])
