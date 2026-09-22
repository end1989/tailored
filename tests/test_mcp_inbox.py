"""The candidate's inbox, as an MCP agent sees it.

get_master_profile carries a derived inbox_url, and the workflow guide tells
the agent how to use it: open that URL, never an account picked by position,
check the mailbox address before reading anything, and stop at a sign-in page.
The guide and the tool docstring are what the agent actually reads, so both are
pinned here along with the EXTENDING.md row that documents the key.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest
from sqlmodel import Session

from backend import mcp_ops
from backend.app.models import Profile, set_contact
from backend.app.schemas import Contact

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = PROJECT_ROOT / "backend" / "mcp_server.py"
EXTENDING_PATH = PROJECT_ROOT / "docs" / "EXTENDING.md"

# Verbatim from the person-picker plan contract. The guide must carry exactly
# this text, so an edit that drops one of the rules fails here.
INBOX_SECTION = """CANDIDATE'S INBOX (only when the user asks you to work in their mail):
- get_master_profile returns inbox_url when the candidate's email is on a
  provider Tailored recognises. Open that URL in the user's own browser. Never
  pick an account by position (such as /mail/u/1/).
- Before reading anything, confirm the mailbox address shown on the page is
  the candidate's contact email. If it differs, stop and say which account is
  open.
- A sign-in page means that account is not signed in in this browser: say so
  and stop. Never sign in on the user's behalf.
- If inbox_url is null, open no inbox. Ask the user which one to use."""

# Characters the voice contract bans in agent-facing text.
MACHINE_TELLS = tuple(chr(c) for c in (0x2014, 0x2013, 0x2026, 0x201C, 0x201D, 0x2018, 0x2019))


def _seed(engine, name: str, email: str | None) -> int:
    """One profile; email None leaves contact_json at its '{}' default."""
    with Session(engine) as session:
        profile = Profile(name=name)
        if email is not None:
            set_contact(profile, Contact(name=name, email=email))
        session.add(profile)
        session.commit()
        session.refresh(profile)
        return profile.id


# --- get_master_profile ---

@pytest.mark.parametrize(
    ("email", "expected"),
    [
        (
            "jordan.rivera+jobs@gmail.com",
            "https://mail.google.com/mail/?authuser=jordan.rivera%2Bjobs@gmail.com",
        ),
        ("jordan@icloud.com", "https://www.icloud.com/mail"),
        ("jordan@hotmail.com", "https://outlook.live.com/mail/"),
        ("jordan.rivera@example.com", None),
        ("", None),
    ],
)
def test_get_master_profile_returns_inbox_url(engine, email, expected):
    profile_id = _seed(engine, "Jordan Rivera", email)

    data = mcp_ops.get_master_profile(engine, profile_id)

    assert "inbox_url" in data, "the key is always present, null when unknown"
    assert data["inbox_url"] == expected
    # Additive: the existing keys are all still there.
    assert {"profile_id", "name", "contact", "voice_notes", "master_profile"} <= set(data)
    assert data["contact"]["email"] == email


def test_get_master_profile_inbox_url_without_any_contact(engine):
    """A profile created with no contact at all falls back to Contact(name=...),
    whose email is empty, so there is no inbox to point at."""
    profile_id = _seed(engine, "No Contact Yet", None)

    data = mcp_ops.get_master_profile(engine, profile_id)

    assert data["inbox_url"] is None


def test_get_master_profile_inbox_url_on_the_sole_profile_path(engine):
    """profile_id omitted resolves the sole profile; the key comes with it."""
    _seed(engine, "Only Person", "only.person@gmail.com")

    data = mcp_ops.get_master_profile(engine)

    assert data["inbox_url"] == (
        "https://mail.google.com/mail/?authuser=only.person@gmail.com"
    )


def test_get_master_profile_inbox_url_is_per_person(engine):
    """Two people, two inboxes: each profile_id gets its own candidate's link,
    which is the whole point of not picking a mailbox by position."""
    first = _seed(engine, "First Person", "first.person@gmail.com")
    second = _seed(engine, "Second Person", "second.person@outlook.com")

    assert mcp_ops.get_master_profile(engine, first)["inbox_url"] == (
        "https://mail.google.com/mail/?authuser=first.person@gmail.com"
    )
    assert mcp_ops.get_master_profile(engine, second)["inbox_url"] == (
        "https://outlook.live.com/mail/"
    )


# --- workflow guide ---

def test_workflow_guide_has_the_inbox_section_verbatim():
    guide = mcp_ops.get_workflow_guide()
    assert INBOX_SECTION in guide


def test_workflow_guide_inbox_section_follows_writing_voice():
    guide = mcp_ops.get_workflow_guide()
    assert "CANDIDATE'S INBOX" in guide
    voice = guide.index("WRITING VOICE")
    inbox = guide.index("CANDIDATE'S INBOX")
    shapes = guide.index("JSON SHAPES")
    assert voice < inbox < shapes


def test_workflow_guide_inbox_section_has_no_machine_tells():
    guide = mcp_ops.get_workflow_guide()
    assert "CANDIDATE'S INBOX" in guide
    section = guide[guide.index("CANDIDATE'S INBOX"):guide.index("JSON SHAPES")]
    for char in MACHINE_TELLS:
        assert char not in section, f"inbox section contains U+{ord(char):04X}"


# --- what the agent reads besides the guide ---

def _tool_docstring(name: str) -> str:
    """One @mcp.tool function's docstring, parsed from source with ast.

    Not imported: importing backend/mcp_server.py runs its module-level engine
    setup against the real data directory (same reason as test_mcp_server.py).
    """
    tree = ast.parse(SERVER_PATH.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == name:
            return ast.get_docstring(node) or ""
    raise AssertionError(f"no tool function named {name!r} in mcp_server.py")


def test_get_master_profile_docstring_mentions_inbox_url():
    doc = _tool_docstring("get_master_profile")
    assert "inbox_url" in doc
    assert "null" in doc
    assert "get_workflow_guide" in doc
    for char in MACHINE_TELLS:
        assert char not in doc, f"docstring contains U+{ord(char):04X}"


def test_extending_md_documents_inbox_url():
    lines = EXTENDING_PATH.read_text(encoding="utf-8").splitlines()
    row = next(
        (line for line in lines if line.startswith("| `get_master_profile(")),
        None,
    )
    assert row is not None, "EXTENDING.md lost its get_master_profile row"
    assert "`inbox_url`" in row
