#!/usr/bin/env python3
"""RQ3 — на какой неделе семестра модель становится пригодной для вмешательства.

    python3 analysis/early_warning.py data/raw -o analysis/output

Идея: берём только те данные, которые реально доступны к концу недели N,
обучаем классификатор «в зоне риска / нет» и смотрим, как растёт качество
с накоплением недель. Практический ответ — самая ранняя неделя, на которой
precision и recall уже достаточны, чтобы куратор мог звать студента на
разговор, не создавая лавину ложных срабатываний.

Кросс-валидация выполняется с разбиением ПО КУРСАМ, а не по студентам.
Иначе студенты одного курса попадают и в обучение, и в тест, качество
завышается, и рецензент справедливо укажет на утечку.
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, precision_score, recall_score
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).parent))
from features import read_table, normalized_entropy  # noqa: E402

RISK_PERCENTILE = 25      # нижние 25% по оценке считаем «в зоне риска»
MIN_POSITIVE = 20         # минимум наблюдений в классе риска для оценки


def cumulative_features(activity, submissions, upto_week):
    """Признаки, доступные к концу недели upto_week включительно."""
    act = activity[activity["week_num"] <= upto_week]
    if act.empty:
        return pd.DataFrame()

    totals = (
        act.groupby(["student_hash", "course_id"])
        .agg(total_events=("n_events", "sum"),
             active_days=("active_days", "sum"))
        .reset_index()
    )

    per_week = (
        act.groupby(["student_hash", "course_id", "week_num"])["n_events"]
        .sum().reset_index()
    )
    rows = []
    n_weeks = upto_week + 1
    for (sh, cid), grp in per_week.groupby(["student_hash", "course_id"]):
        vec = np.zeros(n_weeks)
        for _, r in grp.iterrows():
            w = int(r["week_num"])
            if 0 <= w < n_weeks:
                vec[w] += r["n_events"]
        rows.append({
            "student_hash": sh, "course_id": cid,
            "regularity_entropy": normalized_entropy(vec),
            "active_week_ratio": float((vec > 0).sum() / n_weeks),
            "last_week_events": float(vec[-1]),
            "trend": float(vec[-1] - vec[0]),
        })
    feats = totals.merge(pd.DataFrame(rows), on=["student_hash", "course_id"])

    if submissions is not None and len(submissions):
        sub = submissions[submissions["due_week_num"] <= upto_week]
        if len(sub):
            agg = (
                sub.groupby(["student_hash", "course_id"])
                .agg(n_submissions=("assignment_id", "count"),
                     pct_on_time=("on_time", "mean"),
                     mean_lead_time_h=("lead_time_hours", "mean"))
                .reset_index()
            )
            feats = feats.merge(agg, on=["student_hash", "course_id"], how="left")

    feats["log_total_events"] = np.log1p(feats["total_events"])
    return feats


def evaluate_week(feats, target, model_name="gbm", n_splits=5):
    df = feats.merge(target, on=["student_hash", "course_id"], how="inner").dropna(
        subset=["at_risk"]
    )
    if df.empty or df["at_risk"].sum() < MIN_POSITIVE:
        return None

    X_cols = [c for c in df.columns
              if c not in ("student_hash", "course_id", "at_risk", "grade_pct")]
    X = df[X_cols].fillna(0).values
    y = df["at_risk"].astype(int).values
    groups = df["course_id"].values

    n_splits = min(n_splits, len(np.unique(groups)))
    if n_splits < 2:
        return None

    aucs, precs, recs = [], [], []
    for tr, te in GroupKFold(n_splits=n_splits).split(X, y, groups):
        if len(np.unique(y[tr])) < 2 or len(np.unique(y[te])) < 2:
            continue
        scaler = StandardScaler().fit(X[tr])
        clf = (GradientBoostingClassifier(random_state=0)
               if model_name == "gbm"
               else LogisticRegression(max_iter=2000, random_state=0))
        clf.fit(scaler.transform(X[tr]), y[tr])
        proba = clf.predict_proba(scaler.transform(X[te]))[:, 1]
        pred = (proba >= 0.5).astype(int)
        aucs.append(roc_auc_score(y[te], proba))
        precs.append(precision_score(y[te], pred, zero_division=0))
        recs.append(recall_score(y[te], pred, zero_division=0))

    if not aucs:
        return None
    return {
        "n": len(df),
        "n_at_risk": int(y.sum()),
        "auc": float(np.mean(aucs)), "auc_sd": float(np.std(aucs)),
        "precision": float(np.mean(precs)),
        "recall": float(np.mean(recs)),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("indir", help="папка с CSV из выгрузки")
    ap.add_argument("-o", "--outdir", default="analysis/output")
    ap.add_argument("--model", choices=["gbm", "logit"], default="gbm")
    ap.add_argument("--synthetic", action="store_true")
    args = ap.parse_args()

    if args.synthetic:
        print("!" * 72)
        print("!! СИНТЕТИЧЕСКИЕ данные — проверка кода, а не результаты.")
        print("!" * 72 + "\n")

    d = Path(args.indir)
    activity = read_table(d, "weekly_activity.csv")
    grades = read_table(d, "grades.csv")
    submissions = read_table(d, "submissions.csv", required=False)

    final = grades[grades["item_type"] == "course"][
        ["student_hash", "course_id", "grade_pct"]
    ].drop_duplicates(subset=["student_hash", "course_id"])
    threshold = final["grade_pct"].quantile(RISK_PERCENTILE / 100)
    final["at_risk"] = (final["grade_pct"] <= threshold).astype(int)

    print(f"Порог зоны риска: нижние {RISK_PERCENTILE}% "
          f"(grade_pct <= {threshold:.2f})")
    print(f"В зоне риска: {final['at_risk'].sum()} из {len(final)}\n")

    max_week = int(activity["week_num"].max())
    results = []
    print(f"{'нед.':>5} {'N':>6} {'риск':>6} {'AUC':>7} {'±SD':>6} "
          f"{'precision':>10} {'recall':>8}")
    print("-" * 56)
    for w in range(0, max_week + 1):
        r = evaluate_week(
            cumulative_features(activity, submissions, w), final, args.model
        )
        if r is None:
            print(f"{w:>5} {'—  недостаточно данных':>30}")
            continue
        r["week"] = w
        results.append(r)
        print(f"{w:>5} {r['n']:>6} {r['n_at_risk']:>6} {r['auc']:>7.3f} "
              f"{r['auc_sd']:>6.3f} {r['precision']:>10.3f} {r['recall']:>8.3f}")

    if not results:
        print("\nНе удалось оценить ни одной недели.")
        return

    res = pd.DataFrame(results)
    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    dest = out / ("early_warning_synthetic.csv" if args.synthetic
                  else "early_warning.csv")
    res.to_csv(dest, index=False)

    print("\n" + "=" * 56)
    for thr in (0.70, 0.75, 0.80):
        hit = res[res["auc"] >= thr]
        if len(hit):
            w = int(hit.iloc[0]["week"])
            print(f"AUC >= {thr:.2f} достигается на неделе {w} "
                  f"(AUC = {hit.iloc[0]['auc']:.3f})")
        else:
            print(f"AUC >= {thr:.2f} не достигается за наблюдаемый период")

    best = res.loc[res["auc"].idxmax()]
    print(f"\nМаксимум: неделя {int(best['week'])}, AUC = {best['auc']:.3f}")
    print(f"Записано: {dest}")


if __name__ == "__main__":
    main()
