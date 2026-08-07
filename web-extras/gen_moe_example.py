"""Generates the bundled Stock-MoE example report (run with reportlab):
   python3 web-extras/gen_moe_example.py
Produces sample_stock_moe_experts.pdf in web-extras/ (embeds stocks_sample.csv).
"""
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Preformatted, SimpleDocTemplate, Spacer

HERE = Path(__file__).parent

CSV = (HERE / "stocks_sample.csv").read_text().strip()

SECTIONS: list[tuple[str, str]] = [
    ("1. Objective",
     "Implement the mixture-of-experts (MoE) cross-asset ranking architecture described below for next-day stock ranking, "
     "and evaluate it on the real public dataset embedded in Appendix A: daily closing prices of 16 large-cap US stocks "
     "across 4 GICS-style sectors (Technology, Financials, Healthcare, Energy), 256 trading days (source: Nasdaq public "
     "quote API, Aug 2025 - Aug 2026). All code must be deterministic (seed 7), use only Python stdlib + NumPy/SciPy/"
     "scikit-learn, require no network access, and finish in under 10 minutes."),
    ("2. Architecture",
     "The pipeline follows this diagram exactly:<br/><br/>"
     "<font face='Courier' size='8'>"
     "X[B,T,A,F] -&gt; Feature Encoder -&gt; Temporal Transformer/Mamba (mini) -&gt; H[B,T,A,D]<br/>"
     "H -&gt; three parallel experts:<br/>"
     "&nbsp;&nbsp;E1 Industry/Sector expert (same GICS hierarchy)&nbsp;&nbsp;"
     "E2 Dynamic KNN expert (corr-based, learned KNN)&nbsp;&nbsp;"
     "E3 Global Factor expert (latent market tokens)<br/>"
     "(E1, E2, E3) + regime features -&gt; Regime Router gates g1,g2,g3 -&gt; cross-asset combined state -&gt; ranking / return forecast"
     "</font><br/><br/>"
     "Dimensions: T = 256 days, A = 16 assets, F = 6 features, D = 8 hidden dims, batch B = 1 handled as a single "
     "walk-forward pass (process the whole panel once, causally). Target: next-1-day return y[t,a] = P[t+1,a]/P[t,a] - 1."),
    ("3. Data &amp; splits (strictly causal)",
     "Parse the Appendix A CSV: first column is Date, remaining headers are 'Sector:TICKER'. Build price matrix P (T x A). "
     "Splits by time index: train rows 35 .. floor(0.6*T); router-validation rows floor(0.6*T) .. floor(0.8*T); "
     "test rows floor(0.8*T) .. T-1 (last usable row, since the target needs t+1). All normalization/statistics must use "
     "only data at or before time t (trailing or expanding windows). Never fit anything on the test split except evaluating."),
    ("4. Feature bank &amp; Feature Encoder",
     "Per (t,a) build F = 6 features from trailing prices/returns: (1) 1-day return; (2) 5-day cumulative return; "
     "(3) 21-day momentum; (4) mean-reversion = -(P/MA21 - 1); (5) 21-day realized volatility (std of daily returns); "
     "(6) 5-day realized volatility. Feature Encoder: per feature, causal trailing z-score using at most the last 120 rows "
     "(mean/std over all assets in that window), then tanh compression, then a fixed projection into D = 8 dims via a "
     "seeded Gaussian random matrix E in R^(F x D) scaled by 1/sqrt(F) (rng seed 7). Call the result Z[t,a] in R^D."),
    ("5. Temporal Mixer (the 'Transformer/Mamba' block, mini)",
     "Implement a Mamba-style gated state-space scan per asset: h_t = g * h_{t-1} + (1 - g) * Z_t with per-dimension gate "
     "g in [0,1]^8 (parametrize g = sigmoid(theta)). Fit theta on the train split only by Nelder-Mead (maxiter &lt;= 400) "
     "minimizing the reconstruction MSE of the encoded features (predict Z_t from h_t). H[B,T,A,D] is the stack of all h_t "
     "per asset. This is the temporal-context block of the diagram."),
    ("6. Expert 1 - Industry/Sector expert ('same GICS hierarchy')",
     "One Ridge regression (alpha = 10) per sector, trained on train-split rows of that sector's assets only, mapping "
     "h[t,a] -&gt; y[t,a]. Expert 1's forecast for asset a at time t is its own sector model's prediction."),
    ("7. Expert 2 - Dynamic KNN expert ('corr / learned KNN')",
     "A global Ridge (alpha = 10) mapping h -&gt; y trained once on all train rows. At each (t,a), compute trailing 60-day "
     "return correlations between asset a and every other asset (causal window), rectify to max(corr, 0), take the top K = 3 "
     "neighbors, normalize the weights, and output the weight-averaged global-model forecast of the neighbors. This makes "
     "the expert dynamic: the effective predictor changes with the correlation structure."),
    ("8. Expert 3 - Global Factor expert ('latent market tokens')",
     "At each t, take the trailing (at most 120-row) returns matrix, center per column, compute its SVD and keep the top-3 "
     "right singular vectors V in R^(3 x A) as latent market factor loadings (the 'latent market tokens'). For each asset a, "
     "fit Ridge (alpha = 1) on train rows mapping V_t[:,a] -&gt; y[t,a]. Expert 3's forecast at t uses the factor vector "
     "computed from data up to t only."),
    ("9. Regime Router",
     "Regime features phi_t in R^3: (1) market volatility = std over the trailing 21 days of the cross-sectional mean daily "
     "return; (2) market momentum = trailing 21-day rolling mean of the cross-sectional mean daily return; "
     "(3) cross-sectional dispersion = std across assets of daily returns at t. Z-score phi causally (trailing 120 rows). "
     "Gates g(t) = softmax(phi_t W + b) in R^3 with W in R^(3 x 3), b in R^3 (12 parameters), fitted on the "
     "router-validation split only, by Nelder-Mead (maxiter &lt;= 1500) minimizing MSE of the gated combination "
     "sum_k g_k * Expert_k against realized next-day returns. Combined forecast: yhat[t,a] = sum_k g_k(t) * Expert_k(t,a)."),
    ("10. Cross-asset state &amp; ranking output",
     "On each test day, cross-sectionally rank the 16 assets by yhat (this is the cross-asset combined state producing the "
     "ranking). Print the full ranking table for the last test day, plus the evaluation below."),
    ("11. Evaluation protocol (test split)",
     "For each test day report: Spearman rank IC between yhat and realized next returns; long-short daily return long top-3 / "
     "short bottom-3. Aggregate: mean rank IC and mean L/S (in bps/day) for (a) the MoE router combination, (b) each expert "
     "alone, (c) the equal-weight ensemble. Also print the mean router gates over the test split (sector/KNN/factor shares). "
     "Discuss which expert the router relies on and why."),
    ("12. Reference results (prototype on this exact dataset)",
     "Our reference implementation achieves on the test split (~51 days): mean rank IC of the MoE router about +0.006 vs "
     "equal-weight about -0.025 and single experts about -0.002 / -0.040 / -0.044 (sector/KNN/factor); mean L/S about +8 "
     "bps/day for the router vs about -24 bps/day equal-weight; mean test gates roughly 0.18 sector / 0.71 KNN / 0.12 factor. "
     "Individual numbers may differ slightly with implementation details; the key qualitative result is that no expert is "
     "profitable alone while the learned regime routing turns the combination into positive IC and positive long-short "
     "returns. Your implementation should aim to beat the equal-weight baseline."),
    ("13. Constraints &amp; report format",
     "Python 3 with NumPy/SciPy/scikit-learn only; no PyTorch/TensorFlow; no network; deterministic seed 7; runtime &lt; 10 "
     "minutes; handle NaNs defensively (e.g., warm-up rows). Final report sections: Overview; Architecture Mapping (how each "
     "diagram block was implemented); Data and Splits; Expert Analysis; Router and Regime Analysis; Evaluation table; "
     "Limitations and next steps."),
]


def build():
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1x", parent=styles["Title"], fontSize=14, leading=17, spaceAfter=2)
    h2 = ParagraphStyle("h2x", parent=styles["Normal"], fontSize=9.5, textColor="#444444", spaceAfter=8)
    hs = ParagraphStyle("hsx", parent=styles["Heading2"], fontSize=11, spaceBefore=8, spaceAfter=3)
    body = ParagraphStyle("bodyx", parent=styles["Normal"], fontSize=9.5, leading=13.2)
    csvstyle = ParagraphStyle("csvx", parent=styles["Code"], fontName="Courier", fontSize=5.1, leading=6.4)
    doc = SimpleDocTemplate(
        str(HERE / "sample_stock_moe_experts.pdf"),
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
    )
    story = [
        Paragraph(
            "Cross-Asset Stock Ranking with a Mixture of Experts: Sector, Dynamic-KNN and Global-Factor Experts under a Regime Router",
            h1,
        ),
        Paragraph(
            "Model Research Report (Sample spec) &mdash; mini implementation of the MoE ranking architecture; "
            "dataset: real public US large-cap daily closes, 16 assets / 4 sectors / 256 trading days",
            h2,
        ),
    ]
    for head, text in SECTIONS:
        story += [Paragraph(head, hs), Paragraph(text, body), Spacer(1, 3)]
    story += [Paragraph("Appendix A - Embedded dataset (CSV, parse this text)", hs)]
    story += [
        Paragraph(
            "Columns are 'Sector:TICKER'. If parsing this appendix fails, you may instead download nothing and must error out "
            "gracefully - do not fetch data from the network.",
            body,
        )
    ]
    story += [Preformatted(CSV, csvstyle)]
    doc.build(story)
    print("wrote", HERE / "sample_stock_moe_experts.pdf")


if __name__ == "__main__":
    build()
