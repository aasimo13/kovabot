import asyncio
import logging

from RestrictedPython import compile_restricted, safe_globals
from RestrictedPython.Eval import default_guarded_getiter
from RestrictedPython.Guards import (
    guarded_unpack_sequence,
    safer_getattr,
)
from RestrictedPython.PrintCollector import PrintCollector

logger = logging.getLogger(__name__)

MAX_OUTPUT = 5000
TIMEOUT_SECONDS = 10

# Modules allowed inside the sandbox
_SAFE_MODULES = {
    "math": __import__("math"),
    "statistics": __import__("statistics"),
    "json": __import__("json"),
    "re": __import__("re"),
    "datetime": __import__("datetime"),
    "random": __import__("random"),
    "itertools": __import__("itertools"),
    "collections": __import__("collections"),
}


def _build_sandbox_globals():
    glb = safe_globals.copy()
    glb["__builtins__"] = {
        **glb["__builtins__"],
        "__import__": _restricted_import,
        "abs": abs,
        "all": all,
        "any": any,
        "bin": bin,
        "bool": bool,
        "bytes": bytes,
        "chr": chr,
        "dict": dict,
        "divmod": divmod,
        "enumerate": enumerate,
        "filter": filter,
        "float": float,
        "format": format,
        "frozenset": frozenset,
        "hex": hex,
        "int": int,
        "isinstance": isinstance,
        "len": len,
        "list": list,
        "map": map,
        "max": max,
        "min": min,
        "oct": oct,
        "ord": ord,
        "pow": pow,
        "print": None,  # replaced per-execution
        "range": range,
        "repr": repr,
        "reversed": reversed,
        "round": round,
        "set": set,
        "slice": slice,
        "sorted": sorted,
        "str": str,
        "sum": sum,
        "tuple": tuple,
        "type": type,
        "zip": zip,
    }
    glb["_getiter_"] = default_guarded_getiter
    glb["_unpack_sequence_"] = guarded_unpack_sequence
    glb["_getattr_"] = safer_getattr
    # Allow item access
    glb["_getitem_"] = lambda obj, key: obj[key]
    glb["_write_"] = lambda obj: obj
    glb["_inplacevar_"] = lambda op, x, y: op(x, y)
    return glb


def _restricted_import(name, *args, **kwargs):
    if name in _SAFE_MODULES:
        return _SAFE_MODULES[name]
    raise ImportError(f"Import of '{name}' is not allowed")


def _run_code(code: str) -> str:
    try:
        byte_code = compile_restricted(code, filename="<sandbox>", mode="exec")
    except SyntaxError as e:
        return f"SyntaxError: {e}"

    glb = _build_sandbox_globals()
    glb["_print_"] = PrintCollector
    glb["_getattr_"] = safer_getattr

    # Pre-load safe modules
    for name, mod in _SAFE_MODULES.items():
        glb[name] = mod

    try:
        exec(byte_code, glb)
    except Exception as e:
        return f"{type(e).__name__}: {e}"

    # PrintCollector stores output in the 'printed' variable
    result = glb.get("_print")
    if result is not None:
        result = result()
    else:
        result = ""

    if len(result) > MAX_OUTPUT:
        result = result[:MAX_OUTPUT] + "\n...(output truncated)"
    return result if result else "(no output)"


async def execute_python(code: str) -> str:
    try:
        result = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(None, _run_code, code),
            timeout=TIMEOUT_SECONDS,
        )
        return result
    except asyncio.TimeoutError:
        return f"Execution timed out after {TIMEOUT_SECONDS} seconds."
    except Exception as e:
        logger.error(f"Code execution error: {e}")
        return f"Execution error: {e}"
