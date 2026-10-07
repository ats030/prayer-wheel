"""User requests are search priorities, never historical evidence or shared gold."""
import re
import unicodedata
from urllib.parse import urlsplit

MAX_MILESTONES = 12


def normalize(items):
    if not isinstance(items, list) or len(items) > MAX_MILESTONES:
        raise ValueError(f"主要項目は{MAX_MILESTONES}件以内で指定してください。")
    cleaned, names = [], set()
    for item in items:
        if not isinstance(item, dict) or set(item) - {'name', 'year', 'note', 'url'}:
            raise ValueError("主要項目の形式が不正です。")
        values = {}
        for key, limit in [('name', 120), ('note', 300), ('url', 1000)]:
            value = item.get(key, '')
            if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 for c in value):
                raise ValueError("主要項目の文字数または形式を確認してください。")
            values[key] = value.strip()
        if not key_text(values['name']) or key_text(values['name']) in names:
            raise ValueError("主要項目の名前は空欄・重複にできません。")
        names.add(key_text(values['name']))
        year = item.get('year')
        if year is not None and (type(year) is not int or year == 0 or not -9999 <= year <= 9999):
            raise ValueError("年代は西暦の整数で指定してください。紀元前は負数です。")
        values['year'] = year
        if values['url']:
            try:
                p = urlsplit(values['url'])
                valid = p.scheme in {'http', 'https'} and p.hostname and not p.username and not p.password and p.port in {None, 80, 443}
            except ValueError:
                valid = False
            if not valid:
                raise ValueError("参考URLはHTTPまたはHTTPSの公開ページを指定してください。")
        cleaned.append(values)
    return cleaned


def key_text(text):
    return re.sub(r'[\W_]+', '', unicodedata.normalize('NFKC', text).casefold())


def matches(item, event):
    # This deliberately conservative lexical signal is labelled as such in the UI.
    return (item.get('year') is None or item['year'] == event.get('year')) and key_text(item['name']) in key_text(event.get('title', '') + ' ' + event.get('description', ''))


def report(items, result):
    events = result.get('events', [])
    snapshot = result.get('requested_milestones', [])
    rows = []
    for item in items:
        hits = [i for i, event in enumerate(events) if matches(item, event)]
        if hits:
            status, reason = 'found', '名前・指定年に一致する項目があります。内容と出典も確認してください。'
        elif item.get('year') is not None and any(matches(dict(item, year=None), event) for event in events):
            status = 'mismatch'
            years = sorted({event['year'] for event in events if matches(dict(item, year=None), event)})
            reason = '名前が一致する項目の出典上の年は' + '・'.join(str(year) + '年' for year in years) + 'です。指定年と内容を確認してください。'
        elif item not in snapshot:
            status, reason = 'pending', 'この指定は保存結果の生成時にはありませんでした。再生成で調べます。'
        else:
            status = 'missing'
            reason = '名前・指定年が一致する項目を確認できません。別表記や、資料・候補生成・照合での欠落も考えられます。'
            rejected = [r for r in (result.get('trace') or {}).get('rejected', []) if matches(item, r)]
            if rejected:
                reason = '一致する候補は採用されませんでした：' + str(rejected[0].get('reason', '照合を通過しませんでした。'))
            if result.get('stop_reason') == 'time_limit':
                reason += '時間上限で調査を打ち切りました。'
        rows.append(dict(item, status=status, reason=reason, event_indexes=hits))
    return rows
