"""Run model-written calculation scripts in a bounded, restricted subprocess.

Scripts read document numbers only through value(evidence_key), which returns
the current value of a row in the Data table as a Decimal that carries its
provenance: the Data keys it came from and the numbers the script typed into
its arithmetic. Arithmetic, rounding and math/statistics calls propagate it,
so the reported inputs are the sources of the result itself, and every typed
number that shaped the result (or a result number with no Data source at
all, e.g. built from strings) is reported as manual. The typed numbers 1, 100
and 1000 are formula constants (growth b/a-1, percent, per-mille, unit
scaling), not manual numbers; len(), int(), round() and divmod() of traced
values keep their sources. Provenance is decided at
runtime, never from the script text, and the names the runtime provides
cannot be rebound. Scripts can use Decimal, math, statistics, loops,
comprehensions, small helper functions and list/dict methods. There is no file, environment,
network or process access. This is a calculation language for reviewable
scripts, not a hardened multi-tenant Python host.

A succeeded run also returns result_rows, one per value of the result with
the name the script gave it and its Data keys; printed values and the result
show numbers as plain decimals, never as Decimal('...').
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
# Names the runtime provides; rebinding one would change what a script means.
_RESERVED_NAMES = {"value", "Decimal", "decimal", "math", "statistics", "print", *_SAFE_BUILTINS}
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
    except (InvalidOperation, ValueError):  # ValueError: an integer too long to print
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
        bound = []
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bound.append(node.id)
        if isinstance(node, (ast.FunctionDef, ast.Lambda)):
            args = node.args
            names = [a.arg for a in args.posonlyargs + args.args + args.kwonlyargs]
            names += [a.arg for a in (args.vararg, args.kwarg) if a]
            if any(name.startswith("_") for name in names):
                raise ValueError("Private names are not available")
            bound += names + ([node.name] if isinstance(node, ast.FunctionDef) else [])
        if isinstance(node, ast.ExceptHandler) and node.name:
            bound.append(node.name)
        for name in bound:
            if name in _RESERVED_NAMES:
                raise ValueError(f"{name} is a reserved name in calculation scripts; use another name")
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
import json,sys,math,statistics,decimal,types
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
def unique(items):
    return tuple(dict.fromkeys(items))
def is_number(x):
    return isinstance(x,(int,float,Decimal)) and not isinstance(x,bool)
def traced(number, sources, typed):
    out=Decimal.__new__(Traced, number)
    out.sources=frozenset(sources)
    out.typed=unique(typed)
    return out
# (Data keys, typed numbers) of every number in items, looking inside lists.
def provenance(items):
    sources, typed = set(), []
    for x in items:
        if isinstance(x, Traced):
            sources |= x.sources; typed += x.typed
        elif is_number(x):
            typed += typed_of(x)
        elif isinstance(x,(list,tuple)):
            s,t=provenance(x); sources|=s; typed+=t
    return sources, typed
# An operand equal to the identity of the operation (x+0, x*1, x/1) does not change the value.
IDENTITY={'add':0,'sub':0,'mul':1,'truediv':1,'floordiv':1,'pow':1}
# Percent, per-mille and unit scaling (b/a-1, *100, /1000) are formula constants, not copied data.
FORMULA_CONSTANTS={Decimal(1),Decimal(100),Decimal(1000)}
def typed_of(number):
    return () if Decimal(number) in FORMULA_CONSTANTS else (str(number),)
def operands(other, self_sources, self_typed, name):
    if isinstance(other,Traced): return self_sources|other.sources, self_typed+other.typed
    if other==IDENTITY.get(name): return self_sources, self_typed
    return self_sources, self_typed+typed_of(other)
def operator(name, reflected):
    plain=getattr(Decimal,'__'+name+'__')
    def apply(self, other):
        if not isinstance(other,(int,Decimal)) or isinstance(other,bool): return NotImplemented
        left,right=(other,self) if reflected else (self,other)
        number=plain(Decimal(left),Decimal(right))
        if number is NotImplemented: return number
        sources,typed=operands(other,self.sources,self.typed,name)
        return tuple(traced(n,sources,typed) for n in number) if name=='divmod' else traced(number,sources,typed)
    return apply
def same_provenance(method):
    plain=getattr(Decimal,method)
    def apply(self,*args,**kwargs):
        # The argument of quantize/round is a precision, not an operand.
        args=[Decimal(a) if isinstance(a,Decimal) else a for a in args]
        number=plain(Decimal(self),*args,**kwargs)
        return traced(Decimal(number),self.sources,self.typed) if is_number(number) else number
    return apply
# Decimal that carries the Data keys and the typed numbers it was computed from.
class Traced(Decimal):
    def __new__(cls, value='0', context=None):
        if isinstance(value,Traced): return value
        number=Decimal.__new__(cls,value,context)
        number.sources=frozenset()
        number.typed=typed_of(number)
        return number
    # A whole traced number (len(), int()) still works as an index or range bound.
    def __index__(self):
        if self!=self.to_integral_value(): raise TypeError('only a whole number can be an index')
        return int(self)
for _name in ('add','sub','mul','truediv','floordiv','mod','pow','divmod'):
    setattr(Traced,'__'+_name+'__',operator(_name,False))
    setattr(Traced,'__r'+_name+'__',operator(_name,True))
for _method in ('__neg__','__pos__','__abs__','__round__','quantize','sqrt','ln','log10','exp','normalize','to_integral_value'):
    setattr(Traced,_method,same_provenance(_method))
def module_function(fn):
    def call(*args, **kwargs):
        listed=lambda a: list(a) if not is_number(a) and not isinstance(a,(str,dict)) and hasattr(a,'__iter__') else a
        args=[listed(a) for a in args]
        kwargs={k:listed(a) for k,a in kwargs.items()}
        number=fn(*args,**kwargs)
        if not is_number(number): return number
        # Keyword arguments (math.prod(start=...)) shape the result as much as positional ones.
        sources,typed=provenance(args+list(kwargs.values()))
        return traced(Decimal(str(number)) if isinstance(number,float) else Decimal(number),sources,typed)
    return call
def namespace(module, names):
    return types.SimpleNamespace(**{n:(module_function(getattr(module,n)) if callable(getattr(module,n)) else getattr(module,n)) for n in names})
def value(key):
    item=payload['evidence'].get(key)
    if item is None:
        raise KeyError('Unknown evidence key: '+str(key))
    if item.get('data_status')!='valid' or item.get('numeric_value') is None:
        raise ValueError('Evidence is missing or unverified: '+key)
    if key not in used: used.append(key)
    return traced(Decimal(item['numeric_value']),{key},())
# A count of traced values and the whole part of a traced value keep their sources.
def traced_len(items):
    count=len(items)
    sources,_=provenance(list(items.values()) if isinstance(items,dict) else [] if isinstance(items,str) else list(items))
    return traced(Decimal(count),sources,()) if sources else count
def traced_int(x=0, *args):
    number=int(x,*args)
    return traced(Decimal(number),x.sources,x.typed) if isinstance(x,Traced) else number
VIEWS=(list,tuple,set,frozenset,type({}.keys()),type({}.values()),type({}.items()))
# Containers as dict/list with text keys, so the result and print show numbers, never Decimal('...').
def normalized(x):
    if isinstance(x,dict): return {k if isinstance(k,str) else str(k): normalized(v) for k,v in x.items()}
    if isinstance(x,VIEWS): return [normalized(v) for v in x]
    return x
def result_numbers(x):
    if isinstance(x,dict): return [n for v in x.values() for n in result_numbers(v)]
    if isinstance(x,list): return [n for item in x for n in result_numbers(item)]
    return [x] if is_number(x) else []
# One row per value of the result: the name the script gave it and the Data keys it came from.
def result_rows(x, name=None):
    if isinstance(x,dict): return [r for k,v in x.items() for r in result_rows(v, k if name is None else name+' · '+k)]
    if isinstance(x,list): return [r for i,v in enumerate(x) for r in result_rows(v, str(i+1) if name is None else name+' · '+str(i+1))]
    return [{'name':name,'value':str(x) if is_number(x) else x,'source_keys':sorted(x.sources) if isinstance(x,Traced) else []}]
def shown(x, top=True):
    if isinstance(x,dict): return '{'+', '.join(shown(k,False)+': '+shown(v,False) for k,v in x.items())+'}'
    if isinstance(x,list): return '['+', '.join(shown(v,False) for v in x)+']'
    return repr(x) if isinstance(x,str) and not top else str(x)
def captured_print(*args, sep=' ', end='\n'):
    room=payload['max_stdout']-sum(map(len, printed))
    if room>0: printed.append((sep.join(shown(normalized(a)) for a in args)+end)[:room])
safe={name: __builtins__.__dict__[name] for name in payload['builtins']}
safe['len']=traced_len
safe['int']=traced_int
modules={
    'math':namespace(math,payload['modules']['math']),
    'statistics':namespace(statistics,payload['modules']['statistics']),
    'decimal':types.SimpleNamespace(Decimal=Traced,ROUND_HALF_UP=decimal.ROUND_HALF_UP,ROUND_HALF_EVEN=decimal.ROUND_HALF_EVEN),
}
def limited_import(name, globals=None, locals=None, fromlist=(), level=0):
    if level or name not in modules: raise ValueError('Import is not available')
    return modules[name]
safe['__import__']=limited_import
safe['print']=captured_print
env={'__builtins__':safe,'value':value,'Decimal':Traced,**modules}
try:
    exec(compile(payload['code'],'<calculation>','exec'),env,env)
    if 'result' not in env: raise ValueError('Assign the calculation output to result')
    result=normalized(env['result'])
    numbers=result_numbers(result)
    sources=set().union(*(n.sources for n in numbers if isinstance(n,Traced)))
    if not sources: raise ValueError('result must contain numbers computed from value(evidence_key), not copied constants or text')
    manual=unique(t for n in numbers for t in (n.typed if isinstance(n,Traced) else typed_of(n)))
    output=json.dumps({'status':'succeeded','result':result,'result_rows':result_rows(result),'used_evidence_keys':[k for k in used if k in sources],
                       'manual_numbers':list(manual),'traced_numbers':[str(n) for n in numbers if isinstance(n,Traced) and n.sources],
                       'stdout':''.join(printed)},default=str,allow_nan=False)
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
    except (ValueError, SyntaxError, MemoryError, RecursionError) as exc:
        # The parser itself gives up on extreme nesting (MemoryError).
        return {"status": "failed", "error": f"{type(exc).__name__}: {exc}"[:MAX_ERROR_CHARS], "used_evidence_keys": []}
    payload = {
        "max_stdout": MAX_STDOUT_CHARS,
        "max_error": MAX_ERROR_CHARS,
        "code": code,
        "builtins": _SAFE_BUILTINS,
        "modules": {name: sorted(names) for name, names in _MODULE_ATTRIBUTES.items() if name != "decimal"},
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
    return result
