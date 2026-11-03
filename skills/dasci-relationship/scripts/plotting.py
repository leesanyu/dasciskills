"""Pure plotting plans; axis intent never reorders statistical inputs."""
from __future__ import annotations

PLOT_X_CHOICES = ('auto', 'col1', 'col2')
DISCRETE = {'boolean', 'categorical', 'ordinal'}


def axis(column: dict, slot: int, feature: str | None = None, label: str | None = None) -> dict:
    return {'slot': f'col{slot+1}', 'column_index': column['index'],
            'label': column['display_name'] if label is None else label, 'feature': feature}


def resolve_plan(columns: list[dict], requested_x: str = 'auto') -> dict:
    """Resolve already validated field semantics without inspecting values or statistics."""
    assert requested_x in PLOT_X_CHOICES
    kinds = [column['effective_kind'] for column in columns]
    if all(kind in DISCRETE for kind in kinds):
        kind, default_x, source = 'heatmap', 0, 'slot_default'
    elif any(kind in DISCRETE for kind in kinds):
        measure = 1 if kinds[0] in DISCRETE else 0
        kind = 'timeline' if kinds[measure] == 'datetime' else 'box'
        default_x, source = measure, 'type_default'
    elif kinds.count('datetime') == 1:
        kind, default_x, source = 'scatter', kinds.index('datetime'), 'type_default'
    else:
        kind, default_x, source = 'scatter', 0, 'slot_default'
    x = default_x if requested_x == 'auto' else int(requested_x[-1])-1
    return {'requested_x': requested_x, 'kind': kind,
            'x': axis(columns[x], x), 'y': axis(columns[1-x], 1-x),
            'source': source if requested_x == 'auto' else 'explicit'}
