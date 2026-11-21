"""A coding agent's tools. Few, general, and each with its rules inside it.

Every path is checked against the workspace. An edit replaces one exact string, and only in a
file this run has read. A command's result starts with its exit code."""
import glob, os, re, subprocess, sys

from src.agent.toolbox import declare

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORKSPACE = os.path.join(ROOT, "workspace")
OUTPUT_LIMIT = 3000


class Workspace:
    def __init__(self, root=WORKSPACE):
        self.root = os.path.realpath(root)
        self.read = set()                  # files read in this run

    def path(self, p):
        full = os.path.realpath(os.path.join(self.root, p))
        if not full.startswith(self.root + os.sep):
            raise PermissionError(f"{p} is outside the repository")
        return full

    def read_file(self, path: str, start: int = 1, end: int = 0) -> dict:
        lines = open(self.path(path)).read().split("\n")
        self.read.add(path)
        end = end or len(lines)
        return {"path": path, "lines": [f"{i:>4}  {lines[i - 1]}" for i in range(start, min(end, len(lines)) + 1)]}

    def search(self, pattern: str, files: str = "**/*") -> dict:
        found = []
        for f in sorted(glob.glob(files, root_dir=self.root, recursive=True)):
            full = os.path.join(self.root, f)
            if not os.path.isfile(full) or "__pycache__" in f or ".pytest_cache" in f:
                continue
            if not pattern:
                found.append(f)
                continue
            for n, line in enumerate(open(full, errors="replace"), 1):
                if re.search(pattern, line):
                    found.append(f"{f}:{n}: {line.rstrip()}")
        return {"pattern": pattern, "matches": found[:60], "more": max(0, len(found) - 60)}

    def edit_file(self, path: str, old: str, new: str) -> dict:
        if path not in self.read:
            return {"error": f"read {path} before editing it"}
        text = open(self.path(path)).read()
        n = text.count(old)
        if n != 1:
            hint = "Include more of the surrounding lines." if n else "Read the file again."
            return {"error": f"old was found {n} times in {path}. "
                             f"It must appear exactly once. {hint}"}
        text = text.replace(old, new)
        open(self.path(path), "w").write(text)
        first = text[:text.index(new)].count("\n") + 1
        last = first + new.count("\n")
        return {"path": path, "now": self.read_file(path, max(1, first - 2), last + 2)["lines"]}

    def write_file(self, path: str, content: str) -> dict:
        full = self.path(path)
        if os.path.exists(full) and path not in self.read:
            return {"error": f"{path} exists; read it before replacing it"}
        os.makedirs(os.path.dirname(full), exist_ok=True)
        open(full, "w").write(content)
        self.read.add(path)
        return {"path": path, "written_lines": content.count("\n") + 1}

    def run(self, command: str, timeout: int = 60) -> dict:
        env = {**os.environ, "PATH": os.path.dirname(sys.executable) + os.pathsep + os.environ["PATH"]}
        try:
            p = subprocess.run(command, shell=True, cwd=self.root, env=env, capture_output=True,
                               text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"exit_code": None, "output": f"stopped after {timeout} s"}
        out = (p.stdout + p.stderr)
        cut = f"\n(cut: {len(out) - OUTPUT_LIMIT} more characters)" if len(out) > OUTPUT_LIMIT else ""
        return {"exit_code": p.returncode, "output": out[-OUTPUT_LIMIT:] + cut}

    def list_tests(self) -> dict:
        found = []
        for f in sorted(glob.glob("tests/**/*.py", root_dir=self.root, recursive=True)):
            full = os.path.join(self.root, f)
            if not os.path.isfile(full) or "__pycache__" in f:
                continue
            for line in open(full, errors="replace"):
                m = re.match(r"\s*def\s+(test_\w+)\s*\(", line)
                if m:
                    found.append(f"{f}::{m.group(1)}")
        return {"tests": found}

    def tools(self):
        return [
            (declare(self.read_file, "Read a file, or lines start to end, with line numbers."), self.read_file),
            (declare(self.search, "Find lines matching a regular expression in files matching a glob. "
                                  "An empty pattern lists the files."), self.search),
            (declare(self.edit_file, "Replace one exact string in a file you have read. old must "
                                     "appear exactly once; include surrounding lines to make it unique."), self.edit_file),
            (declare(self.write_file, "Create a file, or replace one you have read, with content."), self.write_file),
            (declare(self.run, "Run a shell command in the repository, with a time limit in seconds. "
                               "Returns the exit code and the output."), self.run),
            (declare(self.list_tests, "List the test names in tests/."), self.list_tests),
        ]