"""Generate opt-in shell integration scripts."""

from tmksh.shell.bash import render_bash_init
from tmksh.shell.zsh import render_zsh_init

__all__ = ["render_bash_init", "render_zsh_init"]
