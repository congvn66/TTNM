"""Run model-written calculation scripts in a bounded, restricted subprocess.

Scripts read document numbers only through value(evidence_key), which returns
the current value of a row in the Data table and records exactly which rows
were used. They can use Decimal, math, statistics, loops, comprehensions,
small helper functions and list/dict methods. There is no file, environment,
network or process access. This is a calculation language for reviewable
scripts, not a hardened multi-tenant Python host.
"""

# AST node kinds are rejected as invalid programs, not as Python argument types.
# ruff: noqa: TRY004
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import time
from decimal import Decimal, InvalidOperation

MAX_CODE_CHARS = 12_000
MAX_STDOUT_CHARS = 4_000
MAX_ERROR_CHARS = 600

_SAFE_BUILTINS = (
    "abs", "all", "any", "bool", "dict", "divmod", "enumerate", "filter", "float", "int", "isinstance",
    "len", "list", "map", "max", "min", "pow", "range", "reversed", "round", "set", "sorted", "str", "sum",
    "tuple", "zip",
)
_MODULE_ATTRIBUTES = {
    "math": {"sqrt", "pow", "log", "log10", "exp", "floor", "ceil", "isfinite", "fsum", "prod", "pi", "e"},
    "statistics": {"mean", "median", "stdev", "pstdev", "variance", "pvariance", "fmean"},
    "decimal": {"Decimal", "ROUND_HALF_UP", "ROUND_HALF_EVEN"},
}
# Public methods of list/dict/set/str/Decimal values. str.format/format_map are
# excluded because format strings can traverse attributes.
_VALUE_METHODS = {
    "append", "extend", "insert", "pop", "remove", "sort", "reverse", "copy", "count", "index",
    "items", "keys", "values", "get", "setdefault", "update", "add",
    "join", "split", "strip", "lower", "upper", "replace", "startswith", "endswith",
    "quantize", "sqrt", "ln", "log10", "exp", "is_finite", "is_zero", "normalize", "to_integral_value",
}
# Not in the runtime namespace either; rejected early with a clear message.
_BLOCKED_NAMES = {
    "getattr", "setattr", "delattr", "hasattr", "eval", "exec", "compile", "open", "globals", "locals", "vars",
    "dir", "type", "object", "super", "breakpoint", "input", "help", "memoryview", "classmethod",
    "staticmethod", "property", "id", "exit", "quit",
}
_FORBIDDEN_NODES = (
    ast.ClassDef, ast.AsyncFunctionDef, ast.Await, ast.AsyncFor, ast.AsyncWith, ast.With,
    ast.Global, ast.Nonlocal, ast.Match,
)
# Small integers and scale factors are formula constants, not copied data.
_COMMON_CONSTANTS = {Decimal(n) for n in (24, 52, 60, 100, 365, 1000, 1_000_000, 1_000_000_000)}


def _is_document_like(number):
    if abs(number) in _COMMON_CONSTANTS:
        return False
    return number != number.to_integral_value() or abs(number) > 12


def _literal_number(node):
    value = node.value
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = Decimal(str(value).replace(",", ""))
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


_FORMULA_CONSTANTS = {Decimal(n) for n in (0, 1, 2, 100, 1000, 1_000_000, 1_000_000_000)}


def manual_numbers(code):
    """Numbers typed into the script rather than read with value(); shown to users."""
    tree = ast.parse(code)
    rounding_digits = {
        id(node.args[1])
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "round" and len(node.args) > 1
    }
    found = []
    constants = [node for node in ast.walk(tree) if isinstance(node, ast.Constant)]
    for node in sorted(constants, key=lambda n: (n.lineno, n.col_offset)):
        if id(node) not in rounding_digits:
            number = _literal_number(node)
            if number is not None and abs(number) not in _FORMULA_CONSTANTS and str(node.value) not in found:
                found.append(str(node.value))
    return found


def validate_script(code, evidence=None):
    """Reject constructs outside the calculation language before running."""
    if len(code) > MAX_CODE_CHARS:
        raise ValueError("Script too large")
    tree = ast.parse(code)
    copied = {}
    for item in (evidence or {}).values():
        try:
            number = Decimal(str(item.get("numeric_value")))
        except InvalidOperation:
            continue
        if number.is_finite() and _is_document_like(number):
            copied.setdefault(number, item["evidence_key"])
    for node in ast.walk(tree):
        if isinstance(node, _FORBIDDEN_NODES):
            raise ValueError(f"Unsupported calculation statement: {type(node).__name__}")
        if isinstance(node, ast.Import) and any(
            alias.name not in _MODULE_ATTRIBUTES or alias.asname not in {None, alias.name} for alias in node.names
        ):
            raise ValueError("Only decimal/math/statistics imports without aliases are available")
        if isinstance(node, ast.ImportFrom) and (
            node.level
            or node.module not in _MODULE_ATTRIBUTES
            or any(a.name not in _MODULE_ATTRIBUTES[node.module] or a.asname not in {None, a.name} for a in node.names)
        ):
            raise ValueError("Import is not available")
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise ValueError("Private names are not available")
        if isinstance(node, ast.Name) and node.id in _BLOCKED_NAMES:
            raise ValueError(f"{node.id} is not available in calculation scripts")
        if isinstance(node, (ast.FunctionDef, ast.Lambda)):
            args = node.args
            names = [a.arg for a in args.posonlyargs + args.args + args.kwonlyargs]
            names += [a.arg for a in (args.vararg, args.kwarg) if a]
            if any(name.startswith("_") for name in names):
                raise ValueError("Private names are not available")
        if isinstance(node, ast.Attribute):
            module = node.value.id if isinstance(node.value, ast.Name) else None
            if node.attr not in _MODULE_ATTRIBUTES.get(module, set()) and node.attr not in _VALUE_METHODS:
                raise ValueError(f"Attribute .{node.attr} is not available")
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                raise ValueError("Cannot change object attributes")
        if isinstance(node, ast.Constant) and copied:
            number = _literal_number(node)
            if number is not None and number in copied:
                raise ValueError(
                    f"Document number {node.value!r} is copied into the code; read it with value('{copied[number]}')"
                )
    return code


_RUNNER = r"""
import json,sys,math,statistics,decimal
from decimal import Decimal
try: import resource
except ImportError: resource=None
def limit(name, value):
    # Windows has no resource module and macOS rejects RLIMIT_AS (ValueError);
    # a limit the OS lacks must not stop the calculation. The parent's
    # wall-clock timeout bounds every script, and where RLIMIT_AS does not
    # work the parent watches memory.
    try: resource.setrlimit(getattr(resource, name), (value, value))
    except (ValueError, OSError, AttributeError): pass
limit('RLIMIT_CPU', 2)
limit('RLIMIT_AS', 256*1024*1024)
limit('RLIMIT_FSIZE', 0)
limit('RLIMIT_NOFILE', 16)
payload=json.load(sys.stdin)
used=[]
printed=[]
def value(key):
    item=payload['evidence'].get(key)
    if item is None:
        raise KeyError('Unknown evidence key: '+str(key))
    if item.get('data_status')!='valid' or item.get('numeric_value') is None:
        raise ValueError('Evidence is missing or unverified: '+key)
    if key not in used: used.append(key)
    return Decimal(item['numeric_value'])
def captured_print(*args, sep=' ', end='\n'):
    room=payload['max_stdout']-sum(map(len, printed))
    if room>0: printed.append((sep.join(map(str, args))+end)[:room])
safe={name: __builtins__.__dict__[name] for name in payload['builtins']}
modules={'math':math,'statistics':statistics,'decimal':decimal}
def limited_import(name, globals=None, locals=None, fromlist=(), level=0):
    if level or name not in modules: raise ValueError('Import is not available')
    return modules[name]
safe['__import__']=limited_import
safe['print']=captured_print
env={'__builtins__':safe,'value':value,'Decimal':Decimal,**modules}
try:
    exec(compile(payload['code'],'<calculation>','exec'),env,env)
    if 'result' not in env: raise ValueError('Assign the calculation output to result')
    if not used: raise ValueError('Read document numbers with value(evidence_key), not copied constants')
    output=json.dumps({'status':'succeeded','result':env['result'],'used_evidence_keys':used,'stdout':''.join(printed)},default=str,allow_nan=False)
    if len(output)>30000: raise ValueError('Calculation result too large')
    print(output)
except Exception as exc:
    print(json.dumps({'status':'failed','error':(type(exc).__name__+': '+str(exc))[:payload['max_error']],'used_evidence_keys':used,'stdout':''.join(printed)},default=str))
"""


TIME_LIMIT_SECONDS = 4
MEMORY_LIMIT_BYTES = 256 * 1024 * 1024
# macOS refuses every memory rlimit (RLIMIT_AS/DATA/RSS) and Windows has none,
# so there the script's memory is watched from this process and the script is
# killed when it grows past the limit. Elsewhere RLIMIT_AS in the runner
# enforces it.
_WATCH_MEMORY = sys.platform in {"darwin", "win32"}
_POLL_SECONDS = 0.05


def _windows_rss_bytes(process):
    """Working set of a child process on Windows, or 0 when it cannot be read."""
    import ctypes
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
            (name, ctypes.c_size_t)
            for name in (
                "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
                "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage",
            )
        ]

    counters = Counters(cb=ctypes.sizeof(Counters))
    handle = wintypes.HANDLE(int(process._handle))
    if not ctypes.WinDLL("psapi").GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
        return 0
    return counters.WorkingSetSize


def _rss_bytes(process):
    """Resident memory of a child process, or 0 when it cannot be read."""
    if sys.platform == "win32":
        try:
            return _windows_rss_bytes(process)
        except (AttributeError, OSError, TypeError, ValueError):
            return 0
    pid = process.pid
    try:
        out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True, timeout=1, check=False).stdout
        return int(out.strip() or 0) * 1024
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return 0


def _child_env():
    """No parent variables; Windows needs SYSTEMROOT to start Python."""
    return {"SYSTEMROOT": os.environ["SYSTEMROOT"]} if "SYSTEMROOT" in os.environ else {}


def _run_runner(payload_json):
    """(returncode, stdout) of the sandbox runner, or an error message."""
    process = subprocess.Popen(
        [sys.executable, "-I", "-c", _RUNNER],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=_child_env(),
    )
    deadline = time.monotonic() + TIME_LIMIT_SECONDS
    pending_input = payload_json
    while True:
        wait = _POLL_SECONDS if _WATCH_MEMORY else max(0.01, deadline - time.monotonic())
        try:
            stdout, _ = process.communicate(pending_input, timeout=wait)
            return process.returncode, stdout
        except subprocess.TimeoutExpired:
            pending_input = None  # already being written; must not be sent twice
        if time.monotonic() >= deadline:
            error = "Calculation exceeded time limit"
        elif _WATCH_MEMORY and _rss_bytes(process) > MEMORY_LIMIT_BYTES:
            error = f"Calculation used more than {MEMORY_LIMIT_BYTES // (1024 * 1024)} MB of memory"
        else:
            continue
        process.kill()
        process.communicate()
        return error


def run_calculation(code, evidence):
    """Execute a validated script; evidence maps key -> current Data row."""
    try:
        validate_script(code, evidence)
    except (ValueError, SyntaxError) as exc:
        return {"status": "failed", "error": f"{type(exc).__name__}: {exc}"[:MAX_ERROR_CHARS], "used_evidence_keys": []}
    payload = {
        "max_stdout": MAX_STDOUT_CHARS,
        "max_error": MAX_ERROR_CHARS,
        "code": code,
        "builtins": _SAFE_BUILTINS,
        "evidence": {
            key: {"numeric_value": item.get("numeric_value"), "data_status": item.get("data_status")}
            for key, item in evidence.items()
        },
    }
    outcome = _run_runner(json.dumps(payload))
    if isinstance(outcome, str):
        return {"status": "failed", "error": outcome, "used_evidence_keys": []}
    returncode, stdout = outcome
    if returncode or not stdout.strip():
        return {"status": "failed", "error": "Calculation process stopped (CPU/memory limit)", "used_evidence_keys": []}
    try:
        result = json.loads(stdout)
    except json.JSONDecodeError:
        return {"status": "failed", "error": "Calculation output was not JSON", "used_evidence_keys": []}
    result["manual_numbers"] = manual_numbers(code)
    return result
