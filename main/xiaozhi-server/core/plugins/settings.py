"""Shared manifest interpretation and defensive validation of runtime settings."""
from copy import deepcopy
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit
import json
import re

CATALOG = json.loads((Path(__file__).parent / 'catalog.json').read_text(encoding='utf-8'))
MANIFESTS = {item['id']: item for item in CATALOG['plugins']}


def defaults(plugin_id):
    return {f['key']: deepcopy(f['default']) for f in MANIFESTS[plugin_id]['fields']}


def normalize(states):
    result = {}
    if not isinstance(states, dict): raise ValueError('插件配置必须是对象')
    for plugin_id, item in states.items():
        if plugin_id not in MANIFESTS: raise ValueError('未知插件')
        if not isinstance(item, dict) or type(item.get('enabled', False)) is not bool:
            raise ValueError('插件开关必须为布尔值')
        supplied = item.get('settings', {})
        if not isinstance(supplied, dict): raise ValueError('插件设置必须是对象')
        config = defaults(plugin_id)
        fields = {f['key']: f for f in MANIFESTS[plugin_id]['fields']}
        if supplied.keys() - fields.keys(): raise ValueError('未知配置字段')
        for key, value in supplied.items():
            field, kind = fields[key], fields[key]['type']
            if kind == 'integer':
                if type(value) is not int or not field['min'] <= value <= field['max']: raise ValueError('数值配置超出范围')
            elif kind == 'boolean':
                if type(value) is not bool: raise ValueError('布尔配置无效')
            elif kind == 'json':
                if not isinstance(value, list) or len(value) > 800: raise ValueError('日历格式无效')
                dates = set()
                for day in value:
                    if not isinstance(day, dict) or set(day) - {'date','name','is_day_off'}: raise ValueError('日历字段无效')
                    stamp = date.fromisoformat(day.get('date', ''))
                    if stamp.isoformat() in dates: raise ValueError('日历日期重复')
                    dates.add(stamp.isoformat())
                    if type(day.get('is_day_off')) is not bool or not isinstance(day.get('name',''),str) or len(day.get('name','')) > 80: raise ValueError('日历安排无效')
            else:
                if not isinstance(value, str) or len(value) > field.get('maxLength', 2048): raise ValueError('文本配置无效')
                if kind == 'select' and value not in field['options']: raise ValueError('选项无效')
                if kind == 'time' and not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value): raise ValueError('时间格式无效')
                if kind == 'url' and value:
                    url = urlsplit(value)
                    if url.scheme not in ('http','https') or not url.hostname or url.username or url.password or url.fragment or url.query: raise ValueError('接口地址无效')
            config[key] = deepcopy(value)
        result[plugin_id] = {'enabled': item.get('enabled', False), 'settings': config}
    for plugin_id, state in result.items():
        if state['enabled']:
            if any(not result.get(dep, {}).get('enabled') for dep in MANIFESTS[plugin_id]['dependencies']):
                raise ValueError('依赖插件尚未启用')
    return result


def missing_fields(plugin_id, config):
    return [f['label'] for f in MANIFESTS[plugin_id]['fields'] if f.get('required') and not str(config.get(f['key'], '')).strip()]
