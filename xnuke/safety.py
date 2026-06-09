import sys

PHRASE = "DELETE EVERYTHING"


def require_typed_confirmation(category: str) -> bool:
    sys.stderr.write(
        f"\nYou are about to permanently delete: {category}\n"
        f"This action is irreversible.\n"
        f"Type exactly: {PHRASE}\n> "
    )
    sys.stderr.flush()
    try:
        line = input().strip()
    except EOFError:
        return False
    return line == PHRASE
