"""A model that learns which findings your auditors reject.

**This is the part that actually learns anything.** A local LLM would not: it
arrives pre-trained on the internet and knows nothing about your rules, your
tenants, or which of your findings turn out to be noise. What it would do is
paraphrase — expensively, slowly, and with a standing risk of inventing a
figure into an audit narrative.

What *is* learnable here is specific and valuable: rule DUP-001 fires forty
times a month and your seniors mark thirty of them false positives. That is a
labelled dataset nobody else has, produced by the feedback loop
(`apps/audit/services/finding_feedback.py`), and a gradient-boosted classifier
over a few thousand rows will beat any language model at predicting the next
rejection.

**Why scikit-learn rather than PyTorch or TensorFlow.** The dataset is
thousands of rows with a dozen mostly-categorical features. On that shape a
neural network is not more powerful, it is less: it needs far more data to
match gradient boosting, it is harder to explain, and it adds 2.5 GB to a
container image that is already 2.81 GB. sklearn is installed, the model
trains in seconds, and — the part that matters for an audit product — you can
show a client which features drove a prediction.

Installing torch *and* tensorflow would be worse still: two frameworks that do
the same job, each pulling its own CUDA-shaped dependency tree, on a host
already running three environments.

**What this model is allowed to do.** Rank. Nothing here suppresses a finding.
A model trained on past rejections that hides new findings is a machine for
confirming yesterday's judgement, and in an audit context that is not a
performance issue, it is a control failure. The output is a probability used
to order a review queue, and every finding stays in it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger("core.ai.fp_model")

#: Below this there is nothing to learn from and a fitted model would encode
#: noise as confidence. Chosen to be comfortably above the point where a single
#: tenant's habits dominate the whole model.
MIN_TRAINING_ROWS = 200

#: Minimum of each class. 300 true positives and 4 false positives fits a model
#: that predicts "true positive" always and scores 98% accuracy — the classic
#: imbalanced-data trap, and one an accuracy figure alone will never reveal.
MIN_PER_CLASS = 30


@dataclass
class TrainingReport:
    """What was trained, on what, and how well — or why nothing was."""

    trained: bool = False
    reason: str = ""
    rows: int = 0
    true_positives: int = 0
    false_positives: int = 0
    precision: float | None = None
    recall: float | None = None
    roc_auc: float | None = None
    top_features: list = field(default_factory=list)

    @property
    def is_useful(self) -> bool:
        """Trained is not the same as useful.

        An AUC near 0.5 means the model is guessing; shipping it would dress a
        coin flip in a probability. 0.65 is a low bar deliberately — it is the
        point below which the ranking carries no information at all.
        """
        return self.trained and (self.roc_auc or 0) >= 0.65


class FalsePositivePredictor:
    """Predicts whether an auditor will reject a finding.

    Trained per organisation. One tenant's rules, vendors and tolerance for
    noise say very little about another's, and a shared model would leak the
    shape of one customer's book into another's queue ordering.
    """

    def __init__(self, organization):
        self.organization = organization
        self._pipeline = None
        self._report = TrainingReport()

    # ── training ─────────────────────────────────────────────────────────

    def train(self) -> TrainingReport:
        """Fit on this organisation's judged findings."""
        rows = self._training_rows()

        if len(rows) < MIN_TRAINING_ROWS:
            return TrainingReport(
                reason=(
                    f"Only {len(rows)} judged findings; {MIN_TRAINING_ROWS} are "
                    f"needed before a fitted model means anything. Verdicts "
                    f"accumulate as auditors work — this is a matter of time, "
                    f"not of tuning."
                ),
                rows=len(rows),
            )

        positives = sum(1 for row in rows if row["is_false_positive"])
        negatives = len(rows) - positives

        if min(positives, negatives) < MIN_PER_CLASS:
            return TrainingReport(
                reason=(
                    f"{negatives} true positives and {positives} false positives. "
                    f"At least {MIN_PER_CLASS} of each are needed: a model fitted "
                    f"on this would predict the majority class every time and "
                    f"report high accuracy for doing nothing."
                ),
                rows=len(rows), true_positives=negatives, false_positives=positives,
            )

        try:
            import numpy as np
            from sklearn.compose import ColumnTransformer
            from sklearn.ensemble import HistGradientBoostingClassifier
            from sklearn.metrics import precision_score, recall_score, roc_auc_score
            from sklearn.model_selection import train_test_split
            from sklearn.pipeline import Pipeline
            from sklearn.preprocessing import OrdinalEncoder
        except ImportError as exc:  # pragma: no cover - declared in requirements
            logger.error("scikit-learn unavailable: %s", exc)
            return TrainingReport(
                reason=f"scikit-learn is not installed on this deployment ({exc}).",
                rows=len(rows),
            )

        categorical = ["rule_code", "rule_group", "severity", "source"]
        numeric = ["message_length", "has_invoice", "hour_of_day", "day_of_week"]

        X = [[row[name] for name in categorical + numeric] for row in rows]
        y = [1 if row["is_false_positive"] else 0 for row in rows]

        # Stratified: without it a random split can leave the minority class
        # absent from the test set, and the score is then measured on a problem
        # the model was not asked to solve.
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.25, random_state=20260804, stratify=y,
        )

        pipeline = Pipeline([
            ("encode", ColumnTransformer(
                [("cat", OrdinalEncoder(handle_unknown="use_encoded_value",
                                        unknown_value=-1),
                  list(range(len(categorical))))],
                remainder="passthrough",
            )),
            ("model", HistGradientBoostingClassifier(
                max_iter=200, random_state=20260804,
                # Rejections are the minority and the interesting class;
                # without this the model optimises for the majority and the
                # ranking it produces is the one you already had.
                class_weight="balanced",
            )),
        ])
        pipeline.fit(X_train, y_train)

        predicted = pipeline.predict(X_test)
        probabilities = pipeline.predict_proba(X_test)[:, 1]

        self._pipeline = pipeline
        self._report = TrainingReport(
            trained=True,
            rows=len(rows),
            true_positives=negatives,
            false_positives=positives,
            precision=round(float(precision_score(y_test, predicted, zero_division=0)), 3),
            recall=round(float(recall_score(y_test, predicted, zero_division=0)), 3),
            roc_auc=round(float(roc_auc_score(y_test, probabilities)), 3),
            top_features=self._feature_importance(pipeline, categorical + numeric,
                                                  np.array(X_test), y_test),
            reason=f"Fitted on {len(X_train)} rows, evaluated on {len(X_test)}.",
        )
        return self._report

    def rank(self, findings) -> list:
        """Order findings by how likely a reviewer is to reject them.

        Returns every finding, always. Nothing is filtered out: a model trained
        on past rejections that hides new findings is a machine for confirming
        yesterday's judgement, and in an audit that is a control failure rather
        than a UX choice.
        """
        if not self._report.is_useful:
            return [
                {"finding": f, "false_positive_probability": None,
                 "reason": self._report.reason or "No usable model."}
                for f in findings
            ]

        rows = [self._features(f) for f in findings]
        X = [[row[k] for k in ("rule_code", "rule_group", "severity", "source",
                               "message_length", "has_invoice", "hour_of_day",
                               "day_of_week")] for row in rows]
        probabilities = self._pipeline.predict_proba(X)[:, 1]

        ranked = [
            {"finding": finding,
             "false_positive_probability": round(float(p), 3),
             "reason": f"Model AUC {self._report.roc_auc} on {self._report.rows} judged findings."}
            for finding, p in zip(findings, probabilities)
        ]
        ranked.sort(key=lambda r: r["false_positive_probability"] or 0)
        return ranked

    # ── internals ────────────────────────────────────────────────────────

    def _training_rows(self):
        from apps.audit.models import AuditFinding

        judged = (
            AuditFinding.objects
            .filter(organization=self.organization)
            .filter(verdict__in=[AuditFinding.Verdict.TRUE_POSITIVE,
                                 AuditFinding.Verdict.FALSE_POSITIVE])
            .only("rule_code", "rule_group", "severity", "source", "message",
                  "invoice_id", "first_detected_at", "verdict")
        )
        return [
            {**self._features(finding),
             "is_false_positive": finding.verdict == AuditFinding.Verdict.FALSE_POSITIVE}
            for finding in judged
        ]

    @staticmethod
    def _features(finding) -> dict:
        """Features an auditor could argue with.

        Every one is something a person could look at and say "yes, that is why
        this rule is noisy". A model whose inputs nobody can name is a model
        nobody can defend in front of a regulator, and this product's whole
        argument is defensibility.
        """
        detected = getattr(finding, "first_detected_at", None)
        return {
            "rule_code": getattr(finding, "rule_code", "") or "",
            "rule_group": getattr(finding, "rule_group", "") or "",
            "severity": getattr(finding, "severity", "") or "",
            "source": getattr(finding, "source", "") or "",
            "message_length": len(getattr(finding, "message", "") or ""),
            "has_invoice": 1 if getattr(finding, "invoice_id", None) else 0,
            # Period-end and out-of-hours entries behave differently; both are
            # things an auditor already looks at by hand.
            "hour_of_day": detected.hour if detected else 12,
            "day_of_week": detected.weekday() if detected else 0,
        }

    @staticmethod
    def _feature_importance(pipeline, names, X_test, y_test) -> list:
        """Permutation importance — which inputs the model actually used.

        Computed on held-out data rather than read off the fitted tree: an
        importance measured on training data reports what the model memorised,
        not what it learned.
        """
        try:
            from sklearn.inspection import permutation_importance

            result = permutation_importance(
                pipeline, X_test, y_test, n_repeats=5, random_state=20260804,
            )
            ranked = sorted(zip(names, result.importances_mean),
                            key=lambda pair: -pair[1])
            return [{"feature": name, "importance": round(float(value), 4)}
                    for name, value in ranked[:5]]
        except Exception as exc:  # pragma: no cover - diagnostics only
            logger.warning("permutation importance failed: %s", exc)
            return []
