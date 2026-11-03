"""Shipped visual tokens shared by the HTML template and Pillow charts."""
import hashlib
import json
from pathlib import Path

ASSETS=Path(__file__).resolve().parents[1]/'assets'
THEME=json.loads((ASSETS/'theme.json').read_text(encoding='utf-8'))
TEMPLATE=THEME['template']


def rgb(value):
    return tuple(int(value[i:i+2],16) for i in (1,3,5))


def category_color(label):
    index=int.from_bytes(hashlib.sha256(str(label).encode()).digest()[:4],'big')%len(THEME['palette'])
    return rgb(THEME['palette'][index])


def css_variables():
    variables=dict(THEME['colors'])
    variables.update({'font-family':THEME['font_family'], 'font-size':f'{THEME["layout"]["font_size"]}px',
                      'line-height':THEME['layout']['line_height'],'max-width':f'{THEME["layout"]["max_width"]}px',
                      'radius':f'{THEME["layout"]["radius"]}px','space':f'{THEME["layout"]["space"]}px'})
    return ':root{'+''.join(f'--{key}:{value};' for key,value in variables.items())+'}'
