#!/usr/bin/env python3
"""Генератор синтетических данных, повторяющих схему выгрузки из Moodle.

    ⚠️  ЭТО НЕ ДАННЫЕ ИССЛЕДОВАНИЯ.  ⚠️

Файлы, которые создаёт этот скрипт, нужны ровно для одного: проверить,
что пайплайн обработки работает, ДО того как придёт настоящая выгрузка.
Ни одна цифра отсюда не может попасть в статью.

Структура и типы полей в точности совпадают с тем, что отдают запросы
из scripts/moodle_export_phpmyadmin.sql.

    python3 analysis/make_synthetic.py -o data/synthetic
"""
import argparse
import csv
import hashlib
import math
import random
from pathlib import Path

SEED = 20260801
EVENT_CATEGORIES = [
    "course_view", "resource_view", "forum_post",
    "forum_read", "submission", "quiz_attempt", "login", "other",
]
MODES = ["distance", "hybrid", "onsite"]


def student_hash(i):
    """Тот же формат, что даёт SHA2(...) в SQL: 64 hex-символа."""
    return hashlib.sha256(f"synthetic-student-{i}".encode()).hexdigest()


def generate(n_courses, n_students, weeks, rng):
    courses, enrolments, activity, grades, submissions, modes = [], [], [], [], [], []

    students = [student_hash(i) for i in range(n_students)]

    for cid in range(1000, 1000 + n_courses):
        mode = rng.choice(MODES)
        n_enrolled = rng.randint(12, 45)
        roster = rng.sample(students, n_enrolled)
        n_assignments = rng.randint(3, 8)

        courses.append({
            "course_id": cid,
            "course_code": f"CRS{cid}",
            "moodle_display_format": rng.choice(["topics", "weeks"]),
            "category": rng.choice(["Engineering", "Economics", "Pedagogy"]),
            "start_date": "2024-09-02 00:00:00",
            "end_date": "2025-01-20 00:00:00",
            "n_students": n_enrolled,
        })
        modes.append({"course_id": cid, "mode": mode})

        for s in roster:
            enrolments.append({
                "student_hash": s, "course_id": cid,
                "enrolled_at": "2024-09-02 00:00:00",
            })

            # Скрытые характеристики студента. Активность в дистанционных
            # курсах выше: там LMS — единственный канал взаимодействия.
            base_rate = rng.lognormvariate(2.0, 0.7)
            if mode == "distance":
                base_rate *= 1.6
            elif mode == "onsite":
                base_rate *= 0.7

            # Регулярность: доля недель, в которые студент вообще заходил.
            regularity = rng.betavariate(2.5, 1.8)

            weekly_counts = []
            for w in range(weeks):
                if rng.random() > regularity:
                    weekly_counts.append(0)
                    continue
                n = max(1, int(rng.gauss(base_rate, base_rate * 0.4)))
                weekly_counts.append(n)
                # Разносим события по категориям
                remaining = n
                for cat in rng.sample(EVENT_CATEGORIES, k=rng.randint(2, 4)):
                    if remaining <= 0:
                        break
                    k = rng.randint(1, remaining)
                    remaining -= k
                    activity.append({
                        "student_hash": s, "course_id": cid, "week_num": w,
                        "event_category": cat, "n_events": k,
                        "active_days": min(k, rng.randint(1, 5)),
                    })

            total = sum(weekly_counts)
            active_weeks = sum(1 for x in weekly_counts if x > 0)

            # Итоговая оценка. Заложена умеренная связь и с регулярностью,
            # и с объёмом — чтобы пайплайн мог их развести. Конкретные
            # веса произвольны и ничего не означают.
            score = (
                38
                + 34 * regularity
                + 9 * math.log1p(total) / 3
                + rng.gauss(0, 9)
            )
            grade_pct = max(0.0, min(100.0, score))
            grades.append({
                "student_hash": s, "course_id": cid, "item_type": "course",
                "item_module": "", "raw_grade": round(grade_pct, 2),
                "final_grade": round(grade_pct, 2), "grade_max": 100,
                "grade_pct": round(grade_pct, 2),
            })

            for a in range(n_assignments):
                if rng.random() > regularity * 0.9:
                    continue                       # задание не сдано
                due_week = int((a + 1) * weeks / (n_assignments + 1))
                lead = rng.gauss(48 * regularity, 40)
                submissions.append({
                    "student_hash": s, "course_id": cid,
                    "assignment_id": cid * 100 + a,
                    "due_week_num": due_week, "status": "submitted",
                    "lead_time_hours": round(lead, 2),
                    "on_time": 1 if lead >= 0 else 0,
                })

    return {
        "courses.csv": courses,
        "enrolments.csv": enrolments,
        "weekly_activity.csv": activity,
        "grades.csv": grades,
        "submissions.csv": submissions,
        "course_modes.csv": modes,
    }


def write_csv(path, rows):
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-o", "--outdir", default="data/synthetic")
    ap.add_argument("--courses", type=int, default=30)
    ap.add_argument("--students", type=int, default=600)
    ap.add_argument("--weeks", type=int, default=16)
    args = ap.parse_args()

    rng = random.Random(SEED)
    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)

    tables = generate(args.courses, args.students, args.weeks, rng)
    for name, rows in tables.items():
        write_csv(out / name, rows)
        print(f"  {name:24} {len(rows):>7} строк")

    marker = out / "СИНТЕТИКА_НЕ_ДЛЯ_СТАТЬИ.txt"
    marker.write_text(
        "Данные в этой папке сгенерированы случайно скриптом\n"
        "analysis/make_synthetic.py для проверки работоспособности\n"
        "пайплайна. Это не результаты исследования. Не цитировать,\n"
        "не помещать в статью, не путать с настоящей выгрузкой.\n",
        encoding="utf-8",
    )
    print(f"\nЗаписано в {out}/")


if __name__ == "__main__":
    main()
