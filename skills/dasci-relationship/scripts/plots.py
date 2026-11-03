"""Optional Pillow charts using the report theme; unexpected errors propagate."""

from __future__ import annotations

import math
from functools import lru_cache

import theme
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Sequence

import numpy as np

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # optional image dependency
    Image = ImageDraw = ImageFont = None


WIDTH, HEIGHT = theme.THEME["chart"]["width"], theme.THEME["chart"]["height"]
MARGIN_LEFT, MARGIN_RIGHT, MARGIN_TOP, MARGIN_BOTTOM = 100, 40, 70, 80
PLOT_W = WIDTH - MARGIN_LEFT - MARGIN_RIGHT
PLOT_H = HEIGHT - MARGIN_TOP - MARGIN_BOTTOM
COLORS = [theme.rgb(color) for color in theme.THEME['palette']]
category_color = theme.category_color
TEXT = theme.rgb(theme.THEME['colors']['text'])
MUTED = theme.rgb(theme.THEME['colors']['muted'])
GRID = theme.rgb(theme.THEME['colors']['border'])
PRIMARY = theme.rgb(theme.THEME['colors']['primary'])


class ChartUnavailable(RuntimeError):
    """An expected missing font or image dependency, reported in both formats."""


@lru_cache(maxsize=32)
def _font(size: int):
    for candidate in theme.THEME['font_paths']:
        if Path(candidate).is_file():
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue
    raise ChartUnavailable('没有可显示中文的字体；请安装微软雅黑、PingFang SC 或 Noto Sans CJK SC。')


def _text(draw, xy, text, fill=TEXT, size=18, anchor=None):
    font = _font(size)
    draw.text(xy, str(text), fill=fill, font=font, anchor=anchor)


def _date_label(days: float) -> str:
    try:
        return (datetime(1970, 1, 1) + timedelta(days=float(days))).strftime("%Y-%m")
    except (ValueError, OverflowError):
        return _fmt(days)


def _fmt(value: float) -> str:
    if value == 0:
        return "0"
    magnitude = abs(value)
    if magnitude >= 1e5 or magnitude < 1e-3:
        return f"{value:.2e}"
    if magnitude >= 100:
        return f"{value:.0f}"
    if magnitude >= 10:
        return f"{value:.1f}"
    return f"{value:.3g}"


def _new_image(title: str):
    image = Image.new("RGB", (WIDTH, HEIGHT), "white")
    draw = ImageDraw.Draw(image)
    _text(draw, (MARGIN_LEFT, 22), _short(title, 32), fill=TEXT, size=24)
    return image, draw


def _axes(image, draw, x_label: str, y_label: str, x_range, y_range,
          x_formatter: Callable[[float], str] | None = None,
          y_formatter: Callable[[float], str] | None = None,
          show_y_ticks: bool = True, show_x_ticks: bool = True, left: int = MARGIN_LEFT):
    x0, x1 = x_range
    y0, y1 = y_range
    if x1 == x0:
        x1 = x0 + 1
    if y1 == y0:
        y1 = y0 + 1
    plot_w = WIDTH-left-MARGIN_RIGHT
    for i in range(6):
        x = left + plot_w*i/5
        y = MARGIN_TOP + PLOT_H*i/5
        draw.line([(x, MARGIN_TOP), (x, MARGIN_TOP+PLOT_H)], fill=GRID, width=1)
        draw.line([(left, y), (left+plot_w, y)], fill=GRID, width=1)
        if show_x_ticks:
            value = x0+(x1-x0)*i/5
            _text(draw, (x, MARGIN_TOP+PLOT_H+8), x_formatter(value) if x_formatter else _fmt(value),
                  fill=MUTED, size=14, anchor='ma')
        if show_y_ticks:
            value = y1-(y1-y0)*i/5
            _text(draw, (left-8, y), y_formatter(value) if y_formatter else _fmt(value),
                  fill=MUTED, size=14, anchor='rm')
    draw.rectangle([left, MARGIN_TOP, left+plot_w, MARGIN_TOP+PLOT_H], outline=GRID, width=1)
    _text(draw, (left+plot_w/2, HEIGHT-30), x_label, size=18, anchor='ma')
    label_img = Image.new('RGBA', (260, 32), (255, 255, 255, 0))
    _text(ImageDraw.Draw(label_img), (0, 0), y_label, size=18)
    rotated = label_img.rotate(90, expand=True)
    image.paste(rotated, (8, MARGIN_TOP+PLOT_H//2-rotated.height//2), rotated)


def _save_axes(image, path, x_label, y_label, note=''):
    """Keep complete field identities in standalone PNGs, wrapping by measured width."""
    font = _font(16)
    lines = []
    for value in ['横轴：'+x_label, '纵轴：'+y_label]+([note] if note else []):
        line = ''
        for char in value:
            if line and font.getlength(line+char) > WIDTH-64:
                lines.append(line)
                line = ''
            line += char
        lines.append(line)
    canvas = Image.new('RGB', (WIDTH, image.height+24+24*len(lines)), 'white')
    canvas.paste(image, (0, 0))
    draw = ImageDraw.Draw(canvas)
    for i, line in enumerate(lines):
        _text(draw, (32, image.height+8+i*24), line, fill=MUTED, size=16)
    canvas.save(path)
    return str(path)


def _scale(value, lo, hi, start, size):
    if hi == lo:
        return start + size / 2
    return start + (value - lo) / (hi - lo) * size


def scatter(x: Sequence[float], y: Sequence[float], x_label: str, y_label: str,
            path: str | Path, title: str | None = None,
            x_date: bool = False, y_date: bool = False) -> str | None:
    if Image is None:
        return None
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.size == 0 or x.size != y.size:
        return None
    if x.size > 5000:
        idx = np.linspace(0, x.size - 1, 5000).astype(int)
        xs, ys = x[idx], y[idx]
    else:
        xs, ys = x, y
    x_pad = (x.max() - x.min()) * 0.05 or 0.5
    y_pad = (y.max() - y.min()) * 0.05 or 0.5
    x0, x1 = x.min() - x_pad, x.max() + x_pad
    y0, y1 = y.min() - y_pad, y.max() + y_pad
    image, draw = _new_image(title or "散点图")
    _axes(image, draw, _short(x_label), _short(y_label, 14), (x0, x1), (y0, y1),
          x_formatter=_date_label if x_date else None,
          y_formatter=_date_label if y_date else None)
    for xv, yv in zip(xs, ys):
        px = _scale(xv, x0, x1, MARGIN_LEFT, PLOT_W)
        py = _scale(yv, y0, y1, MARGIN_TOP + PLOT_H, -PLOT_H)
        draw.ellipse([px - 3, py - 3, px + 3, py + 3], fill=PRIMARY)
    if x.size >= 3 and np.std(x) > 0:
        slope, intercept = np.polyfit(x, y, 1)
        xa, xb = x.min(), x.max()
        ya, yb = slope * xa + intercept, slope * xb + intercept
        p1 = (_scale(xa, x0, x1, MARGIN_LEFT, PLOT_W), _scale(ya, y0, y1, MARGIN_TOP + PLOT_H, -PLOT_H))
        p2 = (_scale(xb, x0, x1, MARGIN_LEFT, PLOT_W), _scale(yb, y0, y1, MARGIN_TOP + PLOT_H, -PLOT_H))
        draw.line([p1, p2], fill=MUTED, width=2)
    if x.size > 5000:
        _text(draw, (MARGIN_LEFT + 8, MARGIN_TOP + 8), f"显示 {min(5000, x.size):,} / {x.size:,} 个点",
              fill=MUTED, size=14)
    return _save_axes(image,path,x_label,y_label)


def boxplot(groups: Sequence[Sequence[float]], labels: Sequence[str], x_label: str,
            path: str | Path, title: str | None = None, max_groups: int = 15, *,
            y_label: str, orientation: str) -> str | None:
    if Image is None:
        return None
    assert orientation in {'horizontal', 'vertical'}
    pairs = [(str(label), np.asarray(group, dtype=float)) for label, group in zip(labels, groups)]
    pairs = [(label, arr) for label, arr in pairs if arr.size > 0][:max_groups]
    if not pairs:
        return None
    values = np.concatenate([arr for _, arr in pairs])
    low, high = float(values.min()), float(values.max())
    pad = (high-low)*.05 or .5
    low, high = low-pad, high+pad
    horizontal = orientation == 'horizontal'
    image, draw = _new_image(title or '分组箱线图')
    left = 260 if horizontal else MARGIN_LEFT
    plot_w = WIDTH-left-MARGIN_RIGHT
    group_range = (-.5, len(pairs)-.5)
    _axes(image, draw, _short(x_label), _short(y_label, 14),
          (low, high) if horizontal else group_range,
          group_range if horizontal else (low, high),
          show_y_ticks=not horizontal, show_x_ticks=horizontal, left=left)
    step = (PLOT_H if horizontal else plot_w)/len(pairs)

    def point(value, group_pixel):
        if horizontal:
            return (_scale(value, low, high, left, plot_w), group_pixel)
        return (group_pixel, _scale(value, low, high, MARGIN_TOP+PLOT_H, -PLOT_H))

    for i, (label, arr) in enumerate(pairs):
        center = (MARGIN_TOP if horizontal else left)+step*(i+.5)
        q1, med, q3 = np.percentile(arr, [25, 50, 75])
        iqr = q3-q1
        lo, hi = max(arr.min(), q1-1.5*iqr), min(arr.max(), q3+1.5*iqr)
        p1, p2 = point(q1, center-step*.28), point(q3, center+step*.28)
        draw.rectangle([min(p1[0],p2[0]), min(p1[1],p2[1]), max(p1[0],p2[0]), max(p1[1],p2[1])],
                       fill=category_color(label), outline=(50,50,50))
        draw.line([point(med,center-step*.3),point(med,center+step*.3)], fill='white', width=2)
        for value in (lo,hi):
            draw.line([point(value,center-step*.12),point(value,center+step*.12)], fill=(50,50,50))
        draw.line([point(lo,center),point(hi,center)], fill=(50,50,50))
        for value in arr[(arr<lo)|(arr>hi)][:40]:
            x,y = point(value,center)
            draw.ellipse([x-2,y-2,x+2,y+2],fill=(120,120,120))
        if horizontal:
            _text(draw,(left-12,center),_short(label,16),size=14,anchor='rm')
        else:
            _text(draw,(center,MARGIN_TOP+PLOT_H+8),_short(label,max(2,int(step/14)-1)),size=14,anchor='ma')
    return _save_axes(image,path,x_label,y_label)


def heatmap(table: np.ndarray, row_labels: Sequence[str], col_labels: Sequence[str],
            path: str | Path, title: str | None = None, max_cells: int = 14, *,
            x_label: str, y_label: str) -> str | None:
    if Image is None:
        return None
    table = np.asarray(table, dtype=float)
    if table.ndim != 2 or table.size == 0:
        return None
    rows = list(range(min(table.shape[0], max_cells)))
    cols = list(range(min(table.shape[1], max_cells)))
    sub = table[np.ix_(rows, cols)]
    image, draw = _new_image(title or "列联表热图")
    left, top = 260, 130
    right, bottom = 40, 80
    grid_w = WIDTH - left - right
    grid_h = HEIGHT - top - bottom
    cell_w = grid_w / len(cols)
    cell_h = grid_h / len(rows)
    vmax = float(sub.max()) or 1.0
    for j, col in enumerate(cols):
        _text(draw, (left + cell_w * (j + 0.5), top - 18), f"C{col + 1}",
              fill=TEXT, size=12, anchor="ms")
    for i, row in enumerate(rows):
        _text(draw, (left - 10, top + cell_h * (i + 0.5)), _short(row_labels[row], 18),
              fill=TEXT, size=12, anchor="rm")
        for j, col in enumerate(cols):
            value = sub[i, j]
            intensity = value / vmax
            color = tuple(int(255+(component-255)*intensity) for component in PRIMARY)
            x1 = left + cell_w * j
            y1 = top + cell_h * i
            draw.rectangle([x1, y1, x1 + cell_w, y1 + cell_h], fill=color, outline=(255, 255, 255))
            if cell_w > 34 and cell_h > 20:
                _text(draw, (x1 + cell_w / 2, y1 + cell_h / 2), f"{int(value)}",
                      fill=TEXT if intensity < 0.55 else (255, 255, 255), size=12, anchor="mm")
    draw.rectangle([left, top, left + grid_w, top + grid_h], outline=GRID, width=1)
    if table.shape[0] > max_cells or table.shape[1] > max_cells:
        _text(draw, (left, HEIGHT - 32), "仅展示部分类别；检验使用完整表。", fill=MUTED, size=13)
    return _save_axes(image,path,x_label,y_label,'颜色表示记录数；上方 C 编号与报告图注的类别映射对应。')


def timeline(dates: Sequence[float], categories: Sequence[str], x_label: str, y_label: str,
             path: str | Path, title: str | None = None, max_categories: int = 12,
             category_order: Sequence[str] | None = None, time_axis: str = 'x') -> str | None:
    if Image is None:
        return None
    assert time_axis in {'x','y'}
    dates = np.asarray(dates,dtype=float)
    cats = [str(c) for c in categories]
    if dates.size == 0 or dates.size != len(cats):
        return None
    unique = (list(category_order) if category_order is not None else list(dict.fromkeys(cats)))[:max_categories]
    index = {c:i for i,c in enumerate(unique)}
    keep = [(d,index[c]) for d,c in zip(dates,cats) if c in index]
    if not keep:
        return None
    values = np.array([pair[0] for pair in keep])
    pad = (values.max()-values.min())*.05 or .5
    time_range = (values.min()-pad,values.max()+pad)
    category_range = (-.6,max(1,len(unique))-.4)
    horizontal = time_axis == 'x'
    image,draw = _new_image(title or '时间与类别')
    _axes(image,draw,_short(x_label),_short(y_label,14),
          time_range if horizontal else category_range, category_range if horizontal else time_range,
          x_formatter=_date_label if horizontal else None,y_formatter=None if horizontal else _date_label,
          show_y_ticks=not horizontal,show_x_ticks=horizontal)
    for i,cat in enumerate(unique):
        if horizontal:
            pos = _scale(i,*category_range,MARGIN_TOP+PLOT_H,-PLOT_H)
            _text(draw,(MARGIN_LEFT-8,pos),_short(cat,6),size=12,anchor='rm')
        else:
            pos = _scale(i,*category_range,MARGIN_LEFT,PLOT_W)
            _text(draw,(pos,MARGIN_TOP+PLOT_H+8),_short(cat,max(2,int(PLOT_W/max(1,len(unique))/12)-1)),size=12,anchor='ma')
    for value,group in keep:
        if horizontal:
            x = _scale(value,*time_range,MARGIN_LEFT,PLOT_W)
            y = _scale(group,*category_range,MARGIN_TOP+PLOT_H,-PLOT_H)
        else:
            x = _scale(group,*category_range,MARGIN_LEFT,PLOT_W)
            y = _scale(value,*time_range,MARGIN_TOP+PLOT_H,-PLOT_H)
        draw.ellipse([x-4,y-4,x+4,y+4],fill=category_color(unique[group]))
    return _save_axes(image,path,x_label,y_label)


def _short(text: str, limit: int = 28) -> str:
    text = str(text)
    return text if len(text) <= limit else text[: limit - 1] + "…"
