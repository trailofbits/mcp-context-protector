"""Common utilities for CLI tools."""

from collections.abc import Iterator

# Standard display width for separators
SEPARATOR_WIDTH = 70


class AnsiColors:
    """ANSI escape codes for terminal colors."""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    CYAN = "\033[36m"


def colorize(text: str, color: str) -> str:
    """Apply ANSI color to text.

    Args:
    ----
        text: The text to colorize
        color: ANSI color code (use AnsiColors constants)

    Returns:
    -------
        Text wrapped with color codes

    """
    return f"{color}{text}{AnsiColors.RESET}"


def truncate_text(
    text: str, max_length: int, ellipsis: str = "...", from_start: bool = True
) -> str:
    """Truncate text with ellipsis if it exceeds max length.

    Args:
    ----
        text: Text to potentially truncate
        max_length: Maximum allowed length
        ellipsis: String to append/prepend when truncating (default: "...")
        from_start: If True, truncate from end; if False, truncate from start

    Returns:
    -------
        Original text if within limit, otherwise truncated text with ellipsis

    """
    if len(text) <= max_length:
        return text

    if from_start:
        # Truncate from the end: "long text..."
        return text[: max_length - len(ellipsis)] + ellipsis
    else:
        # Truncate from the start: "...long text"
        return ellipsis + text[-(max_length - len(ellipsis)) :]


def print_separator(char: str = "=", newline_before: bool = False) -> None:
    """Print a separator line.

    Args:
    ----
        char: Character to use for the separator (default: "=")
        newline_before: Whether to print a newline before the separator

    """
    prefix = "\n" if newline_before else ""
    print(f"{prefix}{char * SEPARATOR_WIDTH}")


def display_colored_diff(diff: Iterator[str]) -> None:
    """Display a unified diff with color highlighting.

    Args:
    ----
        diff: Iterator of diff lines from difflib.unified_diff

    """
    for line in diff:
        if line.startswith("+++") or line.startswith("---"):
            print(colorize(line, AnsiColors.BOLD), end="")
        elif line.startswith("@@"):
            print(colorize(line, AnsiColors.CYAN), end="")
        elif line.startswith("+"):
            print(colorize(line, AnsiColors.GREEN), end="")
        elif line.startswith("-"):
            print(colorize(line, AnsiColors.RED), end="")
        else:
            print(line, end="")


def confirm_prompt(prompt: str, default: str = "n") -> bool:
    """Ask for user confirmation with a yes/no prompt.

    Args:
    ----
        prompt: The question to ask the user
        default: Default answer if empty ('y' or 'n')

    Returns:
    -------
        True if user confirms, False otherwise

    """
    if default.lower() == "y":
        suffix = " [Y/n]: "
        accept_values = ["", "y", "yes"]
        reject_values = ["n", "no"]
    else:
        suffix = " [y/N]: "
        accept_values = ["y", "yes"]
        reject_values = ["", "n", "no"]

    while True:
        response = input(prompt + suffix).strip().lower()
        if response in accept_values:
            return True
        elif response in reject_values:
            return False
        else:
            print("Please enter 'y' for yes or 'n' for no.")
