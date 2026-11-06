"""Input guard — prompt-injection detection and PII redaction for free text.

Every free-text field of an expense request (description, employee, category,
id, ...) is untrusted user input that may end up inside an LLM prompt (the
CrewAI engine) or a log line. This module is the checkpoint in front of both:

* **Prompt-injection detection** (OWASP LLM01) — flags instruction overrides
  ("ignore previous instructions"), role overrides ("you are now the
  approver"), system-prompt exfiltration, tool/command smuggling, chat-template
  tokens and hidden Unicode (zero-width / bidi / tag characters). A flagged
  request is never auto-approved: :func:`finance_crew.tools.analyze` turns the
  findings into policy violations, so the shared ``decide()`` guardrail routes
  it to a human, and the reason lands in ``rules_fired`` and the audit trail.
* **PII redaction** (OWASP LLM02 / LLM06 sensitive information disclosure) —
  emails, phone numbers, payment cards (Luhn-checked), IBANs (mod-97-checked)
  and national-ID-like numbers are replaced with typed placeholders before
  text is sent to an LLM or written to logs.

Pure stdlib, deterministic and side-effect free, so it runs identically in
every engine and is exhaustively unit-tested. Pattern lists are intentionally
specific (phrases, not single words) to avoid false positives on ordinary
expense descriptions.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

# Request fields that carry free text (amount / has_receipt are typed).
TEXT_FIELDS = ("id", "employee", "category", "description", "currency", "date")

# Placeholder used when a flagged field must not reach an LLM at all.
WITHHELD = "[withheld: flagged as possible prompt injection]"

# --- Hidden / invisible Unicode ---------------------------------------------
# Zero-width & joiners, word-joiner/invisible operators, BOM, bidi embedding /
# override / isolate controls, soft hyphen, and the Unicode "tag" block (used
# for invisible ASCII smuggling).
_HIDDEN_CHARS = re.compile(
    "[\u00ad\u180e\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff\U000e0000-\U000e007f]"
)

# --- Injection patterns ------------------------------------------------------
_I = re.IGNORECASE
_INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "instruction override",
        re.compile(
            r"\b(ignore|disregard|forget|override|skip|bypass)\b[\s\w,]{0,30}?"
            r"\b(previous|prior|above|earlier|preceding|all|any|your|the|system)\b[\s\w]{0,20}?"
            r"\b(instructions?|prompts?|rules|directions|guidelines|guardrails?|polic(y|ies)|context)\b",
            _I,
        ),
    ),
    (
        "instruction override",
        re.compile(r"\b(new|updated|revised)\s+(system\s+)?instructions?\s*:", _I),
    ),
    (
        "role override",
        re.compile(
            r"\b(you\s+are\s+now|from\s+now\s+on,?\s+you|pretend\s+(to\s+be|you\s+are)|"
            r"act\s+as\s+(an?\s+|the\s+)?(admin|administrator|approver|approving\s+manager|"
            r"system|developer|root|finance\s+manager|auditor|unrestricted)|"
            r"(enable|enter|activate)\s+(developer|god|jailbreak|dan)\s+mode|\bjailbreak\b|"
            r"do\s+anything\s+now)",
            _I,
        ),
    ),
    (
        "role override",
        # Chat-template / role markers smuggled into data.
        re.compile(
            r"(<\|?\s*(im_start|im_end|system|assistant|endoftext)\s*\|?>|\[/?(system|inst)\]|"
            r"<<\s*sys\s*>>|^\s*#{2,}\s*(system|instruction)s?\b|^\s*(system|assistant)\s*:)",
            _I | re.MULTILINE,
        ),
    ),
    (
        "system prompt exfiltration",
        re.compile(
            r"\b(reveal|show|print|repeat|output|display|leak|dump|tell\s+me|what\s+(is|are))\b"
            r"[\s\w]{0,25}?\b(system|initial|hidden|original|secret)\s+(prompt|instructions?|message)",
            _I,
        ),
    ),
    (
        "system prompt exfiltration",
        re.compile(
            r"\b(api[\s_-]?key|secret[\s_-]?key|jwt[\s_-]?secret|password|credentials?)\b"
            r"[\s\w]{0,15}?\b(reveal|show|print|send|leak|dump|output)\b|"
            r"\b(reveal|show|print|send|leak|dump|output)\b[\s\w]{0,15}?"
            r"\b(api[\s_-]?key|secret[\s_-]?key|jwt[\s_-]?secret|credentials)\b",
            _I,
        ),
    ),
    (
        "tool/command smuggling",
        re.compile(
            r"(<\s*/?\s*(tool_call|function_call|tool_use|invoke|script)\b|"
            r"\"?(function_call|tool_calls?)\"?\s*:|"
            r"\b(call|invoke|execute)\s+(the\s+|this\s+)?(\w+\s+)?(tool|function|command)\b|"
            r"\brun\s+(the\s+|this\s+)?(shell|command)\b|"
            r"\b(decision|status|verdict)\s*[:=]\s*\"?(auto_?approved|approved)\b|"
            r"\b(mark|set|force)\s+(this|it|the\s+(request|expense|decision))?\s*(as|to)\s+"
            r"\"?(auto[\s_-]?)?approved\b)",
            _I,
        ),
    ),
    (
        "tool/command smuggling",
        # Shell / template injection payloads.
        re.compile(
            r"(\$\([^)]*\)|`[^`]*\b(rm|curl|wget|bash|sh|powershell|python)\b[^`]*`|"
            r"[;&|]\s*(rm\s+-rf|curl\s|wget\s|bash\s|sh\s+-c)|\{\{.*?\}\}|\{%.*?%\})",
            _I,
        ),
    ),
]

# --- PII patterns ------------------------------------------------------------
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_CARD_CANDIDATE = re.compile(r"(?<![\w-])\d(?:[ -]?\d){12,18}(?![\w-])")
_IBAN_CANDIDATE = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]){11,30}\b")
# US SSN (123-45-6789), Pakistan CNIC (12345-1234567-1), UK NINO (AB123456C).
_NATIONAL_ID = re.compile(r"\b(\d{3}-\d{2}-\d{4}|\d{5}-\d{7}-\d|[A-CEGHJ-PR-TW-Z]{2}\d{6}[A-D])\b")
_PHONE_CANDIDATE = re.compile(r"(?<![\w.])\+?\(?\d[\d ().-]{7,}\d(?![\w.])")


def luhn_valid(digits: str) -> bool:
    """Luhn checksum (payment card numbers)."""
    if not digits.isdigit() or not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


# ISO 13616 IBAN lengths for common countries; others fall back to 15-34.
_IBAN_LENGTHS = {
    "AE": 23,
    "AT": 20,
    "BE": 16,
    "CH": 21,
    "DE": 22,
    "DK": 18,
    "ES": 24,
    "FI": 18,
    "FR": 27,
    "GB": 22,
    "IE": 22,
    "IT": 27,
    "LU": 20,
    "NL": 18,
    "NO": 15,
    "PK": 24,
    "PL": 28,
    "PT": 25,
    "QA": 29,
    "SA": 24,
    "SE": 24,
    "TR": 26,
}


def iban_valid(candidate: str) -> bool:
    """ISO 13616 check (IBAN): country length + mod-97."""
    iban = candidate.replace(" ", "").upper()
    if not 15 <= len(iban) <= 34 or not iban.isalnum():
        return False
    expected = _IBAN_LENGTHS.get(iban[:2])
    if expected is not None and len(iban) != expected:
        return False
    rearranged = iban[4:] + iban[:4]
    numeric = "".join(str(int(c, 36)) for c in rearranged)
    return int(numeric) % 97 == 1


def strip_hidden(text: str) -> str:
    """Remove invisible characters and NFKC-normalize (folds full-width and
    compatibility look-alikes) so patterns can't be dodged with them."""
    return unicodedata.normalize("NFKC", _HIDDEN_CHARS.sub("", text))


def redact_pii(text: str) -> tuple[str, list[str]]:
    """Replace PII with typed placeholders. Returns (redacted, sorted kinds)."""
    if not text:
        return text, []
    kinds: set[str] = set()

    def _sub(pattern: re.Pattern[str], label: str, check=None):
        def repl(m: re.Match[str]) -> str:
            if check is not None and not check(m.group(0)):
                return m.group(0)
            kinds.add(label.lower())
            return f"[REDACTED_{label}]"

        return lambda s: pattern.sub(repl, s)

    def _phone_ok(s: str) -> bool:
        n = sum(c.isdigit() for c in s)
        return 10 <= n <= 15

    def _iban(s: str) -> str:
        # The candidate regex can over-run into a following upper-case word
        # ("... 7654 32 USD"), so try the longest space-separated prefix that
        # passes the mod-97 check and keep whatever trails it.
        def repl(m: re.Match[str]) -> str:
            parts = m.group(0).split(" ")
            for k in range(len(parts), 0, -1):
                head = " ".join(parts[:k])
                if iban_valid(head):
                    kinds.add("iban")
                    tail = " ".join(parts[k:])
                    return "[REDACTED_IBAN]" + (" " + tail if tail else "")
            return m.group(0)

        return _IBAN_CANDIDATE.sub(repl, s)

    steps = [
        _sub(_EMAIL, "EMAIL"),
        _sub(_CARD_CANDIDATE, "CARD", lambda s: luhn_valid(re.sub(r"\D", "", s))),
        _iban,
        _sub(_NATIONAL_ID, "NATIONAL_ID"),
        _sub(_PHONE_CANDIDATE, "PHONE", _phone_ok),
    ]
    for step in steps:
        text = step(text)
    return text, sorted(kinds)


def detect_injection(text: str) -> list[str]:
    """Return the (deduplicated, ordered) injection categories found in text."""
    if not text:
        return []
    found: list[str] = []
    if _HIDDEN_CHARS.search(text):
        found.append("hidden unicode characters")
    normalized = strip_hidden(text)
    for label, pattern in _INJECTION_PATTERNS:
        if label not in found and pattern.search(normalized):
            found.append(label)
    return found


@dataclass
class GuardReport:
    """Outcome of screening one request's free-text fields."""

    findings: list[str] = field(default_factory=list)  # e.g. "description: role override"
    flagged_fields: list[str] = field(default_factory=list)
    pii_kinds: list[str] = field(default_factory=list)  # e.g. ["card", "email"]

    @property
    def suspicious(self) -> bool:
        return bool(self.findings)

    def as_violations(self) -> list[str]:
        """Findings phrased as policy violations (rules fired)."""
        return [f"input guard: possible prompt injection ({f})" for f in self.findings]


def inspect_fields(fields: dict[str, Any]) -> GuardReport:
    """Screen every free-text field for injection attempts and PII."""
    report = GuardReport()
    pii: set[str] = set()
    for name in TEXT_FIELDS:
        value = fields.get(name)
        if not isinstance(value, str) or not value:
            continue
        hits = detect_injection(value)
        if hits:
            report.flagged_fields.append(name)
            report.findings.extend(f"{name}: {h}" for h in hits)
        pii.update(redact_pii(value)[1])
    report.pii_kinds = sorted(pii)
    return report


def inspect_request(request: Any) -> GuardReport:
    """Screen an ``ExpenseRequest`` (or any object exposing the text fields)."""
    return inspect_fields({name: getattr(request, name, None) for name in TEXT_FIELDS})


def sanitize_for_llm(text: str, *, flagged: bool = False) -> str:
    """What may be placed inside an LLM prompt for one untrusted field:
    withheld entirely if flagged, otherwise hidden chars stripped + PII redacted."""
    if flagged:
        return WITHHELD
    return redact_pii(strip_hidden(text or ""))[0]


class PIIRedactingFilter(logging.Filter):
    """Logging filter that redacts PII from the fully-formatted message, so a
    request field interpolated into a log line never leaks an email / card /
    phone number to the log platform."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - a bad format string must not drop the log
            return True
        redacted, kinds = redact_pii(message)
        if kinds:
            record.msg, record.args = redacted, None
        return True
