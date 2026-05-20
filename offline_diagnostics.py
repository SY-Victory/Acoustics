#!/usr/bin/env python3
"""
Canvas App Offline Diagnostics -- scans .fx.yaml files for known
Dataverse SQLite anti-patterns that cause failures on mobile.

Checks (from CLAUDE.md anti-pattern catalog):
  AP2   Set()/IfError() inside ForAll body
  AP4   Standalone LookUp on restricted/flaky tables
  AP5   ParseJSON without Coalesce guard
  AP6   Not() on nullable boolean (SQLite null semantics)
  AP7   AddColumns wrapping Dataverse Filter
  AP8   Refresh() before ClearCollect (race condition)
  AP9   Standalone ClearCollect on restricted tables
  AP10  Date type mismatch (Text() wrapping date comparison)
  AP11  Direct Dataverse query in auto-evaluating display property
  INFO  LookUp as Patch target (informational)

Usage:
    python offline_diagnostics.py                     # scan active screens + components
    python offline_diagnostics.py --all               # scan ALL .fx.yaml files
    python offline_diagnostics.py file1.fx.yaml ...   # scan specific files
    python offline_diagnostics.py --json              # JSON output
"""

import re
import sys
import os
import glob
import json
from collections import defaultdict

# ── Configuration ──────────────────────────────────────────────────────────

# Active screens (not marked IGNORE in CLAUDE.md)
ACTIVE_SCREENS = {
    "App.fx.yaml",
    "Screen_EngineerHome.fx.yaml",
    "Screen_EngineerAcoustic_1.fx.yaml",
}

# Tables whose OData path always fails on mobile
RESTRICTED_TABLES = ["BESA_Tests", "BESA_BookingElements", "BESA_Envelopes"]
# Tables whose OData path is non-deterministically flaky
FLAKY_TABLES = ["BESA_Shifts"]
ALL_RISKY_TABLES = RESTRICTED_TABLES + FLAKY_TABLES

# Display/auto-evaluating properties -- fire on every re-render
DISPLAY_PROPS = {
    "Text", "Visible", "Items", "Fill", "Color", "Tooltip",
    "DisplayMode", "Width", "Height", "X", "Y", "Size",
    "BorderColor", "HoverFill", "PressedFill", "DisabledFill",
    "TemplateFill", "Default",
}


# ── Formula block extraction ──────────────────────────────────────────────

def extract_formula_blocks(content):
    """Extract formula blocks from .fx.yaml content.

    Returns list of dicts:
        prop      -- YAML property name (e.g. OnSelect, Text, Items)
        start     -- 1-based first line of formula text
        end       -- 1-based last line of formula text
        formula   -- full formula text (may be multi-line)
    """
    lines = content.split("\n")
    blocks = []
    i = 0

    while i < len(lines):
        stripped = lines[i].rstrip()

        # Single-line formula: "  PropName: =formula"
        m = re.match(r'^(\s+)([\w][\w \']*):\s+(=.+)$', stripped)
        if m:
            blocks.append({
                "prop": m.group(2).strip(),
                "start": i + 1,
                "end": i + 1,
                "formula": m.group(3),
            })
            i += 1
            continue

        # Block scalar: "  PropName: |-" or "| " or "|+"
        m = re.match(r'^(\s+)([\w][\w \']*):\s+\|[-+]?\s*$', stripped)
        if m:
            prop_indent = len(m.group(1))
            prop_name = m.group(2).strip()
            formula_lines = []
            j = i + 1
            while j < len(lines):
                nl = lines[j].rstrip()
                if nl.strip() == "":
                    formula_lines.append("")
                    j += 1
                    continue
                ni = len(nl) - len(nl.lstrip())
                if ni <= prop_indent:
                    break
                formula_lines.append(nl)
                j += 1

            # Trim trailing blanks
            while formula_lines and formula_lines[-1].strip() == "":
                formula_lines.pop()
                j -= 1

            blocks.append({
                "prop": prop_name,
                "start": i + 2,
                "end": max(i + 2, j),
                "formula": "\n".join(formula_lines),
            })
            i = j
            continue

        i += 1

    return blocks


def _char_to_line(text, pos):
    """0-based line offset within text for character position."""
    return text[:pos].count("\n")


def _in_comment(formula, pos):
    """Return True if character position is inside a // comment."""
    line_start = formula.rfind("\n", 0, pos)
    line_start = line_start + 1 if line_start >= 0 else 0
    line_text = formula[line_start:pos]
    # Check for // that isn't inside a string
    in_str = False
    for i, c in enumerate(line_text):
        if in_str:
            if c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == '/' and i + 1 < len(line_text) and line_text[i + 1] == '/':
                return True
    return False


# ── Scope-aware ForAll body finder ────────────────────────────────────────

def _find_forall_ranges(formula):
    """Return list of (body_start, body_end) char ranges for ForAll bodies.

    Tracks parentheses while skipping string literals.
    """
    ranges = []
    for m in re.finditer(r"\bForAll\s*\(", formula):
        open_pos = m.end() - 1          # the '(' character
        depth = 0
        in_str = False
        pos = open_pos
        while pos < len(formula):
            c = formula[pos]
            if in_str:
                if c == '"':
                    in_str = False
            else:
                if c == '"':
                    in_str = True
                elif c == '(':
                    depth += 1
                elif c == ')':
                    depth -= 1
                    if depth == 0:
                        ranges.append((open_pos, pos))
                        break
            pos += 1
    return ranges


# ── Per-block checks ─────────────────────────────────────────────────────

def _check_block(block, basename, content_lines):
    """Run all anti-pattern checks on one formula block.  Returns violations."""
    formula = block["formula"]
    prop = block["prop"]
    violations = []

    def _add(rule, name, sev, char_off, fix, **extra):
        lineno = block["start"] + _char_to_line(formula, char_off)
        line_text = content_lines[lineno - 1].strip() if lineno <= len(content_lines) else ""
        v = {
            "rule": rule,
            "name": name,
            "severity": sev,
            "file": basename,
            "line": lineno,
            "prop": prop,
            "text": line_text[:160],
            "fix": fix,
        }
        v.update(extra)
        violations.append(v)

    # ── AP4: Standalone LookUp on restricted / flaky tables ──────────
    risky_re = "|".join(re.escape(t) for t in ALL_RISKY_TABLES)
    for m in re.finditer(rf"\bLookUp\s*\(\s*({risky_re})\b", formula):
        if _in_comment(formula, m.start()):
            continue
        table = m.group(1)
        sev = "HIGH" if table in RESTRICTED_TABLES else "MEDIUM"
        _add("AP4", f"Standalone LookUp({table})", sev, m.start(),
             "Replace with ForAll buffer + First(Filter(Table, Text(PK) = g.pk))",
             table=table)

    # ── AP5: ParseJSON without Coalesce ──────────────────────────────
    for m in re.finditer(r"ParseJSON\s*\(", formula):
        if _in_comment(formula, m.start()):
            continue
        after = formula[m.end():].lstrip()
        if not (after.startswith("Coalesce") or after.startswith("JSON")
                or after.startswith('"') or after.startswith("'{")
                or after.startswith("\"{")):
            # Check for field guarded by IsBlank() in same formula block
            # Handles: part.X, 'Column Name', varName.field patterns
            arg_m = re.match(
                r"ParseJSON\s*\(\s*(part\.\w+|'[^']+(?:\s[^']+)*'|[a-zA-Z]\w*(?:\.\w+)*)",
                formula[m.start():]
            )
            if arg_m:
                field = arg_m.group(1)
                escaped = re.escape(field)
                if re.search(rf"IsBlank\s*\(\s*{escaped}\s*\)", formula):
                    _add("AP5-guarded", f"ParseJSON({field}) with IsBlank guard",
                         "INFO", m.start(),
                         "Guarded by IsBlank() - safe, but Coalesce is more explicit")
                    continue
            _add("AP5", "ParseJSON without Coalesce", "HIGH", m.start(),
                 'Wrap argument in Coalesce(..., "{}")')

    # ── AP9: ClearCollect on restricted tables ───────────────────────
    rest_re = "|".join(re.escape(t) for t in RESTRICTED_TABLES)
    for m in re.finditer(
            rf"\bClearCollect\s*\(\s*\w+\s*,\s*(?:FirstN\s*\(\s*)?({rest_re})\b",
            formula):
        _add("AP9", f"ClearCollect on {m.group(1)}", "HIGH", m.start(),
             "Use ForAll(Filter(...)) + Collect() instead", table=m.group(1))

    # ── AP7: AddColumns wrapping Dataverse Filter ────────────────────
    for m in re.finditer(r"\bAddColumns\s*\(\s*Filter\s*\(\s*BESA_\w+", formula):
        _add("AP7", "AddColumns wrapping Dataverse Filter", "MEDIUM", m.start(),
             "ClearCollect first, then AddColumns on local collection")

    # ── AP8: Refresh on Dataverse table ──────────────────────────────
    for m in re.finditer(r"\bRefresh\s*\(\s*(BESA_\w+)\s*\)", formula):
        if _in_comment(formula, m.start()):
            continue
        table = m.group(1)
        rest = formula[m.end():]
        has_cc = re.search(rf"\bClearCollect\b.*\b{re.escape(table)}\b", rest)
        sev = "MEDIUM" if has_cc else "LOW"
        label = f"Refresh({table}) before ClearCollect" if has_cc else f"Refresh({table})"
        _add("AP8", label, sev, m.start(),
             "Remove Refresh() -- background sync keeps SQLite current",
             table=table)

    # ── AP10: Date type mismatch ─────────────────────────────────────
    for m in re.finditer(r"'Shift Date'\s*=\s*Text\s*\(", formula):
        _add("AP10", "Text() wrapping Shift Date comparison", "HIGH", m.start(),
             "Remove Text() -- compare date value directly")

    # ── AP11: Direct Dataverse query in auto-evaluating property ─────
    if prop in DISPLAY_PROPS:
        for m in re.finditer(
                r"\b(Filter|LookUp|Sum|CountRows|CountIf|Average|Max|Min)"
                r"\s*\(\s*(BESA_\w+)", formula):
            if _in_comment(formula, m.start()):
                continue
            func, table = m.group(1), m.group(2)
            _add("AP11", f"{func}({table}) in display property '{prop}'",
                 "MEDIUM", m.start(),
                 "Use local collection -- display props fire on every re-render")

    # ── AP6: Not() on nullable boolean ───────────────────────────────
    for m in re.finditer(r"\bNot\s*\(\s*\w+[\.\s]+Adhoc\b", formula):
        _add("AP6", "Not() on nullable boolean Adhoc", "MEDIUM", m.start(),
             "Use (IsBlank(x.Adhoc) || x.Adhoc = false)")

    # ── AP2: Set() / IfError() inside ForAll ─────────────────────────
    forall_ranges = _find_forall_ranges(formula)
    for (fa_start, fa_end) in forall_ranges:
        body = formula[fa_start:fa_end + 1]
        for pat_name, pat in [("Set", r"\bSet\s*\("), ("IfError", r"\bIfError\s*\(")]:
            for sm in re.finditer(pat, body):
                _add("AP2", f"{pat_name}() inside ForAll", "HIGH",
                     fa_start + sm.start(),
                     f"Use Collect() + Set(var, First(col)) after ForAll"
                     if pat_name == "Set" else
                     "Use If(!IsBlank(rec)) instead of IfError()")

    # ── INFO: LookUp as Patch target ─────────────────────────────────
    for m in re.finditer(r"\bPatch\s*\(\s*(BESA_\w+)\s*,\s*LookUp\s*\(", formula):
        if _in_comment(formula, m.start()):
            continue
        table = m.group(1)
        _add("INFO", f"LookUp as Patch target on {table}", "LOW", m.start(),
             "ForAll buffer needed for restricted tables; OK for BESA_TestRuns",
             table=table)

    return violations


# ── File scanner ─────────────────────────────────────────────────────────

def scan_file(filepath):
    """Scan one .fx.yaml file.  Returns list of violation dicts."""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    basename = os.path.basename(filepath)
    content_lines = content.split("\n")
    blocks = extract_formula_blocks(content)

    all_violations = []
    for block in blocks:
        all_violations.extend(_check_block(block, basename, content_lines))

    return all_violations


# ── CLI ──────────────────────────────────────────────────────────────────

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    scan_all = "--all" in sys.argv
    output_json = "--json" in sys.argv
    explicit = [a for a in sys.argv[1:] if not a.startswith("--")]

    if explicit:
        files = explicit
    else:
        pat1 = os.path.join(script_dir, "src", "Src", "*.fx.yaml")
        pat2 = os.path.join(script_dir, "src", "Src", "Components", "*.fx.yaml")
        all_files = sorted(glob.glob(pat1)) + sorted(glob.glob(pat2))

        if scan_all:
            files = all_files
        else:
            # Active screens + all components
            files = [f for f in all_files
                     if os.path.basename(f) in ACTIVE_SCREENS
                     or "Components" in f]

    if not files:
        print("No .fx.yaml files found. Pass paths or run from project root.")
        sys.exit(1)

    # ── Scan ──
    all_violations = []
    files_scanned = []
    for fpath in files:
        if not os.path.isfile(fpath):
            print(f"  SKIP (not found): {fpath}", file=sys.stderr)
            continue
        files_scanned.append(os.path.basename(fpath))
        all_violations.extend(scan_file(fpath))

    # ── Output ──
    if output_json:
        print(json.dumps(all_violations, indent=2))
        sys.exit(1 if any(v["severity"] == "HIGH" for v in all_violations) else 0)

    print("=" * 72)
    print("  CANVAS APP OFFLINE DIAGNOSTICS")
    print("=" * 72)
    print()
    if not scan_all and not explicit:
        print(f"  Mode: active screens + components")
    print(f"  Files scanned: {', '.join(files_scanned)}")
    print()

    if not all_violations:
        print("  No violations found.")
        print()
        print("=" * 72)
        return

    by_sev = defaultdict(list)
    for v in all_violations:
        by_sev[v["severity"]].append(v)

    for sev in ("HIGH", "MEDIUM", "LOW", "INFO"):
        items = by_sev.get(sev, [])
        if not items:
            continue

        print(f"  --- {sev} ({len(items)}) " + "-" * (55 - len(sev)))
        print()

        by_rule = defaultdict(list)
        for v in items:
            by_rule[v["rule"]].append(v)

        for rule in sorted(by_rule):
            group = by_rule[rule]
            print(f"  [{rule}] {group[0]['name']}  ({len(group)}x)")
            for v in group:
                loc = f"{v['file']}:{v['line']}"
                print(f"    {loc:<50s} {v['prop']}")
                print(f"      {v['text'][:120]}")
            print(f"    FIX: {group[0]['fix']}")
            print()

    high = len(by_sev.get("HIGH", []))
    med  = len(by_sev.get("MEDIUM", []))
    low  = len(by_sev.get("LOW", []))
    info = len(by_sev.get("INFO", []))
    total = high + med + low + info
    print("=" * 72)
    print(f"  TOTAL: {total} findings  --  {high} HIGH, {med} MEDIUM, {low} LOW, {info} INFO")
    print("=" * 72)

    sys.exit(1 if high > 0 else 0)


if __name__ == "__main__":
    main()
