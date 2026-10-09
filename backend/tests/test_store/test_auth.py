"""Password hashing, Basic login checks and form origin checks."""

from __future__ import annotations

import base64
import stat
from pathlib import Path

import pytest

from ecowitt import auth


def basic(user: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


def test_a_password_verifies_against_its_hash_and_nothing_else() -> None:
    stored = auth.hash_password("correct horse")

    assert auth.verify_password("correct horse", stored)
    assert not auth.verify_password("correct horsE", stored)
    assert "correct horse" not in stored


def test_hashes_are_salted() -> None:
    """The same password hashes differently each time, so equal hashes reveal nothing."""
    assert auth.hash_password("same") != auth.hash_password("same")


@pytest.mark.parametrize(
    "stored", ["", "plain", "bcrypt$1$2$3$a$b", "scrypt$x$8$1$a$b", "scrypt$16384$8$1$!!$!!"]
)
def test_a_malformed_hash_matches_nothing(stored: str) -> None:
    assert not auth.verify_password("anything", stored)


def test_basic_login() -> None:
    stored = auth.hash_password("pw-12345")

    assert auth.check_basic(basic("admin", "pw-12345"), "admin", stored)
    assert not auth.check_basic(basic("admin", "wrong"), "admin", stored)
    assert not auth.check_basic(basic("root", "pw-12345"), "admin", stored)


@pytest.mark.parametrize(
    "header",
    [
        None,
        "",
        "Bearer abc",
        "Basic",
        "Basic !!!not-base64",
        "Basic " + base64.b64encode(b"no-colon").decode(),
        "Basic " + base64.b64encode(b"\xff\xfe:x").decode(),
    ],
)
def test_malformed_authorization_headers_are_refused(header: str | None) -> None:
    assert not auth.check_basic(header, "admin", auth.hash_password("x"))


def test_a_wrong_username_still_costs_a_hash_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """Refusing a wrong username faster than a wrong password would reveal valid usernames."""
    calls: list[str] = []
    monkeypatch.setattr(auth, "verify_password", lambda pw, _stored: calls.append(pw) or False)

    auth.check_basic(basic("someone-else", "guess"), "admin", "scrypt$...")

    assert calls == ["guess"]


def test_the_secret_is_created_once_and_owner_only(tmp_path: Path) -> None:
    path = tmp_path / "data" / "secret.key"

    first = auth.load_secret(path)
    second = auth.load_secret(path)

    assert first == second and len(first) == 32
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


class TestForms:
    secret = b"s" * 32

    def token(self) -> str:
        return auth.csrf_token(self.secret)

    def test_a_form_from_this_server_is_allowed(self) -> None:
        assert auth.form_allowed(
            self.token(), self.secret, "https://wx.example", None, "wx.example"
        )

    def test_referer_stands_in_when_origin_is_absent(self) -> None:
        assert auth.form_allowed(
            self.token(), self.secret, None, "https://wx.example/setup", "wx.example"
        )

    def test_an_opaque_origin_falls_back_to_referer(self) -> None:
        assert not auth.form_allowed(self.token(), self.secret, "null", None, "wx.example")

    @pytest.mark.parametrize(
        ("origin", "referer"),
        [
            ("https://evil.example", None),
            (None, "https://evil.example/x"),
            (None, None),
            ("https://wx.example.evil.example", None),
        ],
    )
    def test_a_form_from_anywhere_else_is_refused(
        self, origin: str | None, referer: str | None
    ) -> None:
        assert not auth.form_allowed(self.token(), self.secret, origin, referer, "wx.example")

    def test_a_wrong_token_is_refused_even_from_this_server(self) -> None:
        assert not auth.form_allowed(
            "0" * 64, self.secret, "https://wx.example", None, "wx.example"
        )

    def test_the_host_comparison_ignores_case(self) -> None:
        assert auth.form_allowed(
            self.token(), self.secret, "https://WX.example", None, "wx.EXAMPLE"
        )
