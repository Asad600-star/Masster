#!/usr/bin/env python3
"""Обезличивание выгрузок, скачанных через интерфейс Moodle.

Выгрузка из веб-интерфейса Moodle (Отчёты → Логи, Оценки → Экспорт)
содержит ФИО студентов в открытом виде. Этот скрипт заменяет их на
необратимые хеши и удаляет остальные персональные поля.

ЗАПУСКАТЬ У СЕБЯ НА КОМПЬЮТЕРЕ, до отправки файлов кому бы то ни было.

    python3 scripts/anonymize_moodle_export.py папка_с_выгрузкой

Скрипт создаст рядом папку "<имя>_anon" с очищенными файлами и
запишет соль в отдельный файл salt.txt. Соль храни у себя: без неё
восстановить, кто есть кто, невозможно; с ней — тривиально.

Требуется только стандартная библиотека Python, ничего ставить не надо.
"""
import argparse
import csv
import hashlib
import re
import secrets
import string
import sys
from pathlib import Path

# Колонки, которые вырезаются целиком. Сопоставление регистронезависимое,
# по вхождению подстроки — заголовки в Moodle зависят от языка интерфейса.
DROP_PATTERNS = [
    "email", "почт", "e-mail",
    "phone", "телефон",
    "address", "адрес",
    "city", "город",
    "country", "стран",
    "idnumber", "идентификационный",
    "username", "логин",
    "birth", "рожден",
    "ip", "ip-адрес",
    "description", "описание",
]

# Колонки, значения которых заменяются на хеш (это идентификаторы людей).
HASH_PATTERNS = [
    "полное имя", "full name", "имя пользователя", "user full name",
    "затронутый пользователь", "affected user",
    "фамилия", "surname", "lastname", "last name",
    "имя", "firstname", "first name",
    "участник", "participant",
    "userid", "id пользователя",
]


def make_salt(n=48):
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(n))


def anon(value, salt):
    v = (value or "").strip()
    if not v or v in ("-", "—"):
        return ""
    return hashlib.sha256((v + salt).encode("utf-8")).hexdigest()


def classify(header):
    """Возвращает 'drop', 'hash' или 'keep' для колонки."""
    h = (header or "").strip().lower()
    if any(p in h for p in DROP_PATTERNS):
        return "drop"
    if any(p in h for p in HASH_PATTERNS):
        return "hash"
    return "keep"


def sniff_dialect(path):
    """Moodle отдаёт то запятую, то точку с запятой, то таб."""
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        sample = f.read(8192)
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        return csv.excel


def process_file(src, dst, salt):
    dialect = sniff_dialect(src)
    with open(src, "r", encoding="utf-8-sig", errors="replace", newline="") as fin:
        reader = csv.reader(fin, dialect)
        try:
            header = next(reader)
        except StopIteration:
            return None

        actions = [classify(h) for h in header]
        keep_idx = [i for i, a in enumerate(actions) if a != "drop"]
        new_header = [
            (header[i] + "_hash" if actions[i] == "hash" else header[i])
            for i in keep_idx
        ]

        rows = 0
        with open(dst, "w", encoding="utf-8", newline="") as fout:
            writer = csv.writer(fout)
            writer.writerow(new_header)
            for row in reader:
                if not row:
                    continue
                row += [""] * (len(header) - len(row))
                out = [
                    anon(row[i], salt) if actions[i] == "hash" else row[i]
                    for i in keep_idx
                ]
                writer.writerow(out)
                rows += 1

    return {
        "rows": rows,
        "dropped": [header[i] for i, a in enumerate(actions) if a == "drop"],
        "hashed": [header[i] for i, a in enumerate(actions) if a == "hash"],
    }


LEFTOVER_PATTERNS = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "адрес электронной почты"),
    (re.compile(r"\+?\d[\d\s()-]{8,}\d"), "похоже на телефон"),
]


def audit(path, max_hits=5):
    """Финальная проверка: вдруг что-то персональное осталось в тексте."""
    hits = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for lineno, line in enumerate(f, 1):
            for rx, label in LEFTOVER_PATTERNS:
                m = rx.search(line)
                if m:
                    hits.append((lineno, label, m.group()[:40]))
                    if len(hits) >= max_hits:
                        return hits
    return hits


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("indir", help="папка с CSV, скачанными из Moodle")
    ap.add_argument("--salt", help="использовать существующую соль "
                                   "(если догружаешь данные к прежним)")
    args = ap.parse_args()

    src_dir = Path(args.indir)
    if not src_dir.is_dir():
        sys.exit(f"Не папка: {src_dir}")

    files = sorted(list(src_dir.glob("*.csv")) + list(src_dir.glob("*.txt")))
    if not files:
        sys.exit(f"В {src_dir} нет файлов .csv или .txt")

    out_dir = src_dir.parent / (src_dir.name + "_anon")
    out_dir.mkdir(exist_ok=True)

    salt = args.salt or make_salt()
    salt_file = out_dir.parent / "salt.txt"
    if not args.salt:
        salt_file.write_text(salt + "\n", encoding="utf-8")

    print(f"Обрабатываю {len(files)} файлов\n")
    problems = []

    for src in files:
        dst = out_dir / (src.stem + ".csv")
        info = process_file(src, dst, salt)
        if info is None:
            print(f"  {src.name}: пустой, пропущен")
            continue

        print(f"  {src.name}  ->  {dst.name}   ({info['rows']} строк)")
        if info["hashed"]:
            print(f"      захешировано: {', '.join(info['hashed'])}")
        if info["dropped"]:
            print(f"      удалено:      {', '.join(info['dropped'])}")

        left = audit(dst)
        if left:
            problems.append((dst.name, left))

    print("\n" + "=" * 62)
    if problems:
        print("⚠  ПРОВЕРЬ ВРУЧНУЮ — возможны остатки персональных данных:\n")
        for name, hits in problems:
            for lineno, label, sample in hits:
                print(f"   {name}, строка {lineno}: {label} — {sample}")
        print("\n   Открой эти файлы и удали соответствующие колонки,")
        print("   прежде чем куда-либо отправлять.")
    else:
        print("✓  Автопроверка не нашла почт и телефонов в результате.")

    print(f"\nГотовые файлы: {out_dir}/")
    if not args.salt:
        print(f"Соль записана:  {salt_file}")
        print("\n⚠  Перенеси salt.txt в надёжное место и НЕ отправляй его")
        print("   вместе с данными. Пока соль только у тебя, восстановить")
        print("   по хешу конкретного человека невозможно.")
    print("\nПеред отправкой всё равно открой пару файлов глазами.")


if __name__ == "__main__":
    main()
