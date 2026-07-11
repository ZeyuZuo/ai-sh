"""Generate opt-in shell integration scripts."""

from ai_sh.shell.bash import render_bash_init
from ai_sh.shell.zsh import render_zsh_init

__all__ = ["render_bash_init", "render_zsh_init"]
