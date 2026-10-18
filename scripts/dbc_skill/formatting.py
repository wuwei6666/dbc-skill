import json
import sys


def _format_value(value):
    if isinstance(value, bool):
        return "yes" if value else "no"
    if value is None:
        return "none"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def emit_result(operation, result, json_output):
    if json_output:
        print(
            json.dumps(
                {"success": True, "operation": operation, "result": result},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return

    if not result:
        print(f"{operation} succeeded.")
        return
    for key, value in result.items():
        label = key.replace("_", " ").capitalize()
        print(f"{label}: {_format_value(value)}")


def emit_error(operation, message, json_output):
    if json_output:
        print(
            json.dumps(
                {"success": False, "operation": operation, "error": message},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    else:
        print(f"Error: {message}", file=sys.stderr)
