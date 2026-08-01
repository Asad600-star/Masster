#!/usr/bin/env python3
"""Основной анализ: проверка H1-H3 и ответы на RQ1-RQ2.

    python3 analysis/models.py data/processed/features.csv

Студенты вложены в курсы, поэтому обычная OLS-регрессия нарушает
допущение о независимости наблюдений. Используется многоуровневая
модель со случайным эффектом курса — на это рецензенты смотрят в первую
очередь.

Предикторы стандартизованы (z-оценки), чтобы коэффициенты можно было
сравнивать между собой напрямую. Именно это сравнение и проверяет H1.
"""
import argparse
import sys
import warnings

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)

PREDICTORS = [
    "regularity_entropy",
    "log_total_events",
    "active_week_ratio",
    "events_per_active_week",
    "mean_lead_time_h",
    "pct_on_time",
]


def zscore(s):
    s = pd.to_numeric(s, errors="coerce")
    sd = s.std()
    return (s - s.mean()) / sd if sd and sd > 0 else s * 0.0


def prepare(df):
    for c in PREDICTORS:
        if c in df.columns:
            df["z_" + c] = zscore(df[c])
    return df


def section(title):
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def descriptives(df):
    section("ОПИСАТЕЛЬНАЯ СТАТИСТИКА")
    cols = [c for c in PREDICTORS + ["grade_pct"] if c in df.columns]
    desc = df[cols].describe().T[["count", "mean", "std", "min", "50%", "max"]]
    print(desc.round(2).to_string())

    print("\nКорреляции с итоговой оценкой (Пирсон):")
    for c in PREDICTORS:
        if c not in df.columns:
            continue
        sub = df[[c, "grade_pct"]].dropna()
        if len(sub) > 10:
            r = sub[c].corr(sub["grade_pct"])
            print(f"  {c:26} r = {r:+.3f}   (n={len(sub)})")


def rq1(df):
    section("RQ1 / H1 — какие индикаторы предсказывают успеваемость")
    print("H1: регулярность предсказывает сильнее, чем объём активности.\n")

    avail = [c for c in ["z_regularity_entropy", "z_log_total_events",
                         "z_events_per_active_week", "z_pct_on_time"]
             if c in df.columns and df[c].notna().any()]
    formula = "grade_pct ~ " + " + ".join(avail)
    data = df.dropna(subset=["grade_pct", "course_id"] + avail)

    print(f"Модель: {formula}")
    print(f"Случайный эффект: course_id  |  N = {len(data)}, "
          f"курсов = {data['course_id'].nunique()}\n")

    model = smf.mixedlm(formula, data, groups=data["course_id"]).fit()
    print(model.summary().tables[1])

    params = model.params.drop(["Intercept", "Group Var"], errors="ignore")
    ranked = params.abs().sort_values(ascending=False)
    print("\nСила эффекта (|стандартизованный коэффициент|):")
    for name, val in ranked.items():
        p = model.pvalues.get(name, np.nan)
        star = "***" if p < .001 else "**" if p < .01 else "*" if p < .05 else ""
        print(f"  {name:28} {val:6.3f}   p = {p:.4f} {star}")

    reg = params.get("z_regularity_entropy", np.nan)
    vol = params.get("z_log_total_events", np.nan)
    if not (np.isnan(reg) or np.isnan(vol)):
        verdict = "ПОДДЕРЖИВАЕТСЯ" if abs(reg) > abs(vol) else "НЕ поддерживается"
        print(f"\nH1: {verdict}")
        print(f"    регулярность |{reg:.3f}|  vs  объём |{vol:.3f}|")
    return model


def rq2(df):
    section("RQ2 / H2 — различия между формами обучения")
    if "mode" not in df.columns or df["mode"].isna().all():
        print("⚠ Нет course_modes.csv — форма обучения неизвестна.")
        print("  Запроси таблицу соответствия в учебной части, без неё")
        print("  этот вопрос проверить нельзя.")
        return None

    print("H2: поведенческие индикаторы сильнее предсказывают результат")
    print("    в дистанционных курсах, чем в очных.\n")

    print("Корреляция «регулярность — оценка» по формам обучения:")
    for mode, grp in df.groupby("mode"):
        sub = grp[["regularity_entropy", "grade_pct"]].dropna()
        if len(sub) > 10:
            print(f"  {mode:10} r = {sub['regularity_entropy'].corr(sub['grade_pct']):+.3f}"
                  f"   (n = {len(sub)}, курсов = {grp['course_id'].nunique()})")

    data = df.dropna(subset=["grade_pct", "mode", "z_regularity_entropy",
                             "z_log_total_events"])
    if data["mode"].nunique() < 2:
        print("\n⚠ Менее двух форм обучения в данных — взаимодействие не оценить.")
        return None

    formula = ("grade_pct ~ z_regularity_entropy * C(mode) "
               "+ z_log_total_events * C(mode)")
    print(f"\nМодель со взаимодействием:\n  {formula}\n")
    model = smf.mixedlm(formula, data, groups=data["course_id"]).fit()
    print(model.summary().tables[1])

    inter = [n for n in model.params.index if ":" in n]
    if inter:
        print("\nЭффекты взаимодействия (различие наклонов между формами):")
        for n in inter:
            p = model.pvalues[n]
            star = "***" if p < .001 else "**" if p < .01 else "*" if p < .05 else "н.з."
            print(f"  {n:52} b = {model.params[n]:+.3f}  p = {p:.4f} {star}")
    return model


def h3(df):
    section("H3 — своевременность сдачи первого задания как ранний предиктор")
    if "first_assignment_on_time" not in df.columns:
        print("⚠ Нет данных о сдаче заданий (submissions.csv).")
        return

    sub = df.dropna(subset=["first_assignment_on_time", "grade_pct"])
    if sub.empty:
        print("⚠ Пустая выборка.")
        return

    grp = sub.groupby("first_assignment_on_time")["grade_pct"]
    print("Итоговая оценка в зависимости от сдачи первого задания:\n")
    for val, s in grp:
        label = "сдал вовремя" if val == 1 else "опоздал"
        print(f"  {label:16} M = {s.mean():5.2f}  SD = {s.std():5.2f}  n = {len(s)}")

    from scipy import stats
    a = sub[sub["first_assignment_on_time"] == 1]["grade_pct"]
    b = sub[sub["first_assignment_on_time"] == 0]["grade_pct"]
    if len(a) > 5 and len(b) > 5:
        t, p = stats.ttest_ind(a, b, equal_var=False)
        pooled = np.sqrt((a.var() + b.var()) / 2)
        d = (a.mean() - b.mean()) / pooled if pooled else np.nan
        print(f"\n  Уэлч t = {t:.3f}, p = {p:.4g}, Коэн d = {d:.3f}")
        print(f"  H3: {'ПОДДЕРЖИВАЕТСЯ' if p < .05 else 'НЕ поддерживается'}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("features", help="CSV от analysis/features.py")
    ap.add_argument("--synthetic", action="store_true",
                    help="пометить вывод как полученный на синтетике")
    args = ap.parse_args()

    df = prepare(pd.read_csv(args.features))

    if args.synthetic:
        print("\n" + "!" * 72)
        print("!! ВНИМАНИЕ: анализ выполнен на СИНТЕТИЧЕСКИХ данных.")
        print("!! Это проверка работоспособности кода, а не результаты.")
        print("!! Ни одна цифра ниже не может попасть в статью.")
        print("!" * 72)

    descriptives(df)
    rq1(df)
    rq2(df)
    h3(df)

    print("\n" + "=" * 72)
    print("Готово.")


if __name__ == "__main__":
    main()
