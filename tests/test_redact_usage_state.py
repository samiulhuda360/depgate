from depgate.models import Update
from depgate.redact import REDACTED, redact
from depgate.state import digest_notes, prepare_state
from depgate.usage import find_usage, symbols_from_notes


def test_redacts_assignments_bearer_and_url_credentials() -> None:
    text = 'password = "hunter-two-not-real"\nAuthorization: Bearer test-token-not-real-123\nDB=postgres://app:not-a-real-pass@db:5432/x'
    out, n = redact(text)
    assert "hunter-two-not-real" not in out
    assert "test-token-not-real-123" not in out
    assert "not-a-real-pass" not in out
    assert n == 3
    assert out.count(REDACTED) == 3


def test_keeps_env_references_and_placeholders() -> None:
    text = "api_key = os.environ['API_KEY']\ntoken: ${{ secrets.TOKEN }}\nsecret = process.env.SECRET"
    out, n = redact(text)
    assert n == 0
    assert out == text


def test_redacts_private_key_block() -> None:
    begin, end = "-----BEGIN " + "PRIVATE KEY-----", "-----END " + "PRIVATE KEY-----"
    out, n = redact(f"key:\n{begin}\nabc\n{end}\n")
    assert n == 1
    assert "abc" not in out


def test_symbols_from_notes() -> None:
    notes = "- Removed `axios.defaults.adapter` option\n- `formDataToJSON()` now handles arrays\n- fix typo"
    syms = symbols_from_notes(notes, "axios")
    assert "formDataToJSON" in syms
    assert "adapter" in syms


def test_find_usage_python_alias_and_runtime() -> None:
    files = {
        "app/auth.py": "import os\nimport jwt\n\n\ndef decode(t):\n    return jwt.decode(t, os.environ['K'], algorithms=['HS256'])\n",
        "pyproject.toml": '[project]\nrequires-python = ">=3.8"\n',
        "app/other.py": "print('no package here')\n",
    }
    usage = find_usage("pyjwt", "pip", "Drop support for Python 3.8; `decode()` requires `algorithms`", files)
    assert "app/auth.py:2: import jwt" in usage
    assert any("jwt.decode" in u for u in usage)
    assert any("requires-python" in u for u in usage)
    assert not any("other.py" in u for u in usage)


def test_find_usage_js_and_tool_config() -> None:
    files = {
        "src/client.ts": "import axios from 'axios';\nexport const api = axios.create({ baseURL: '/api' });\n",
        "jest.config.js": "module.exports = {\n  testEnvironment: 'jsdom',\n};\n",
    }
    assert find_usage("axios", "npm", "", files) == [
        "src/client.ts:1: import axios from 'axios';",
        "src/client.ts:2: export const api = axios.create({ baseURL: '/api' });",
    ]
    jest = find_usage("jest", "npm", "", files)
    assert "jest.config.js:2: testEnvironment: 'jsdom'," in jest


def test_digest_keeps_breaking_lines() -> None:
    notes = "## v2.0.0\n" + "\n".join(f"- internal refactor {i}" for i in range(400)) + "\n- BREAKING: removed `legacy()`\n"
    out = digest_notes(notes, 2000)
    assert len(out) < 2200
    assert "BREAKING: removed `legacy()`" in out
    assert "trimmed to the key lines" in out


def test_prepare_state_redacts_usage() -> None:
    u = Update(package="x", ecosystem="npm", from_version="1.0.0", to_version="1.0.1", usage=['src/a.js:3: const token = "abcdef-not-real"'])
    state, n = prepare_state(u)
    assert n == 1
    assert "abcdef-not-real" not in str(state["usage"])
    assert state["advisories"] == "none listed"


def test_find_usage_github_actions() -> None:
    wf = "jobs:\n  t:\n    steps:\n      - uses: actions/checkout@v4\n        with:\n          fetch-depth: 0\n      - run: make test\n"
    usage = find_usage("actions/checkout", "actions", "", {".github/workflows/ci.yml": wf})
    assert usage[0] == ".github/workflows/ci.yml:4: - uses: actions/checkout@v4"
    assert ".github/workflows/ci.yml:6: fetch-depth: 0" in usage
