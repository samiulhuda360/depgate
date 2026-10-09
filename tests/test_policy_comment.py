from conftest import make_decision

from depgate.comment import MARKER, relevant_lines, render_comment
from depgate.config import Config, load_config
from depgate.models import Update
from depgate.notify import notification_text
from depgate.policy import apply_policy, auto_merge_blockers


def test_confident_low_risk_green_patch_auto_merges(update: Update) -> None:
    out = apply_policy(update, make_decision(), Config())
    assert out.action == "auto_merge"
    assert out.enable_auto_merge and out.approve
    assert out.labels == ["depgate:auto-merge"]
    assert not out.user_reviewers and not out.team_reviewers


def test_each_blocker(update: Update) -> None:
    cfg = Config()
    assert auto_merge_blockers(update, make_decision(conf_top=0.7), cfg)  # confidence 0.55 < 0.8
    assert auto_merge_blockers(update, make_decision(risk=2), cfg)
    update.ci_status = "pending"
    assert any("CI is pending" in b for b in auto_merge_blockers(update, make_decision(), cfg))
    update.ci_status = "success"
    update.jump = "major"
    assert any("major" in b for b in auto_merge_blockers(update, make_decision(), cfg))
    cfg.auto_merge.allow_major = True
    assert not auto_merge_blockers(update, make_decision(), cfg)
    cfg.auto_merge.ignore = ["axios"]
    assert any("ignore list" in b for b in auto_merge_blockers(update, make_decision(), cfg))


def test_breaking_change_affecting_repo_is_held(update: Update) -> None:
    cfg = Config.from_dict({"reviewers": ["@acme/platform", "@lead-dev"]})
    out = apply_policy(update, make_decision("hold", risk=3, breaking_in_notes=0.95, breaking_affects_repo=0.9), cfg)
    assert out.action == "hold"
    assert "depgate:hold" in out.labels and "breaking-change" in out.labels
    assert out.team_reviewers == ["platform"] and out.user_reviewers == ["lead-dev"]
    assert any("breaking change" in r for r in out.reasons)
    assert out.notify  # hold notifies by default


def test_failing_ci_holds_even_if_model_says_merge(update: Update) -> None:
    update.ci_status = "failure"
    out = apply_policy(update, make_decision(), Config.from_dict({"fail_check_on_hold": True}))
    assert out.action == "hold"
    assert out.check_conclusion == "failure"


def test_security_fix_gets_priority_and_security_reviewers(update: Update) -> None:
    update.advisories = [{"ghsa_id": "GHSA-test", "summary": "ReDoS", "severity": "high", "url": "https://example.test"}]
    cfg = Config.from_dict({"security_reviewers": ["@acme/security"]})
    auto = apply_policy(update, make_decision(security_fix=0.97), cfg)
    assert auto.action == "auto_merge" and "priority:high" in auto.labels and auto.notify
    review = apply_policy(update, make_decision("merge_after_review", risk=2, security_fix=0.97), cfg)
    assert review.team_reviewers == ["security"]


def test_uncertain_answers_need_a_human(update: Update) -> None:
    out = apply_policy(update, make_decision(breaking_affects_repo=0.45), Config())
    assert out.needs_human and out.action != "auto_merge"
    assert "depgate:needs-human" in out.labels


def test_config_from_yaml_text() -> None:
    cfg = load_config(text="auto_merge:\n  min_confidence: 0.9\n  merge_method: rebase\nlabels:\n  hold: blocked\nnotify:\n  events: [all]\n")
    assert cfg.auto_merge.min_confidence == 0.9
    assert cfg.auto_merge.merge_method == "REBASE"
    assert cfg.labels.hold == "blocked"
    assert cfg.notify.events == ["all"]


def test_comment_quotes_relevant_notes(update: Update) -> None:
    update.release_notes = "## v2.0.0\n- BREAKING: removed the `legacyParse` option\n- chore: bump dev deps\n- `formDataToJSON` handles nested arrays"
    quotes = relevant_lines(update)
    assert quotes[0].startswith("BREAKING: removed")
    assert any("formDataToJSON" in q for q in quotes)  # the repo uses this symbol
    assert not any("dev deps" in q for q in quotes)
    dec = make_decision("hold", risk=3, breaking_in_notes=0.9, breaking_affects_repo=0.8)
    text = render_comment(update, dec, apply_policy(update, dec, Config()), dry_run=True)
    assert text.startswith(MARKER)
    assert "hold: do not merge yet" in text
    assert "> BREAKING: removed" in text
    assert "Dry run" in text


def test_notification_text(update: Update) -> None:
    dec = make_decision("hold", risk=3, breaking_affects_repo=0.9)
    text = notification_text(update, dec, apply_policy(update, dec, Config()))
    assert text.startswith("Dependency update in example/orders-api#7: axios 1.6.0 -> 1.6.1 is held")
