"""The masking catalogue: fields, labels, and patterns.

Edit this file to change what is detected. Labels are matched after folding, so
write them in lowercase with no diacritics (``muc luong``, not ``Mức lương``).

``Field.editable`` is the operator switch. Salary is editable: the batch
checkbox turns salary masking on or off. Every other field is mandatory.
``Field.masked`` is false only for a listed field that is not removed.

Bump ``DETECTOR_VERSION`` when a pattern, label, or score below changes.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from cv_masking.domain.errors import InvariantError

DETECTOR_VERSION: Final = "1.2.3"
CONTEXT_WINDOW: Final = 48
SCORE_HIGH: Final = 0.92
SCORE_CONTEXT: Final = 0.88
SCORE_VALUE: Final = 0.90


@dataclass(frozen=True, slots=True)
class Field:
    """One catalogue field and the label written where its text was removed."""

    entity: str
    replacement: str
    editable: bool = False
    masked: bool = True


@dataclass(frozen=True, slots=True)
class AppliedPattern:
    """A value shape matched anywhere in the text."""

    entity: str
    name: str
    regex: str
    score: float


@dataclass(frozen=True, slots=True)
class ContextPattern:
    """A value shape matched only when one of ``labels`` sits just before it."""

    entity: str
    regex: str
    score: float
    labels: tuple[str, ...]


FIELDS: Final[tuple[Field, ...]] = (
    Field("candidate_name", "[NAME]"),
    Field("reference_name", "[NAME]"),
    Field("email", "[EMAIL]"),
    Field("phone", "[PHONE]"),
    Field("national_id", "[ID]"),
    Field("passport", "[ID]"),
    Field("postal_address", "[ADDRESS]"),
    Field("date_of_birth", "[DOB]"),
    Field("gender", "[REDACTED]"),
    Field("marital_status", "[REDACTED]"),
    Field("nationality", "[REDACTED]"),
    Field("religion", "[REDACTED]"),
    Field("ethnicity", "[REDACTED]"),
    Field("health", "[REDACTED]"),
    Field("family_details", "[REDACTED]"),
    Field("personal_url", "[URL]", masked=False),
    Field("salary", "[SALARY]", editable=True),
)

# --- Value shapes matched anywhere ------------------------------------------

EMAIL_RE: Final = r"(?<![A-Za-z0-9._%+\-])[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]{1,253}\.[A-Za-z]{2,}"
"""Leftmost matches always start where a local-part run starts, so the lookbehind
changes no result; it stops rescans from inside long runs. The 253 cap is the DNS
name limit; unbounded, the `regex` engine Presidio uses backtracks quadratically on
long dotted runs."""
EMAIL_LOCAL_RE: Final = (
    r"(?<![A-Za-z0-9._%+\-])([A-Za-z0-9._%+\-]+)@[A-Za-z0-9.\-]{1,253}\.[A-Za-z]{2,}"
)
PHONE_RE: Final = (
    r"(?<!\d)(?:(?:\+84|\(\+84\)|84)[\s.\-]*|[0])"
    r"(?:[35789](?:[\s.\-]?\d){8}|2\d(?:[\s.\-]?\d){8})(?!\d)"
)
CCCD_RE: Final = r"(?<!\d)(?:\d[\s]?){11}\d(?!\d)"

ANYWHERE_PATTERNS: Final[tuple[AppliedPattern, ...]] = (
    AppliedPattern("email", "email", EMAIL_RE, SCORE_HIGH),
    AppliedPattern("phone", "phone", PHONE_RE, SCORE_HIGH),
    AppliedPattern("national_id", "cccd", CCCD_RE, SCORE_VALUE),
)

# --- Value shapes matched only after a label --------------------------------

CMND_RE: Final = r"(?<!\d)\d{9}(?!\d)"
PASSPORT_RE: Final = r"(?<![A-Za-z0-9])[A-Za-z]\d{7}(?!\d)"
ID_LABELS: Final = (
    "cccd",
    "cmnd",
    "can cuoc cong dan",
    "chung minh nhan dan",
    "so cmnd",
    "so cccd",
    "id card",
    "id number",
    "national id",
    "citizen id",
)
PASSPORT_LABELS: Final = ("ho chieu", "so ho chieu", "passport", "passport no")

CONTEXT_PATTERNS: Final[tuple[ContextPattern, ...]] = (
    ContextPattern("national_id", CMND_RE, SCORE_CONTEXT, ID_LABELS),
    ContextPattern("passport", PASSPORT_RE, SCORE_CONTEXT, PASSPORT_LABELS),
)

# --- Label, then the value on the same line ---------------------------------
# national_id and passport are listed so their labels stop a neighboring value.
# Their own values come from the patterns above, not from the rest of the line.

DOB_LABELS: Final = (
    "ngay sinh",
    "sinh ngay",
    "nam sinh",
    "date of birth",
    "dob",
    "born",
    "age",
    "tuoi",
)
SALARY_LABELS: Final = (
    "muc luong",
    "luong mong muon",
    "muc luong mong muon",
    "luong hien tai",
    "thu nhap",
    "salary",
    "expected salary",
    "current salary",
    "compensation",
)
POSTAL_ADDRESS_LABELS: Final = (
    "dia chi",
    "cho o hien nay",
    "que quan",
    "nguyen quan",
    "ho khau thuong tru",
    "noi sinh",
    "address",
    "hometown",
    "place of birth",
    "permanent address",
)
FIELD_LABELS: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("gender", ("gioi tinh", "gender", "sex")),
    ("marital_status", ("tinh trang hon nhan", "hon nhan", "marital status")),
    ("nationality", ("quoc tich", "nationality")),
    ("religion", ("ton giao", "religion")),
    ("ethnicity", ("dan toc", "ethnicity")),
    ("health", ("suc khoe", "chieu cao", "can nang", "health", "height", "weight")),
    ("postal_address", POSTAL_ADDRESS_LABELS),
    ("date_of_birth", DOB_LABELS),
    ("salary", SALARY_LABELS),
    ("passport", PASSPORT_LABELS),
    ("national_id", ID_LABELS),
)
LABELED_VALUE_KIND: Final[Mapping[str, str]] = MappingProxyType(
    {
        "date_of_birth": "dob",
        "salary": "salary",
        "national_id": "skip",
        "passport": "skip",
    }
)

DATE_RE: Final = (
    r"(?<!\d)(?:\d{1,2}[/\-.]\d{1,2}[/\-.]\d{4}"
    r"|ngay\s+\d{1,2}\s+thang\s+\d{1,2}\s+nam\s+\d{4}"
    r"|\d{1,2}\s+(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?"
    r"|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
    r"\s+\d{4})(?!\d)"
)
YEAR_RE: Final = r"(?<!\d)(?:19|20)\d{2}(?!\d)"
DOB_AGE_RE: Final = r"(?<!\d)(\d{1,2})\s*tuoi"
AGE_AFTER_LABEL_RE: Final = r"(?i)(?:tu[oôố]i|\bage)\b\s*[:\-]?\s*(\d{1,2})\b"
AGE_BEFORE_LABEL_RE: Final = r"(?i)(?<!\d)(\d{1,2})\s*tu[oôố]i\b"
SALARY_RE: Final = (
    r"(?:\d{1,3}(?:[.,]\d{3})+(?:\s*(?:vnd|vnđ|đ))?"
    r"|\d{1,3}(?:[.,]\d{1,2})?\s*(?:triệu|trieu|tr)\b"
    r"|\$\s*\d{1,3}(?:,\d{3})+(?:/\s*month)?"
    r"|\d{1,3}(?:,\d{3})+\s*usd"
    r"|thoa\s*thuan|thỏa\s*thuận|negotiable)"
)

CONTACT_LABELS: Final = (
    "email",
    "dien thoai",
    "so dien thoai",
    "phone",
    "tel",
    "lien he",
    "contact",
    "zalo",
    "skype",
    "telegram",
)
EXTRA_STOP_LABELS: Final = (
    "linkedin",
    "github",
    "facebook",
    "website",
    "portfolio",
    "kinh nghiem",
    "experience",
    "education",
    "hoc van",
    "ky nang",
    "skills",
    "objective",
    "muc tieu",
)

# --- Names -------------------------------------------------------------------

NAME_LABELS: Final = (
    "ho va ten",
    "ho ten",
    "ten ung vien",
    "ten",
    "full name",
    "candidate name",
    "name",
)
HONORIFICS: Final = ("ong", "ba", "anh", "chi", "co", "thay", "mr", "mrs", "ms", "miss", "dr")
VN_SURNAMES: Final = frozenset(
    {
        "nguyen",
        "tran",
        "le",
        "pham",
        "hoang",
        "huynh",
        "phan",
        "vu",
        "vo",
        "dang",
        "bui",
        "do",
        "ho",
        "ngo",
        "duong",
        "ly",
        "dinh",
        "truong",
        "mai",
        "to",
        "lam",
        "ha",
        "dao",
        "cao",
        "luu",
        "ta",
        "chau",
        "quach",
        "thai",
        "kieu",
        "chu",
        "trieu",
        "luong",
        "doan",
        "trinh",
        "tang",
    }
)
EXCLUDED_TOKENS: Final = frozenset(
    {
        "ltd",
        "inc",
        "corp",
        "jsc",
        "llc",
        "plc",
        "bank",
        "group",
        "company",
        "corporation",
        "holdings",
        "limited",
        "university",
        "college",
        "institute",
        "academy",
        "school",
        "technology",
        "technologies",
        "solutions",
        "software",
        "services",
        "consulting",
        "vitae",
        "resume",
        "cv",
        "engineer",
        "developer",
        "manager",
        "analyst",
        "intern",
        "specialist",
        "officer",
        "director",
        "consultant",
        "designer",
        "accountant",
        "executive",
        "assistant",
        "lead",
        "head",
        "senior",
        "junior",
        "tnhh",
        "programming",
        "languages",
        "frameworks",
        "libraries",
        "databases",
        "devops",
        "tools",
        "cloud",
    }
)
EXCLUDED_PHRASES: Final = (
    "cong ty",
    "co phan",
    "ngan hang",
    "dai hoc",
    "cao dang",
    "hoc vien",
    "truong dai",
    "truong thpt",
    "truong thcs",
    "thanh pho",
    "ho chi minh",
    "ha noi",
    "da nang",
    "hai phong",
    "can tho",
    "viet nam",
    "vietnam",
    "curriculum vitae",
    "so yeu ly lich",
    "ho so",
    "chuyen vien",
    "nhan vien",
    "ky su",
    "truong phong",
    "giam doc",
    "ke toan",
    "thuc tap",
    "programming languages",
    "frameworks libraries",
    "databases tools",
)
WEAK_EMAIL_TOKENS: Final = frozenset({"van", "thi"})

# --- Section headings --------------------------------------------------------

REFERENCE_HEADINGS: Final = (
    "nguoi tham chieu",
    "nguoi tham khao",
    "nguoi gioi thieu",
    "thong tin tham chieu",
    "references",
    "referees",
    "reference",
)
FAMILY_HEADINGS: Final = (
    "thong tin gia dinh",
    "quan he gia dinh",
    "hoan canh gia dinh",
    "gia dinh",
    "family",
    "family background",
    "family information",
)
OTHER_HEADINGS: Final = (
    "kinh nghiem",
    "kinh nghiem lam viec",
    "qua trinh cong tac",
    "hoc van",
    "trinh do hoc van",
    "qua trinh hoc tap",
    "ky nang",
    "du an",
    "chung chi",
    "ngoai ngu",
    "hoat dong",
    "giai thuong",
    "so thich",
    "muc tieu",
    "muc tieu nghe nghiep",
    "thong tin ca nhan",
    "thong tin lien he",
    "experience",
    "work experience",
    "work history",
    "employment",
    "education",
    "skills",
    "projects",
    "certifications",
    "certificates",
    "languages",
    "activities",
    "awards",
    "interests",
    "hobbies",
    "objective",
    "career objective",
    "expectations",
    "summary",
    "profile",
    "personal information",
    "personal details",
    "contact",
    "contact information",
)

# --- Unlabeled addresses in the contact block --------------------------------

ADDRESS_CUES: Final = frozenset(
    {
        "so",
        "duong",
        "pho",
        "ngo",
        "ngach",
        "hem",
        "kiet",
        "phuong",
        "quan",
        "huyen",
        "xa",
        "tinh",
        "thon",
        "ap",
        "khu",
        "street",
        "st",
        "road",
        "rd",
        "avenue",
        "ave",
        "lane",
        "ward",
        "district",
        "dist",
        "province",
        "apartment",
    }
)
ABBREVIATED_ADDRESS_CUES: Final = frozenset({"p.", "q.", "tp.", "tx.", "tt."})
NUMBERED_ADDRESS_RES: Final = (
    r"\bbuilding\s+\d{1,4}\b",
    r"\bfloor\s+\d{1,3}\b",
    r"\b\d{1,3}(?:st|nd|rd|th)\s+floor\b",
    r"\bapt\.?\s+\d{1,4}\b",
)

_VALUE_KINDS: Final = frozenset({"dob", "salary", "skip"})


def _require_consistent() -> None:
    entities = tuple(field.entity for field in FIELDS)
    if len(entities) != len(set(entities)):
        raise InvariantError("catalogue FIELDS lists an entity twice")
    if any(field.editable and not field.masked for field in FIELDS):
        raise InvariantError("an editable field is masked when the operator leaves it on")
    editable = tuple(field.entity for field in FIELDS if field.editable)
    if editable != ("salary",):
        raise InvariantError("salary is the only editable catalogue field")
    for field in FIELDS:
        if not field.replacement or any(char.isspace() for char in field.replacement):
            raise InvariantError("a replacement label is non-empty and has no whitespace")
    known = set(entities)
    used = {pattern.entity for pattern in ANYWHERE_PATTERNS}
    used.update(pattern.entity for pattern in CONTEXT_PATTERNS)
    used.update(entity for entity, _labels in FIELD_LABELS)
    used.update(LABELED_VALUE_KIND)
    if not used <= known:
        raise InvariantError("a catalogue pattern names a field that is not listed")
    if any(kind not in _VALUE_KINDS for kind in LABELED_VALUE_KIND.values()):
        raise InvariantError("a labeled value kind must be dob, salary, or skip")
    for _entity, labels in FIELD_LABELS:
        if not labels:
            raise InvariantError("a labeled field needs at least one label")


_require_consistent()
