"""Generates the bundled Stock-MoE example report (run with reportlab):
   python3 web-extras/gen_moe_example.py
Produces sample_stock_moe_experts.pdf in web-extras/ (embeds stocks_sample.csv).
Spec targets the CoSTEER PyTorch execution harness (model.py / model_cls / TimeSeries).
"""
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Preformatted, SimpleDocTemplate, Spacer

HERE = Path(__file__).parent

CSV = (HERE / "stocks_sample.csv").read_text().strip()

SECTIONS: list[tuple[str, str]] = [
    ("1. Objective and model card",
     "Implement a PyTorch mixture-of-experts (MoE) model for next-day cross-sectional stock ranking, and evaluate it on the "
     "real public dataset embedded in Appendix A: daily closing prices of 16 large-cap US stocks across 4 sectors "
     "(Technology, Financials, Healthcare, Energy), 256 trading days (source: Nasdaq public quote API, Aug 2025 - Aug 2026). "
     "Model card for the research pipeline:<br/><br/>"
     "<font face='Courier' size='8'>"
     "model_name: StockMoEExpertsModel<br/>"
     "model_type: TimeSeries<br/>"
     "description: Cross-asset ranking model. Encodes a trailing window of the full stock cross-section, mixes it temporally "
     "with a causal gated scan, and combines three experts - sector, dynamic-KNN and global-factor - through a regime router "
     "into a single return forecast for a target stock.<br/>"
     "hyperparameters: hidden_dim D = 16; num_sectors S = 4; knn_neighbors K = 3; num_factors = 3<br/>"
     "training_hyperparameters: n_epochs = 30; lr = 1e-3; early_stop = 10; batch_size = 256; weight_decay = 1e-4"
     "</font>"),
    ("2. Integration contract (mandatory)",
     "The deliverable is ONE Python file named model.py containing exactly one class subclassing torch.nn.Module and the "
     "module-level assignment model_cls = StockMoEExpertsModel. The class must satisfy this execution contract, which the "
     "automated runner applies verbatim:<br/><br/>"
     "<font face='Courier' size='8'>"
     "import torch<br/>"
     "from model import model_cls<br/>"
     "m = model_cls(num_features=10, num_timesteps=4)<br/>"
     "for _, param in m.named_parameters():<br/>"
     "&nbsp;&nbsp;&nbsp;&nbsp;param.data.fill_(1.0)<br/>"
     "out = m(torch.full((32, 4, 10), 1.0))<br/>"
     "assert out.shape == (32, 1) and torch.isfinite(out).all()"
     "</font><br/><br/>"
     "Consequences: (a) __init__(self, num_features, num_timesteps, **kwargs) - every other hyperparameter needs a default; "
     "(b) forward receives a float tensor of shape (batch_size, num_timesteps, num_features) and must return shape "
     "(batch_size, 1) - do NOT permute the input, timesteps are already axis 1; (c) after every nn.Parameter is overwritten "
     "with 1.0 and the input is a constant all-ones batch, forward must stay finite - no division by parameters, no BatchNorm "
     "(a constant batch has zero variance and produces NaN), prefer LayerNorm with eps or simple tanh/sigmoid gates; "
     "(d) fixed constants (masks, decay factors) should be register_buffer since buffers are NOT overwritten; "
     "(e) no side effects at import time (no file/network access, no dataset loading at module level), no try-except blocks, "
     "no top-level main; (f) the real-data demo of Section 8 must live inside an if __name__ == '__main__': guard. "
     "Only torch and the Python standard library may be imported."),
    ("3. Input convention of this model",
     "Each row of a batch predicts ONE target stock on ONE day. A sample x in R^(T x F) packs: columns 0 .. A-1 = trailing "
     "T-day daily log-return cross-section of A stocks (identical across samples that share a date), column A (the last "
     "column) = target indicator, constant along time with value target_idx / (A - 1). Hence F = A + 1, i.e. "
     "num_features = A + 1. The model must work for ANY num_features &gt;= 2 and any num_timesteps: treat the last column as "
     "the target indicator, the remaining A' = num_features - 1 columns as the cross-section, and recover the target index as "
     "idx = clamp(round(x[:, -1, -1] * (A' - 1)), 0, A' - 1).long(). Under the acceptance test above, A' = 9 and idx = 8, "
     "which is valid."),
    ("4. Architecture",
     "The model follows this diagram:<br/><br/>"
     "<font face='Courier' size='8'>"
     "x[B,T,F] -&gt; Feature Encoder -&gt; Temporal gated scan -&gt; H[B,T,D]<br/>"
     "H + x -&gt; three parallel experts E1 sector / E2 dynamic-KNN / E3 global-factor<br/>"
     "(E1, E2, E3) + regime features -&gt; Regime Router gates g1,g2,g3 -&gt; y = head(sum g_k E_k), shape (B, 1)"
     "</font><br/><br/>"
     "Feature Encoder (causal): z_t = tanh(LayerNorm_eps(x_t) W_e + b_e), W_e in R^(F x D), D = 16. Per-timestep, hence causal. "
     "Temporal mixer (Mamba-style gated scan, causal): h_0 = 0, g_t = sigmoid(z_t W_g + b_g) in [0,1]^D, "
     "h_t = g_t * h_{t-1} + (1 - g_t) * z_t. H = stack(h_1 .. h_T).<br/><br/>"
     "Expert 1 - Sector: split the A' cross-section columns into S = min(4, A') consecutive blocks (a stand-in for the GICS "
     "hierarchy; in the demo data columns are already ordered by sector). Compute per-block means over the last min(3, T) "
     "timesteps -> s in R^S. Target block ts = idx // ceil(A'/S), clamped. E1 = Linear(2S -&gt; 1)(concat(s, s * onehot(ts))).<br/><br/>"
     "Expert 2 - Dynamic KNN: gather the target series xs = x[:, :, idx]. Compute trailing Pearson correlation of xs with every "
     "other column over the window T (cov / (std_i * std_j + eps)), tanh-compress, keep top K = min(3, A'-1) with softmax "
     "weights w. E2 = Linear(1 -&gt; 1)(sum_j w_j * x[:, -1, j]) - a correlation-weighted readout of the neighbors' most recent "
     "moves, so the effective predictor tracks the changing correlation structure.<br/><br/>"
     "Expert 3 - Global factor: M = x[:, :, :A'] centered over the time axis; torch.linalg.svd(M) -> keep top-3 singular "
     "values s3 (B,3) and right vectors V3 (B, A', 3); target loading l = V3[range(B), idx, :3]; "
     "E3 = Linear(3 -&gt; 1)(l * (s3 / (s3.max + eps))).<br/><br/>"
     "Regime Router: regime features phi in R^3 computed from x (data-driven, no parameters): realized vol of the cross-section "
     "mean series, trailing momentum (window mean of the cross-section mean), cross-sectional dispersion at the last timestep; "
     "z-score each within the window with eps. Gates g = softmax(phi W_r + b_r) in R^3. Output head: y = Linear(1 -&gt; 1)"
     "(g1*E1 + g2*E2 + g3*E3), returned as (B, 1)."),
    ("5. Stability requirements",
     "Every denominator gets + eps (1e-6). torch.linalg.svd must receive the centered matrix of a constant batch without NaN: "
     "centering makes it exactly zero, which is fine. All gather/scatter indices are clamped to valid ranges. No BatchNorm1d/2d. "
     "The model must produce a finite (B,1) tensor for the all-ones, all-parameters-1.0 acceptance test of Section 2."),
    ("6. Data and splits (demo, strictly causal)",
     "Parse the Appendix A CSV: first column Date, remaining headers 'Sector:TICKER' (16 columns). Build price matrix "
     "P (256 x 16) and daily log returns R. Window length T_win = 20; horizon 1 day: target y[t, a] = R[t+1, a]. Samples: for "
     "every usable date t and stock a, x packs R[t-T_win+1 .. t, :] plus target indicator a/(16-1). Split by date: first 60% "
     "train, next 20% validation, last 20% test. All statistics causal. Nothing is fitted on test except evaluation."),
    ("7. Training",
     "torch.manual_seed(7). Adam, lr = 1e-3, weight_decay = 1e-4, batch_size = 256, at most n_epochs = 30 with early stopping "
     "(patience 10) on validation MSE of the next-day target return. CPU only, no network, total runtime under 10 minutes."),
    ("8. Evaluation protocol (inside the __main__ guard)",
     "Embed the Appendix A CSV as a string constant INSIDE the __main__ guard of model.py (the file is still importable "
     "side-effect-free). On the test split report per date the Spearman rank IC between predicted and realized next-day returns, "
     "averaged over dates, and the long-short return (mean of top-3 minus bottom-3 predicted stocks per date, bps/day). Also "
     "report ablations with the router gates fixed: expert-1-only, expert-2-only, expert-3-only, and equal-weight 1/3 each. "
     "Print a small results table."),
    ("9. Reference results (feasibility baseline, NumPy prototype, seed 7)",
     "A closed-form NumPy prototype of this exact architecture on this dataset achieved on the 51 test days: rank IC "
     "MoE +0.0062 vs equal-weight -0.0252 vs experts alone -0.0015 / -0.0396 / -0.0441; long-short +8.12 bps/day vs -23.51 "
     "for equal weight; learned gates [0.18, 0.71, 0.12] (sector / KNN / factor). A torch implementation with a short training "
     "loop should reach comparable or better rank IC; matching the sign and relative ordering is sufficient for this sample."),
    ("10. Constraints and report format",
     "Deterministic (seed 7), torch + stdlib only, no network, runtime &lt; 10 min. The final report should restate the "
     "architecture, the acceptance-test result, the results table of Section 8, and one paragraph of analysis of the learned "
     "router gates."),
]


def build():
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1x", parent=styles["Title"], fontSize=13, leading=16, spaceAfter=2)
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
            "Model Research Report (Sample spec, PyTorch) &mdash; model_type: TimeSeries; "
            "dataset: real public US large-cap daily closes, 16 assets / 4 sectors / 256 trading days",
            h2,
        ),
    ]
    for head, text in SECTIONS:
        story += [Paragraph(head, hs), Paragraph(text, body), Spacer(1, 3)]
    story += [Paragraph("Appendix A - Embedded dataset (CSV, parse this text)", hs)]
    story += [
        Paragraph(
            "Columns are 'Sector:TICKER'. Embed this CSV as a string constant inside the __main__ guard of model.py and parse "
            "it there. No network access is allowed anywhere.",
            body,
        )
    ]
    story += [Preformatted(CSV, csvstyle)]
    doc.build(story)
    print("wrote", HERE / "sample_stock_moe_experts.pdf")


if __name__ == "__main__":
    build()
