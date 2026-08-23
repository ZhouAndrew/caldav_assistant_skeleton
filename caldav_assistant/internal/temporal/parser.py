from __future__ import annotations
import re
from datetime import date, datetime, time, timedelta
from ...api.v1.errors import ValidationError

_MONTHS={name.lower():i for i,names in enumerate([
    (),('january','jan'),('february','feb'),('march','mar'),('april','apr'),('may',),('june','jun'),('july','jul'),('august','aug'),('september','sep','sept'),('october','oct'),('november','nov'),('december','dec')
]) for name in names}
_WEEKDAYS={'monday':0,'mon':0,'tuesday':1,'tue':1,'tues':1,'wednesday':2,'wed':2,'thursday':3,'thu':3,'thur':3,'thurs':3,'friday':4,'fri':4,'saturday':5,'sat':5,'sunday':6,'sun':6}

class TemporalParser:
    def __init__(self, now_provider=None, today_provider=None, now=None):
        if now is not None:
            self._now_provider=lambda: now if isinstance(now,datetime) else datetime.combine(now,time())
        elif now_provider is not None: self._now_provider=now_provider
        elif today_provider is not None: self._now_provider=lambda: datetime.combine(today_provider(),time())
        else: self._now_provider=datetime.now
    def _now(self):
        value=self._now_provider()
        return value if isinstance(value,datetime) else datetime.combine(value,time())
    def parse_date(self, text: str, *, bias: str='any', reference=None) -> date:
        if bias not in {'any','future','past'}: raise ValidationError("bias must be one of: any, future, past")
        if not isinstance(text,str) or not text.strip(): raise ValidationError("date text must be non-empty")
        s=' '.join(text.strip().split()).lower()
        ref = reference or self._now()
        today = ref.date() if isinstance(ref,datetime) else ref
        if s=='today': return today
        if s=='tomorrow': return today+timedelta(days=1)
        if s=='yesterday': return today-timedelta(days=1)
        try: return date.fromisoformat(s)
        except ValueError: pass
        m=re.fullmatch(r'(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?',s)
        if m:
            month,day,year=int(m.group(1)),int(m.group(2)),m.group(3)
            y=int(year) if year else today.year
            if year and y<100: y+=2000
            return self._apply_bias(date(y,month,day), bool(year), today, bias)
        m=re.fullmatch(r'([a-z]+)\s*(\d{1,2})(?:\s*,?\s*(\d{4}))?',s)
        if m and m.group(1) in _MONTHS:
            y=int(m.group(3)) if m.group(3) else today.year
            return self._apply_bias(date(y,_MONTHS[m.group(1)],int(m.group(2))), bool(m.group(3)), today,bias)
        # weekday / next weekday
        next_prefix=s.startswith('next ')
        wd=s[5:] if next_prefix else s
        if wd in _WEEKDAYS:
            delta=(_WEEKDAYS[wd]-today.weekday())%7
            if next_prefix: delta = delta + 7 if delta else 7
            elif bias=='future' and delta==0: delta=7
            elif bias=='past':
                back=(today.weekday()-_WEEKDAYS[wd])%7
                if back==0: back=7
                return today-timedelta(days=back)
            return today+timedelta(days=delta)
        raise ValidationError(f"Unrecognized date: {text}")
    @staticmethod
    def _apply_bias(candidate, explicit_year, today, bias):
        if explicit_year or bias=='any': return candidate
        if bias=='future' and candidate<today: return candidate.replace(year=candidate.year+1)
        if bias=='past' and candidate>today: return candidate.replace(year=candidate.year-1)
        return candidate
    def parse_time(self,text: str) -> time:
        s=text.strip().lower()
        for fmt in ('%H:%M','%H:%M:%S','%I:%M %p','%I %p'):
            try:return datetime.strptime(s,fmt).time()
            except ValueError: pass
        raise ValidationError(f"Unrecognized time: {text}")
    def parse_datetime(self,text: str, *, bias: str='any', reference=None) -> datetime:
        s=' '.join(text.strip().split())
        try:return datetime.fromisoformat(s)
        except ValueError: pass
        # split trailing time from human date
        m=re.fullmatch(r'(.+?)\s+(\d{1,2}:\d{2}(?::\d{2})?(?:\s*[ap]m)?)',s,re.I)
        if m:
            d=self.parse_date(m.group(1),bias=bias,reference=reference); t=self.parse_time(m.group(2)); return datetime.combine(d,t)
        d=self.parse_date(s,bias=bias,reference=reference)
        return datetime.combine(d,time())
