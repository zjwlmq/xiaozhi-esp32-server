"""Built-in context capabilities. No network access or changes to source memory."""
from datetime import datetime, timedelta
import json
import re


def optimize_memory(memory, query, settings):
    if not isinstance(memory, str) or not memory:
        return memory
    limit = int(settings.get('max_characters', 4000))
    # Preserve whole paragraphs, including dates and negation. Do not manufacture summaries.
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n|\n', memory) if p.strip()]
    if settings.get('deduplicate', True):
        seen, unique = set(), []
        for p in paragraphs:
            normalized = re.sub(r'\s+', ' ', p)
            if normalized not in seen:
                seen.add(normalized)
                unique.append(p)
        paragraphs = unique
    if sum(len(p) + 1 for p in paragraphs) <= limit:
        return '\n'.join(paragraphs)
    words = set(re.findall(r'[a-z0-9]{2,}|[\u4e00-\u9fff]{2,}', (query or '').lower()))
    for word in list(words):
        if re.search(r'[\u4e00-\u9fff]', word):
            words.update(word[i:i+2] for i in range(len(word)-1))
    ranked = sorted(enumerate(paragraphs), key=lambda row: (-sum(w in row[1].lower() for w in words), row[0]))
    selected, size = [], 0
    for index, paragraph in ranked:
        if size + len(paragraph) + 1 <= limit:
            selected.append((index, paragraph))
            size += len(paragraph) + 1
    return '\n'.join(p for _, p in sorted(selected))


def holiday_context(now, settings, lunar_factory=None):
    solar = {(1, 1): '元旦', (5, 1): '劳动节', (10, 1): '国庆节'}
    lunar_names = {(1, 1): '春节', (1, 15): '元宵节', (5, 5): '端午节', (7, 7): '七夕', (8, 15): '中秋节', (9, 9): '重阳节', (12, 8): '腊八节'}
    if lunar_factory is None:
        try:
            from cnlunar import Lunar
            lunar_factory = Lunar
        except ImportError:
            pass
    overrides = {item['date']: item for item in settings.get('calendar', [])}
    days = []
    lunar_available = lunar_factory is not None
    for offset in range(int(settings.get('lookahead_days', 3)) + 1):
        day = now.date() + timedelta(days=offset)
        names = []
        if (day.month, day.day) in solar:
            names.append(solar[(day.month, day.day)])
        if lunar_factory:
            try:
                lunar = lunar_factory(datetime(day.year, day.month, day.day, 12), godType='8char')
                if not lunar.isLunarLeapMonth:
                    name = lunar_names.get((lunar.lunarMonth, lunar.lunarDay))
                    if name: names.append(name)
                if lunar.todaySolarTerms == '清明': names.append('清明节')
            except (ValueError, IndexError, AttributeError):
                lunar_available = False
        override = overrides.get(day.isoformat())
        if names or override or offset == 0:
            days.append({'date': day.isoformat(), 'days_from_today': offset, 'festivals': names,
                         'calendar_name': override.get('name') if override else None,
                         'is_day_off': override['is_day_off'] if override else None,
                         'schedule_source': 'configured_calendar' if override else 'unknown'})
    return {'days': days, 'lunar_calendar_available': lunar_available,
            'rule': '节日不等于本人休假。is_day_off为空时，休假与调休安排未知；不能凭周末或节日断言不用上班。'}


def in_quiet_hours(now, start, end):
    current = now.strftime('%H:%M')
    if start == end:
        return False
    return start <= current < end if start < end else current >= start or current < end
