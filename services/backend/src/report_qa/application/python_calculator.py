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
import subprocess
import sys
from decimal import Decimal, InvalidOperation

MAX_CODE_CHARS = 12_000

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
import json,sys,math,statistics,resource,decimal
from decimal import Decimal
resource.setrlimit(resource.RLIMIT_CPU,(2,2))
resource.setrlimit(resource.RLIMIT_AS,(256*1024*1024,256*1024*1024))
resource.setrlimit(resource.RLIMIT_FSIZE,(0,0))
resource.setrlimit(resource.RLIMIT_NOFILE,(16,16))
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
    if sum(map(len, printed)) < 4000: printed.append(sep.join(map(str, args))+end)
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
    print(json.dumps({'status':'failed','error':type(exc).__name__+': '+str(exc),'used_evidence_keys':used,'stdout':''.join(printed)},default=str))
"""


def run_calculation(code, evidence):
    """Execute a validated script; evidence maps key -> current Data row."""
    try:
        validate_script(code, evidence)
    except (ValueError, SyntaxError) as exc:
        return {"status": "failed", "error": f"{type(exc).__name__}: {exc}", "used_evidence_keys": []}
    payload = {
        "code": code,
        "builtins": _SAFE_BUILTINS,
        "evidence": {
            key: {"numeric_value": item.get("numeric_value"), "data_status": item.get("data_status")}
            for key, item in evidence.items()
        },
    }
    try:
        process = subprocess.run(
            [sys.executable, "-I", "-c", _RUNNER],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=4,
            env={},
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"status": "failed", "error": "Calculation exceeded time limit", "used_evidence_keys": []}
    if process.returncode or not process.stdout.strip():
        return {"status": "failed", "error": "Calculation process stopped (CPU/memory limit)", "used_evidence_keys": []}
    try:
        return json.loads(process.stdout)
    except json.JSONDecodeError:
        return {"status": "failed", "error": "Calculation output was not JSON", "used_evidence_keys": []}
