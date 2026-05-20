"""
Fix YAML blank line indentation for Power Apps Canvas App source files.

The Edit tool (and other text editors) strip trailing whitespace from blank lines
inside YAML block scalars (|-, |, |+). This breaks `pac canvas pack` because
the blank lines lose their indentation context.

This script restores indentation on blank lines by looking at surrounding
non-blank lines and using the minimum indentation of the nearest neighbours.

Usage:
    python fix_yaml_indents.py                          # fix all .fx.yaml files in src/Src/
    python fix_yaml_indents.py src/Src/Screen_EngineerHome.fx.yaml   # fix a specific file
    python fix_yaml_indents.py file1.fx.yaml file2.fx.yaml           # fix multiple files
"""

import sys
import os
import glob


def fix_blank_line_indentation(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    fixed = 0
    result = []
    for i, line in enumerate(lines):
        stripped = line.rstrip("\n").rstrip("\r")
        if stripped.strip() == "":
            # Blank line — check if we need to restore indentation
            prev_indent = 0
            next_indent = 0
            for j in range(i - 1, max(i - 5, -1), -1):
                prev_stripped = lines[j].rstrip("\n").rstrip("\r")
                if prev_stripped.strip():
                    prev_indent = len(prev_stripped) - len(prev_stripped.lstrip())
                    break
            for j in range(i + 1, min(i + 5, len(lines))):
                next_stripped = lines[j].rstrip("\n").rstrip("\r")
                if next_stripped.strip():
                    next_indent = len(next_stripped) - len(next_stripped.lstrip())
                    break

            needed = min(prev_indent, next_indent)
            if needed > 0 and len(stripped) < needed:
                result.append(" " * needed + "\n")
                fixed += 1
            else:
                result.append(line)
        else:
            result.append(line)

    if fixed > 0:
        with open(filepath, "w", encoding="utf-8") as f:
            f.writelines(result)

    return fixed


def main():
    if len(sys.argv) > 1:
        files = sys.argv[1:]
    else:
        # Default: all .fx.yaml files in src/Src/
        script_dir = os.path.dirname(os.path.abspath(__file__))
        pattern = os.path.join(script_dir, "src", "Src", "*.fx.yaml")
        files = sorted(glob.glob(pattern))
        if not files:
            print("No .fx.yaml files found in src/Src/. Pass file paths as arguments.")
            sys.exit(1)

    total_fixed = 0
    for fpath in files:
        if not os.path.isfile(fpath):
            print(f"  SKIP (not found): {fpath}")
            continue
        fixed = fix_blank_line_indentation(fpath)
        print(f"  {fpath}: {fixed} blank lines fixed")
        total_fixed += fixed

    print(f"\nTotal: {total_fixed} blank lines fixed across {len(files)} file(s)")


if __name__ == "__main__":
    main()
