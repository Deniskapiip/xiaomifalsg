"""Read and atomically edit private configuration without displaying its values."""
import hashlib
import os
from pathlib import Path
import re
import tempfile

from dotenv import dotenv_values, set_key
from sqlalchemy.engine import make_url


class EnvConflict(RuntimeError):
    pass


def read_env(path: Path) -> dict[str, str]:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError("Файл .env не найден")
    try:
        values = dotenv_values(path, encoding="utf-8-sig", interpolate=False)
    except (OSError, UnicodeError):
        raise ValueError("Не удалось прочитать .env в кодировке UTF-8") from None
    return {key: value if value is not None else "" for key, value in values.items()}


def env_fingerprint(path: Path) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        raise ValueError("Не удалось прочитать .env") from None


def update_env(path: Path, updates: dict[str, str], *, expected_fingerprint: str | None = None) -> None:
    path = Path(path)
    if any(not isinstance(key, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) or not isinstance(value, str) or "\n" in value or "\r" in value or "\x00" in value for key, value in updates.items()):
        raise ValueError("Некорректный формат обновления .env")
    try:
        original = path.read_bytes()
    except OSError:
        raise ValueError("Файл .env недоступен для обновления") from None
    fingerprint = hashlib.sha256(original).hexdigest()
    if expected_fingerprint is not None and fingerprint != expected_fingerprint:
        raise EnvConflict("Настройки .env изменились. Проверьте их и запустите снова.")
    descriptor, name = tempfile.mkstemp(prefix=".taoji-env-", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            # Drop the optional UTF-8 BOM so dotenv set_key sees the first key correctly.
            stream.write(original.removeprefix(b"\xef\xbb\xbf"))
        for key, value in updates.items():
            set_key(str(temporary), key, value, quote_mode="always", encoding="utf-8")
        with temporary.open("ab") as stream:
            stream.flush()
            os.fsync(stream.fileno())
        if env_fingerprint(path) != fingerprint:
            raise EnvConflict("Настройки .env изменились. Проверьте их и запустите снова.")
        if os.name != "nt":
            temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def ensure_env(path: Path, example: Path) -> None:
    """Create the initial template exclusively; never overwrite an existing .env."""
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(Path(example).read_bytes())
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        Path(path).unlink(missing_ok=True)
        raise


def sqlite_database_path(value: str, root: Path) -> Path | None:
    try:
        url = make_url(value)
    except Exception:
        raise ValueError("Некорректный DATABASE_URL") from None
    if url.get_backend_name() != "sqlite":
        return None
    if url.drivername not in {"sqlite", "sqlite+aiosqlite"} or not url.database or url.database == ":memory:" or url.database.startswith("file:") or url.query or url.username or url.password or url.host or url.port:
        raise ValueError("Нужен DATABASE_URL обычного файла SQLite, без режима memory и параметров URI")
    database = Path(url.database)
    return (database if database.is_absolute() else Path(root) / database).resolve()
