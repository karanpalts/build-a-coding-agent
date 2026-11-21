"""Rules checked around every call: permissions first, then hooks.

Permissions: deny wins; then allow; anything not matched asks the person.
Hooks: the repository owner's code, run before and after each call, every time."""
import fnmatch, os, py_compile, re, tomllib

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def subject(name, args):
    """What a rule is matched against: the command for run, the path for file tools."""
    return f"{name}({args.get('command', args.get('path', args.get('pattern', args.get('name', args.get('question', '')))))})"


class Permissions:
    def __init__(self, path=os.path.join(ROOT, "permissions.toml")):
        rules = tomllib.load(open(path, "rb"))
        self.deny, self.allow = rules.get("deny", []), rules.get("allow", [])

    def check(self, name, args):
        # A chained command is checked part by part: "git add x && git push" is two commands.
        parts = re.split(r"&&|\|\||;|\||\n", args["command"]) if name == "run" else [None]
        decisions = [self.check_one(name, {**args, "command": p.strip()} if p else args) for p in parts]
        for d in ("deny", "ask"):
            if d in decisions:
                return d
        return "allow"

    def check_one(self, name, args):
        s = subject(name, args)
        if any(fnmatch.fnmatch(s, r) for r in self.deny):
            return "deny"
        if any(fnmatch.fnmatch(s, r) for r in self.allow):
            return "allow"
        return "ask"


def ask_person(name, args):
    s = subject(name, args)
    scripted = os.environ.get("ASK_ANSWER")              # for recorded demos: yes or no
    # Asked while the call runs, so this prints just before the step that named it.
    answer = scripted if scripted else input(f"\n  the agent named {s}, and no rule allows it. Allow it? [y/N] ")
    print(f"  asked: {s} -> {answer}")
    return answer.strip().lower() in ("y", "yes")


def before_call(workspace, name, args):
    """A hook: refuse edits to generated files, whatever the permissions say."""
    if name in ("edit_file", "write_file") and args.get("path", "").startswith("src/generated/"):
        return "src/generated/ is generated from the payments schema; change the schema instead"
    if name == "write_file" and args.get("path", "").startswith("tests/") and os.path.exists(workspace.path(args["path"])):
        return f"{args['path']} already exists in tests/; use edit_file instead of replacing the whole file"


def after_call(workspace, name, args, result):
    """A hook: after a Python file changes, check that it still compiles."""
    if name in ("edit_file", "write_file") and args.get("path", "").endswith(".py") and "error" not in result:
        try:
            py_compile.compile(workspace.path(args["path"]), doraise=True)
            result["compile"] = "ok"
        except py_compile.PyCompileError as e:
            result["compile"] = str(e).strip()[-400:]
    return result


def guarded(toolbox, workspace, permissions):
    """Wrap a toolbox so every call passes the permissions and the hooks."""
    call = toolbox.call

    def checked(name, args):
        decision = permissions.check(name, args)
        if decision == "deny":
            return {"error": f"denied by a rule: {subject(name, args)}"}
        if decision == "ask" and not ask_person(name, args):
            return {"error": f"the person said no to {subject(name, args)}"}
        blocked = before_call(workspace, name, args)
        if blocked:
            return {"error": f"blocked by a hook: {blocked}"}
        return after_call(workspace, name, args, call(name, args))

    toolbox.call = checked
    return toolbox