"""Qué versión del código está corriendo realmente.

Existe por un problema concreto y repetido: se hacía un cambio, se subía, y
en la app seguía viéndose lo de antes — sin forma de saber si el fallo
estaba en el código, en el despliegue o en la caché del navegador. Cada
diagnóstico costaba varias idas y vueltas.

Con esto, la propia app dice desde qué commit corre. Si el número que
muestra no coincide con el último subido al repositorio, el problema es el
despliegue y no hay que buscar en el código.

Se lee del directorio .git directamente (sin ejecutar `git`, que puede no
estar disponible en el servidor). Si no se puede determinar, devuelve None
y la interfaz simplemente no muestra nada — nunca es un error.
"""
from __future__ import annotations

from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent


def commit_actual() -> str | None:
    """Los primeros 7 caracteres del commit desplegado, o None."""
    try:
        git = _RAIZ / ".git"
        if not git.exists():
            return None
        # En un despliegue con worktree, .git puede ser un archivo que apunta
        # al directorio real.
        if git.is_file():
            destino = git.read_text(encoding="utf-8").strip()
            if destino.startswith("gitdir:"):
                git = Path(destino.split(":", 1)[1].strip())
                if not git.is_absolute():
                    git = (_RAIZ / git).resolve()

        head = (git / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref:"):
            return head[:7]  # HEAD suelto (detached), ya es el sha

        ref = head.split(" ", 1)[1].strip()
        suelto = git / ref
        if suelto.exists():
            return suelto.read_text(encoding="utf-8").strip()[:7]

        # Referencias empaquetadas: es como suele quedar tras un clone.
        empaquetadas = git / "packed-refs"
        if empaquetadas.exists():
            for linea in empaquetadas.read_text(encoding="utf-8").splitlines():
                if linea.strip().endswith(" " + ref) or linea.strip().endswith("\t" + ref):
                    return linea.split()[0][:7]
    except Exception:
        pass
    return None


def rama_actual() -> str | None:
    """Nombre de la rama desplegada, o None si no se puede determinar."""
    try:
        git = _RAIZ / ".git"
        if git.is_file():
            destino = git.read_text(encoding="utf-8").strip()
            if destino.startswith("gitdir:"):
                git = Path(destino.split(":", 1)[1].strip())
                if not git.is_absolute():
                    git = (_RAIZ / git).resolve()
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
        if head.startswith("ref:"):
            return head.split("/")[-1].strip()
    except Exception:
        pass
    return None


def etiqueta_version() -> str:
    """Texto corto listo para mostrar, p. ej. "main · 798f9ab"."""
    rama, commit = rama_actual(), commit_actual()
    if commit and rama:
        return f"{rama} · {commit}"
    if commit:
        return commit
    return "versión no identificada"
