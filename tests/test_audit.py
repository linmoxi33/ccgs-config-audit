#!/usr/bin/env python3
"""Behaviour tests for ccgs-config-audit. Stdlib only: python3 -m unittest discover tests"""
import importlib.util
import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.join(HERE, "..", "bin", "ccgs-config-audit")
_loader = importlib.machinery.SourceFileLoader("ccgs_audit", BIN)
_spec = importlib.util.spec_from_loader("ccgs_audit", _loader)
audit_mod = importlib.util.module_from_spec(_spec)
_loader.exec_module(audit_mod)


def write(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


SKILL = """---
name: {name}
description: "d"
argument-hint: "[x]"
user-invocable: true
allowed-tools: {tools}
model: sonnet
---
# {name}
{body}
"""

AGENT = """---
name: {name}
description: "d"
tools: Read, Grep
model: inherit
maxTurns: 10
---
You work.
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="ccgs-audit-")
        self.addCleanup(shutil.rmtree, self.root, True)
        write(self.root, ".claude/agents/reviewer.md", AGENT.format(name="reviewer"))

    def skill(self, name="alpha", body="", tools="Read, Agent"):
        write(self.root, ".claude/skills/%s/SKILL.md" % name,
              SKILL.format(name=name, body=body, tools=tools))

    def run_cli(self, *argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = audit_mod.main(list(argv) or [self.root])
        return code, buf.getvalue()

    def codes(self):
        return [f["code"] for f in audit_mod.audit(self.root)["findings"]]


class TestExitCodes(Base):
    def test_clean_pack_exits_zero(self):
        self.skill()
        code, out = self.run_cli(self.root)
        self.assertEqual(code, 0)
        self.assertIn("PASS", out)

    def test_findings_exit_one(self):
        self.skill(body="Delegate to `subagent_type: ghost`.")
        code, out = self.run_cli(self.root)
        self.assertEqual(code, 1)
        self.assertIn("FAIL", out)

    def test_missing_directory_exits_two(self):
        code, _ = self.run_cli(os.path.join(self.root, "nope"))
        self.assertEqual(code, 2)

    def test_no_claude_dir_exits_two(self):
        empty = tempfile.mkdtemp(prefix="ccgs-empty-")
        self.addCleanup(shutil.rmtree, empty, True)
        code, _ = self.run_cli(empty)
        self.assertEqual(code, 2)

    def test_strict_promotes_warnings(self):
        self.skill(tools="Read, NotATool")
        code, _ = self.run_cli(self.root)
        self.assertEqual(code, 0)
        code, _ = self.run_cli(self.root, "--strict")
        self.assertEqual(code, 1)


class TestReferences(Base):
    def test_dangling_subagent_type(self):
        self.skill(body="Hand off to `subagent_type: ghost` now.")
        self.assertIn("REF001", self.codes())

    def test_existing_subagent_type_ok(self):
        self.skill(body="Hand off to `subagent_type: reviewer`.")
        self.assertNotIn("REF001", self.codes())

    def test_bracket_placeholder_is_skipped(self):
        self.skill(body="Hand off to `subagent_type: [primary engine specialist]`.")
        self.assertNotIn("REF001", self.codes())

    def test_dangling_skill_reference(self):
        self.skill(body="Then run `/nope`.")
        self.assertIn("REF002", self.codes())

    def test_builtin_command_is_skipped(self):
        self.skill(body="Then run `/clear`.")
        self.assertNotIn("REF002", self.codes())

    def test_glob_path_is_not_a_skill_reference(self):
        self.skill(body="Write `production/story-*.md` and `/story-[NNN].md`.")
        self.assertNotIn("REF002", self.codes())

    def test_fenced_example_is_ignored(self):
        self.skill(body="```\n/subagent_type: ghost\n/not-a-skill\n```\n")
        self.assertEqual(self.codes(), [])

    def test_dangling_path_reference(self):
        self.skill(body="Run `.claude/scripts/gone.sh`.")
        self.assertIn("REF003", self.codes())

    def test_doc_drift_detected(self):
        write(self.root, ".claude/docs/hooks-reference.md",
              "# Hooks\n\n| Hook | Event |\n| --- | --- |\n| `present.sh` | x |\n")
        write(self.root, ".claude/hooks/present.sh", "#!/bin/sh\n")
        write(self.root, ".claude/hooks/extra.sh", "#!/bin/sh\n")
        found = self.codes()
        self.assertIn("DOC002", found)


class TestFrontmatter(Base):
    def test_missing_frontmatter(self):
        write(self.root, ".claude/skills/bad/SKILL.md", "# no frontmatter\n")
        self.assertIn("FM001", self.codes())

    def test_duplicate_key(self):
        write(self.root, ".claude/skills/dup/SKILL.md",
              "---\nname: dup\nname: dup\ndescription: d\n---\n# Dup\n")
        self.assertIn("FM001", self.codes())

    def test_name_mismatch(self):
        write(self.root, ".claude/skills/alpha/SKILL.md",
              SKILL.format(name="beta", body="", tools="Read"))
        self.assertIn("FM003", self.codes())

    def test_missing_required_key(self):
        write(self.root, ".claude/skills/alpha/SKILL.md",
              "---\nname: alpha\ndescription: d\n---\n# Alpha\n")
        self.assertIn("FM002", self.codes())

    def test_unknown_tool_is_warning(self):
        self.skill(tools="Read, Bogus")
        report = audit_mod.audit(self.root)
        warns = [f for f in report["findings"] if f["code"] == "FM005"]
        self.assertTrue(warns)
        self.assertEqual(warns[0]["severity"], "warn")


class TestStage(Base):
    def test_stage_drift(self):
        write(self.root, "project.yaml", "project:\n  stage: Production\n")
        write(self.root, "production/stage.txt", "Polish")
        self.assertIn("STG001", self.codes())

    def test_half_written_stage(self):
        write(self.root, "project.yaml", "project:\n  stage: Production\n")
        self.assertIn("STG003", self.codes())

    def test_both_absent_is_clean(self):
        self.skill()
        self.assertNotIn("STG003", self.codes())

    def test_invalid_stage_value(self):
        write(self.root, "project.yaml", "project:\n  stage: Shipping\n")
        write(self.root, "production/stage.txt", "Shipping")
        self.assertIn("STG002", self.codes())


class TestJson(Base):
    def test_json_is_parseable_and_stable(self):
        self.skill(body="Run `/nope`.")
        code, out = self.run_cli(self.root, "--json")
        self.assertEqual(code, 1)
        data = json.loads(out)
        self.assertFalse(data["ok"])
        self.assertEqual(data["counts"]["skills"], 1)
        self.assertTrue(any(f["code"] == "REF002" for f in data["findings"]))

    def test_example_report_matches_committed_output(self):
        example = os.path.join(HERE, "..", "examples", "in", "mini-pack")
        expected = os.path.join(HERE, "..", "examples", "out", "report.json")
        code, out = self.run_cli(example, "--json")
        self.assertEqual(code, 1)
        with open(expected, encoding="utf-8") as fh:
            committed = json.load(fh)
        self.assertEqual(json.loads(out)["findings"], committed["findings"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
