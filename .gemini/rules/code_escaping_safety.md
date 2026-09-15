# Rule: Code Escaping & Diff Minimality Safety Guardrail

When writing, editing, or inspecting Python code patches (especially regex literals, byte literals, and string escapes):

1. **Raw String Regex Integrity**: Never double-escape backslashes inside raw string literals `r"..."`. `r"\d"` must remain `r"\d"`, NOT `r"\\d"`.
2. **Byte Literal Integrity**: Preserve raw byte escape sequences in byte literals `b"..."` exactly as intended (e.g. `b"\0receipt"` must NOT become `b"\\0receipt"`).
3. **No Trailing Backslashes**: Never leave unintended trailing backslashes `\` at the end of statement lines (such as `if` or `return` statements).
4. **Strict AST & Syntax Verification**: Run static compilation `compile(code_content, filename, 'exec')` or `git diff --check` to verify zero syntax artifacts before committing or opening pull requests.
