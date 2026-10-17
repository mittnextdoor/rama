"""The engine's wording, as an accountant reads it (docs/89 U0). The engine writes amounts in cents and dates in ISO form
inside its messages ("WIRE OUT 88213 (-45000 on 2025-01-22): nothing says what this is"). Screens show them the way a
workpaper does: amounts with two decimals and negatives in parentheses, dates as MM/DD/YYYY ("WIRE OUT 88213,
01/22/2025, (450.00): nothing says what this is"). Applied when the text is read, never to what's stored, so matching
on stored text is unchanged."""
import re

_CENTS_ON = re.compile(r"\s*\((-?\d+) on (\d{4})-(\d{2})-(\d{2})\)")
_ISO = re.compile(r"(?<![\d-])(\d{4})-(\d{2})-(\d{2})(?![\d-])")
_MONTH = re.compile(r"(?<![\d/-])(\d{4})-(\d{2})(?![\d/-])")
_NEG = re.compile(r"(?<![\w.,(])-(\d{1,3}(?:,\d{3})*\.\d{2})(?![\d])")


def money(cents):
    """1234567 -> 12,345.67; -45000 -> (450.00)."""
    if cents is None:
        return ""
    c = int(cents)
    return f"({abs(c) / 100:,.2f})" if c < 0 else f"{c / 100:,.2f}"


def date(iso):
    s = str(iso or "")[:10]
    return f"{s[5:7]}/{s[8:10]}/{s[:4]}" if len(s) == 10 and s[4] == "-" else s


def text(s):
    """A message with its cents and ISO dates in the accounting format."""
    if not s:
        return s
    out = _CENTS_ON.sub(lambda m: f", {m.group(3)}/{m.group(4)}/{m.group(2)}, {money(int(m.group(1)))}", str(s))
    out = _ISO.sub(lambda m: f"{m.group(2)}/{m.group(3)}/{m.group(1)}", out)
    out = _MONTH.sub(lambda m: f"{m.group(2)}/{m.group(1)}", out)
    return _NEG.sub(lambda m: f"({m.group(1)})", out)
