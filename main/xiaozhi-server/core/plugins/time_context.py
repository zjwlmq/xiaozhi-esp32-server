"""Persistent, per-conversation time context for a future QQ/Xiaozhi adapter.

This module records live interaction metadata only. Import historical chats into
a separate knowledge store; their latest date is not a live conversation event.
"""
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
from pathlib import Path
import json
import sqlite3
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC = timezone.utc
WEEKDAYS = ('星期一', '星期二', '星期三', '星期四', '星期五', '星期六', '星期日')


def get_timezone(name='Asia/Shanghai'):
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        # Current mainland China has UTC+8 year round. No dependency on the
        # Windows/Linux host timezone or an installed tzdata package is needed.
        if name in ('Asia/Shanghai', 'Asia/Hong_Kong', 'Asia/Taipei'):
            return timezone(timedelta(hours=8), name)
        if name == 'UTC':
            return UTC
        raise ValueError(f'Unknown timezone: {name}')


def aware(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('An offset-aware datetime is required; naive local times are ambiguous.')
    return value.astimezone(UTC)


def resolve_relative_day(word, message_at, timezone_name='Asia/Shanghai'):
    """Resolve a bounded date word against the message's date, not today's date."""
    offsets = {'前天': -2, '昨天': -1, '今天': 0, '明天': 1, '后天': 2}
    if word not in offsets:
        raise ValueError('Unsupported relative date; keep it unresolved.')
    day = aware(message_at).astimezone(get_timezone(timezone_name)).date()
    return (day + timedelta(days=offsets[word])).isoformat()


def elapsed_label(seconds):
    if seconds is None:
        return '未知（尚无本机器人此前的互动记录）'
    if seconds < 60:
        return f'{int(seconds)}秒'
    if seconds < 3600:
        return f'{int(seconds // 60)}分钟'
    if seconds < 86400:
        hours, minutes = divmod(int(seconds // 60), 60)
        return f'{hours}小时{minutes}分钟'
    days, hours = divmod(int(seconds // 3600), 24)
    return f'{days}天{hours}小时'


class TimeContextStore:
    def __init__(self, db_path, timezone_name='Asia/Shanghai', clock=None):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.timezone_name = timezone_name
        self.tz = get_timezone(timezone_name)
        self.clock = clock or (lambda: datetime.now(UTC))
        with self._connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS interactions (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_key TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                    event_at REAL NOT NULL,
                    received_at REAL NOT NULL,
                    previous_interaction_at REAL,
                    previous_user_at REAL,
                    previous_reply_at REAL,
                    out_of_order INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(conversation_key, role, event_id)
                );
                CREATE INDEX IF NOT EXISTS interactions_by_time
                    ON interactions(conversation_key, event_at DESC, seq DESC);
            ''')

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def _now(self):
        return aware(self.clock())

    @staticmethod
    def _key(value):
        if not isinstance(value, str) or not value.strip() or len(value) > 512:
            raise ValueError('Conversation/event IDs must be nonempty strings up to 512 characters.')
        return value

    def _record(self, conversation_key, event_id, role, event_at=None):
        conversation_key, event_id = self._key(conversation_key), self._key(event_id)
        now = self._now()
        explicit = event_at is not None
        stamp = aware(event_at) if explicit else now
        if stamp > now + timedelta(minutes=5):
            raise ValueError('Event timestamp is in the future; check the transport/server clock.')
        at = stamp.timestamp()
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT * FROM interactions WHERE conversation_key=? AND role=? AND event_id=?', (conversation_key, role, event_id)).fetchone()
            if existing is not None:
                if explicit and abs(existing['event_at'] - at) > .001:
                    raise ValueError('Retry has a different timestamp for the same event.')
                return dict(existing)
            latest = db.execute('SELECT MAX(event_at) FROM interactions WHERE conversation_key=?', (conversation_key,)).fetchone()[0]

            def previous(target_role=None):
                sql = 'SELECT MAX(event_at) FROM interactions WHERE conversation_key=? AND event_at<=?'
                params = [conversation_key, at]
                if target_role:
                    sql += ' AND role=?'
                    params.append(target_role)
                return db.execute(sql, params).fetchone()[0]

            db.execute('''INSERT INTO interactions
                (conversation_key,event_id,role,event_at,received_at,previous_interaction_at,previous_user_at,previous_reply_at,out_of_order)
                VALUES (?,?,?,?,?,?,?,?,?)''',
                (conversation_key,event_id,role,at,now.timestamp(),previous(),previous('user'),previous('assistant'),int(latest is not None and at < latest)))
            return dict(db.execute('SELECT * FROM interactions WHERE conversation_key=? AND role=? AND event_id=?', (conversation_key,role,event_id)).fetchone())

    def observe_user_message(self, conversation_key, event_id, event_at=None):
        """Call once per incoming message; retries with the same ID are idempotent."""
        self._record(conversation_key, event_id, 'user', event_at)
        return self.for_turn(conversation_key, event_id)

    def record_reply_sent(self, conversation_key, event_id, event_at=None):
        """Call only after the transport confirms the reply was actually sent."""
        return self._record(conversation_key, event_id, 'assistant', event_at)

    def for_turn(self, conversation_key, user_event_id):
        """Refresh the current clock while preserving this turn's original gap."""
        with self._connect() as db:
            row = db.execute('SELECT * FROM interactions WHERE conversation_key=? AND role=? AND event_id=?', (conversation_key,'user',user_event_id)).fetchone()
        if row is None:
            raise KeyError('Observe the incoming message before building its time context.')
        now = self._now().astimezone(self.tz)
        sent = datetime.fromtimestamp(row['event_at'], self.tz)

        def local(value):
            return datetime.fromtimestamp(value,self.tz).isoformat(timespec='seconds') if value is not None else None

        previous = row['previous_interaction_at']
        gap = max(0, row['event_at'] - previous) if previous is not None else None
        day_gap = (sent.date() - datetime.fromtimestamp(previous,self.tz).date()).days if previous is not None else None
        hour = now.hour
        period = '凌晨' if hour < 5 else '清晨' if hour < 8 else '上午' if hour < 11 else '中午' if hour < 14 else '下午' if hour < 18 else '晚上'
        return {
            'timezone': self.timezone_name, 'now': now.isoformat(timespec='seconds'),
            'weekday': WEEKDAYS[now.weekday()], 'period': period,
            'today': now.date().isoformat(), 'yesterday': (now.date()-timedelta(days=1)).isoformat(),
            'tomorrow': (now.date()+timedelta(days=1)).isoformat(),
            'user_message_at': sent.isoformat(timespec='seconds'),
            'message_date_reference': sent.date().isoformat(),
            'previous_interaction_at': local(previous),
            'previous_user_message_at': local(row['previous_user_at']),
            'previous_sent_reply_at': local(row['previous_reply_at']),
            'elapsed_since_previous_interaction_seconds': gap,
            'elapsed_since_previous_interaction': elapsed_label(gap),
            'calendar_days_since_previous_interaction': day_gap,
            'first_recorded_live_interaction': previous is None and not row['out_of_order'],
            'out_of_order_delivery': bool(row['out_of_order']),
            'seconds_since_this_message': max(0, now.timestamp()-row['event_at']),
            'clock_skew_seconds': max(0, row['event_at']-now.timestamp()),
            'history_imported_as_live_interaction': False,
        }

    def build_system_prompt(self, persona_text, conversation_key, user_event_id, dated_memory_text=''):
        policy = (Path(__file__).parent/'time_awareness.md').read_text(encoding='utf-8')
        context = json.dumps(self.for_turn(conversation_key,user_event_id),ensure_ascii=False,indent=2)
        memory = '\n\n<dated_historical_memory>\n'+dated_memory_text+'\n</dated_historical_memory>' if dated_memory_text else ''
        return persona_text.rstrip()+'\n\n'+policy.strip()+'\n\n<time_context>\n'+context+'\n</time_context>'+memory


def describe_plan(due_at, status, now, timezone_name='Asia/Shanghai'):
    """An elapsed due date is not evidence that a plan happened."""
    if status in ('completed','cancelled'):
        return '已确认完成' if status == 'completed' else '已取消'
    if status != 'planned':
        return '状态未确认'
    if due_at is None:
        return '已约定，日期未明确，完成情况未确认'
    due = aware(due_at).astimezone(get_timezone(timezone_name))
    return '计划时间已过，完成情况未确认' if due < aware(now) else '已约定，尚未确认完成'
