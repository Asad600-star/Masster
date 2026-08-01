#!/usr/bin/env python3
"""Сборка признаков из выгрузки Moodle.

Читает пять CSV, склеивает их в одну таблицу «студент × курс» с набором
поведенческих индикаторов и итоговой оценкой.

    python3 analysis/features.py data/raw -o data/processed/features.csv

Ключевой признак — regularity_entropy: нормированная энтропия Шеннона
распределения активности студента по неделям курса. Именно она проверяет
гипотезу H1 (регулярность важнее объёма).
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

EVENT_COLS = [
    "course_view", "resource_view", "forum_post",
    "forum_read", "submission", "quiz_attempt", "login", "other",
]


def read_table(directory, name, required=True):
    """Читает CSV; для weekly_activity склеивает части, если выгрузка
    делалась по семестрам (weekly_activity_1.csv, _2.csv и т.д.)."""
    direct = directory / name
    if direct.exists():
        return pd.read_csv(direct)

    stem = Path(name).stem
    parts = sorted(directory.glob(f"{stem}_*.csv"))
    if parts:
        print(f"  {name}: склеиваю {len(parts)} частей", file=sys.stderr)
        return pd.concat([pd.read_csv(p) for p in parts], ignore_index=True)

    if required:
        raise FileNotFoundError(f"не найден {direct} (и частей {stem}_*.csv тоже нет)")
    print(f"  {name}: нет, пропускаю", file=sys.stderr)
    return None


def normalized_entropy(counts):
    """Нормированная энтропия Шеннона, 0..1.

    1 — активность распределена равномерно по всем неделям курса.
    0 — вся активность сосредоточена в одной неделе.

    Нормировка по числу недель курса обязательна: без неё длинные курсы
    получают систематически более высокую энтропию, и признак начинает
    мерить длительность курса, а не поведение студента.
    """
    counts = np.asarray(counts, dtype=float)
    total = counts.sum()
    if total <= 0 or len(counts) <= 1:
        return 0.0
    p = counts[counts > 0] / total
    h = -(p * np.log(p)).sum()
    return float(h / np.log(len(counts)))


def build_weekly_matrix(activity, course_weeks):
    """Матрица «студент-курс × неделя» с суммой событий."""
    per_week = (
        activity.groupby(["student_hash", "course_id", "week_num"])["n_events"]
        .sum()
        .reset_index()
    )
    rows = []
    for (sh, cid), grp in per_week.groupby(["student_hash", "course_id"]):
        n_weeks = course_weeks.get(cid, int(grp["week_num"].max()) + 1)
        vec = np.zeros(max(n_weeks, 1))
        for _, r in grp.iterrows():
            w = int(r["week_num"])
            if 0 <= w < len(vec):
                vec[w] += r["n_events"]
        rows.append({
            "student_hash": sh,
            "course_id": cid,
            "regularity_entropy": normalized_entropy(vec),
            "n_active_weeks": int((vec > 0).sum()),
            "n_weeks_in_course": len(vec),
            "active_week_ratio": float((vec > 0).sum() / len(vec)),
            "first_week_events": float(vec[0]) if len(vec) else 0.0,
            "first_4w_events": float(vec[:4].sum()),
            "peak_week_share": float(vec.max() / vec.sum()) if vec.sum() else 0.0,
        })
    return pd.DataFrame(rows)


def build(directory):
    directory = Path(directory)
    courses = read_table(directory, "courses.csv")
    activity = read_table(directory, "weekly_activity.csv")
    grades = read_table(directory, "grades.csv")
    submissions = read_table(directory, "submissions.csv", required=False)
    modes = read_table(directory, "course_modes.csv", required=False)
    background = read_table(directory, "student_background.csv", required=False)

    # Длительность курса в неделях — из максимальной наблюдаемой недели.
    course_weeks = (
        activity.groupby("course_id")["week_num"].max().add(1).astype(int).to_dict()
    )

    # --- объём и типы активности ---
    totals = (
        activity.groupby(["student_hash", "course_id"])
        .agg(total_events=("n_events", "sum"),
             active_days=("active_days", "sum"))
        .reset_index()
    )
    by_cat = (
        activity.pivot_table(index=["student_hash", "course_id"],
                             columns="event_category", values="n_events",
                             aggfunc="sum", fill_value=0)
        .reset_index()
    )
    for c in EVENT_COLS:
        if c not in by_cat.columns:
            by_cat[c] = 0

    # --- регулярность ---
    weekly = build_weekly_matrix(activity, course_weeks)

    df = totals.merge(by_cat, on=["student_hash", "course_id"], how="left")
    df = df.merge(weekly, on=["student_hash", "course_id"], how="left")

    # --- своевременность сдачи ---
    if submissions is not None and len(submissions):
        sub = (
            submissions.groupby(["student_hash", "course_id"])
            .agg(n_submissions=("assignment_id", "count"),
                 mean_lead_time_h=("lead_time_hours", "mean"),
                 pct_on_time=("on_time", "mean"))
            .reset_index()
        )
        first = (
            submissions.sort_values("due_week_num")
            .groupby(["student_hash", "course_id"])
            .first()
            .reset_index()[["student_hash", "course_id", "on_time"]]
            .rename(columns={"on_time": "first_assignment_on_time"})
        )
        df = df.merge(sub, on=["student_hash", "course_id"], how="left")
        df = df.merge(first, on=["student_hash", "course_id"], how="left")

    # --- зависимая переменная: итоговая оценка за курс ---
    final = grades[grades["item_type"] == "course"][
        ["student_hash", "course_id", "grade_pct"]
    ].drop_duplicates(subset=["student_hash", "course_id"])
    df = df.merge(final, on=["student_hash", "course_id"], how="inner")

    # --- контекст курса ---
    df = df.merge(courses[["course_id", "category", "n_students"]],
                  on="course_id", how="left")
    if modes is not None:
        df = df.merge(modes, on="course_id", how="left")
    else:
        df["mode"] = pd.NA
        print("  ⚠ course_modes.csv отсутствует — RQ2 проверить не получится",
              file=sys.stderr)

    if background is not None:
        df = df.merge(background, on="student_hash", how="left")
    else:
        df["entry_score"] = pd.NA
        print("  ⚠ student_background.csv отсутствует — нет контроля "
              "исходной подготовки", file=sys.stderr)

    # Производные
    df["events_per_active_week"] = (
        df["total_events"] / df["n_active_weeks"].replace(0, np.nan)
    )
    df["log_total_events"] = np.log1p(df["total_events"])

    return df


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("indir", help="папка с CSV из выгрузки")
    ap.add_argument("-o", "--output", default="data/processed/features.csv")
    args = ap.parse_args()

    print(f"Читаю из {args.indir}/", file=sys.stderr)
    df = build(args.indir)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)

    print(f"\nСобрано наблюдений (студент × курс): {len(df)}", file=sys.stderr)
    print(f"Уникальных студентов: {df['student_hash'].nunique()}", file=sys.stderr)
    print(f"Уникальных курсов:    {df['course_id'].nunique()}", file=sys.stderr)
    if df["mode"].notna().any():
        print("\nПо формам обучения:", file=sys.stderr)
        print(df["mode"].value_counts().to_string(), file=sys.stderr)
    print(f"\nЗаписано: {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
