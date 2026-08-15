"""Regenerates the three bundled "General Model Implementation" spec PDFs.

   python3 web-extras/gen_example_specs.py

Outputs (committed; served from /examples-assets/ and uploaded by examples.html):
  sample_stock_moe_experts.pdf  - Stock-MoE ranking architecture + embedded real dataset
  sample_prime_attention.pdf    - simplified Prime Attention reproduction
  sample_chatsfm.pdf            - simplified ChaTSFM channel-adapter reproduction

All three specs target the CoSTEER PyTorch execution harness: one model.py with
`model_cls = <nn.Module>`, model_type=TimeSeries, constructor
(num_features, num_timesteps), forward (B, T, F) -> (B, 1), stable when every
parameter is overwritten with 1.0 (see CONTRACT / section 2 of each spec).
"""
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Preformatted, SimpleDocTemplate, Spacer

HERE = Path(__file__).parent

CSV = (HERE / "stocks_sample.csv").read_text().strip()

# Integration contract shared by the paper-reproduction specs (the MoE spec has a
# lightly customised version referring to its own demo section).
CONTRACT = (
    "The deliverable is ONE Python file named model.py containing exactly one class subclassing torch.nn.Module and the "
    "module-level assignment model_cls = &lt;YourClass&gt;. The automated runner applies this contract verbatim:<br/><br/>"
    "<font face='Courier' size='8'>"
    "import torch<br/>"
    "from model import model_cls<br/>"
    "m = model_cls(num_features=10, num_timesteps=4)<br/>"
    "for _, param in m.named_parameters():<br/>"
    "&nbsp;&nbsp;&nbsp;&nbsp;param.data.fill_(1.0)<br/>"
    "out = m(torch.full((32, 4, 10), 1.0))<br/>"
    "assert out.shape == (32, 1) and torch.isfinite(out).all()"
    "</font><br/><br/>"
    "Consequences: (a) __init__(self, num_features, num_timesteps, **kwargs) with defaults for everything else; "
    "(b) forward receives shape (batch_size, num_timesteps, num_features) and returns (batch_size, 1) - do NOT permute the "
    "input, timesteps are already axis 1; (c) with every nn.Parameter overwritten by 1.0 and a constant all-ones input the "
    "output must stay finite: no division by parameters, no BatchNorm (zero-variance batch gives NaN), prefer LayerNorm with "
    "eps or tanh/sigmoid gates; (d) fixed constants belong in register_buffer (buffers are NOT overwritten); (e) no side "
    "effects at import time, no try-except, no top-level main; the demo of this report must live inside an "
    "if __name__ == '__main__': guard. Only torch and the Python standard library may be imported. "
    "model_type: TimeSeries."
)

# ================================================================ Stock-MoE
MOE_SECTIONS: list[tuple[str, str]] = [
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

# =========================================================== Prime Attention
PRIME_TITLE = "Prime Attention for Multivariate Time Series Forecasting (Simplified Reproduction)"
PRIME_SUBTITLE = (
    "Model Research Report (Sample spec, PyTorch) &mdash; model_type: TimeSeries &mdash; based on Lee &amp; Clark, "
    "<i>Dynamic Relational Priming Improves Transformer in Multivariate Time Series</i> (arXiv:2509.12196)"
)
PRIME_SECTIONS: list[tuple[str, str]] = [
    ("1. Overview and model card",
     "Standard attention presents the same static token representation in every pair-wise interaction. Prime attention "
     "instead modulates each key/value vector with a pair-specific 'primer' F_ij derived from the lead-lag cross-correlation "
     "structure between channels, so that different channel pairs interact through tailored representations, at the same "
     "asymptotic cost. The paper reports up to 6.5% forecasting gains on MTS benchmarks. Model card:<br/><br/>"
     "<font face='Courier' size='8'>"
     "model_name: PrimeAttentionModel<br/>"
     "model_type: TimeSeries<br/>"
     "description: Channel-attention forecaster whose keys/values are modulated by pairwise cross-correlation primers; "
     "predicts the next-step value of the target channel (channel 0).<br/>"
     "hyperparameters: d_model = 16; n_lags = 8<br/>"
     "training_hyperparameters: n_epochs = 20; lr = 1e-3; early_stop = 5; batch_size = 128; weight_decay = 1e-4"
     "</font>"),
    ("2. Integration contract (mandatory)", CONTRACT),
    ("3. Model formulation",
     "forward(x) with x of shape (B, T, C), where C = num_features is the number of channels and T = num_timesteps the "
     "look-back. Target channel is channel 0; output (B, 1) is the predicted next-step value of channel 0.<br/><br/>"
     "Embedding: per channel c, z_c = tanh(x[:, :, c] @ W_e^T + b_e) with W_e a nn.Linear(num_timesteps, d_model) shared "
     "across channels -> z of shape (B, C, d).<br/><br/>"
     "Standard attention: q_i = z_i W_q, k_j = z_j W_k, v_j = z_j W_v (nn.Linear(d_model, d_model)); "
     "a_ij = softmax_j(q_i . k_j / sqrt(d)); o_i = sum_j a_ij v_j.<br/><br/>"
     "Primer: lag features R_ij in R^L (L = min(n_lags, num_timesteps)) from the circular cross-correlation of the RAW "
     "series x_i and x_j via torch.fft (R = IFFT(FFT(x_j) * conj(FFT(x_i))), first L lags, tanh-compressed). "
     "F_ij = 1 + tanh(R_ij @ W_p^T), W_p a nn.Linear(L, d_model) (the primer projection). Modulated k'_j = k_j * F_ij, "
     "v'_j = v_j * F_ij element-wise, and o'_i = sum_j softmax_j(q_i . k'_j / sqrt(d)) v'_j.<br/><br/>"
     "Readout: y = Linear(d_model, 1)(o'_0), returned as (B, 1). Constructor keyword prime: bool = True switches between "
     "prime attention and the standard-attention ablation; attention: bool = True disables attention entirely "
     "(o_i = z_i, the channel-independent baseline). Both flags are constructor kwargs with defaults, so the acceptance "
     "test's model_cls(num_features=10, num_timesteps=4) call stays valid."),
    ("4. Stability requirements",
     "With all parameters filled with 1.0 and a constant all-ones input: tanh embeddings keep z bounded, softmax is "
     "normalized, F_ij = 1 + tanh(.) stays in [0, 2]; output finite. Use eps = 1e-6 anywhere a division occurs. "
     "No BatchNorm. FFT of a constant series is finite; guard the lag truncation for small num_timesteps (L = min(8, T))."),
    ("5. Demo data and evaluation (__main__ guard only)",
     "Inside the guard, generate a synthetic dataset with torch.manual_seed(42): C = 8 channels, T_total = 2000 steps. "
     "Channel 0 = sine + AR(1) driver; channel 1 = channel 0 delayed 3 steps + noise (lead-lag pair); channel 2 = 0.8 * "
     "channel 0 + noise (instantaneous); channel 3 = independent AR(1); channels 4/5 = lead-lag pair with lag 5; "
     "channels 6/7 = independent seasonal + noise. Slide windows with look-back 24 (construct the model with "
     "num_timesteps = 24, num_features = 8) predicting the next value of channel 0. Chronological 70/15/15 split. Train "
     "with Adam (lr 1e-3, weight_decay 1e-4, batch 128, max 20 epochs, early stop patience 5 on validation MSE). Report "
     "test MSE for three variants of the same class: (a) attention = False baseline, (b) prime = False, (c) prime = True, "
     "plus the relative improvement of (c) over (b). Expect prime attention to match or beat standard attention, with the "
     "clearest gains on lead-lag structure."),
    ("6. Reference",
     "Hunjae Lee, Corey Clark. Dynamic Relational Priming Improves Transformer in Multivariate Time Series. "
     "arXiv:2509.12196, 2025. Official code: https://github.com/timlee0131/Prime-Attention"),
]

# ============================================================== ChaTSFM
CHAT_TITLE = "ChaTSFM: Channel Adapter for Frozen Time Series Foundation Models (Simplified Reproduction)"
CHAT_SUBTITLE = (
    "Model Research Report (Sample spec, PyTorch) &mdash; model_type: TimeSeries &mdash; based on Li et al., <i>Channel Adapter "
    "for Time Series Foundation Models in Zero-Shot Multivariate Forecasting</i> (ChaTSFM, ICML 2026)"
)
CHAT_SECTIONS: list[tuple[str, str]] = [
    ("1. Overview and model card",
     "Time series foundation models (TSFMs) are typically pre-trained channel-independently, so they under-use "
     "inter-channel correlations. ChaTSFM is a lightweight plug-and-play adapter (well under 1% extra parameters) that lets "
     "a FROZEN backbone exploit multivariate correlations in a zero-shot manner. Three pillars: (1) budgeted synthetic "
     "pre-training over diverse inter-channel dependency patterns; (2) data-derived per-channel 'domain descriptors' that "
     "condition a similarity metric; (3) gated sparse refinement blending other channels' backbone forecasts into each "
     "channel's prediction. Model card:<br/><br/>"
     "<font face='Courier' size='8'>"
     "model_name: ChaTSFMModel<br/>"
     "model_type: TimeSeries<br/>"
     "description: Frozen lag-linear backbone (stand-in TSFM, weights kept in buffers) plus a trainable channel adapter "
     "(metric weights m, gate scalars b, c) that refines the target channel forecast with the top-k most similar channels; "
     "predicts the next-step value of channel 0.<br/>"
     "hyperparameters: n_lags = 12; period = 24; top_k = 2; descriptor_dim = 6<br/>"
     "training_hyperparameters: n_epochs = 80; lr = 5e-2; early_stop = 20; batch_size = 64; weight_decay = 0"
     "</font>"),
    ("2. Integration contract (mandatory)", CONTRACT),
    ("3. Model formulation",
     "forward(x) with x of shape (B, T, C); target channel 0; output (B, 1) is the refined next-step forecast of "
     "channel 0.<br/><br/>"
     "Frozen backbone (a stand-in channel-independent TSFM): per channel, a linear forecast from lags 1..12 plus sin/cos "
     "time-of-day features with period 24: f_i = [lags_i, sin_i, cos_i] @ backbone_w. backbone_w lives in a register_buffer "
     "(shape (n_lags + 2, 1), initialized to zeros) so the acceptance test's parameter fill does not touch it and the "
     "unfitted model outputs zeros. The demo fits backbone_w by closed-form ridge (alpha = 1.0) and writes it into the "
     "buffer; after that it is frozen.<br/><br/>"
     "Domain descriptors: per channel d_c = [mean, std, trend slope, lag-1 autocorrelation, spectral entropy of the "
     "periodogram, dominant-period strength] computed from the window, then z-scored across channels with eps.<br/><br/>"
     "Similarity: sim(i, j) = exp(-(d_i - d_j)^T diag(m) (d_i - d_j)) with m = softplus(param_m), param_m an "
     "nn.Parameter(6) - the dataset-conditioned metric. Gate: for the target channel take the top k = 2 most similar other "
     "channels, normalized weights w_ij from their similarities; g = sigmoid(b + c * mean_top_k_similarity) with scalars "
     "b, c as nn.Parameters. Final y = Linear(1, 1)((1 - g) * f_0 + g * sum_j w_ij f_j), shape (B, 1). Trainable parameters: "
     "param_m (6), b, c and the head - a tiny adapter, mirroring the paper."),
    ("4. Stability requirements",
     "In the acceptance test all parameters are 1.0: m = softplus(1) &gt; 0 so similarities are valid exp(-nonneg) in (0, 1]; "
     "g = sigmoid(1 + 1 * sim) in (0.5, 1); backbone buffer is zero so every f_i = 0 and the output is exactly 0 - finite. "
     "Use eps = 1e-6 in every z-score/division. No BatchNorm. Spectral entropy of a flat periodogram must not NaN: "
     "normalize the periodogram by its sum + eps before the entropy."),
    ("5. Demo: adapter pre-training and zero-shot evaluation (__main__ guard only)",
     "Pre-training corpus inside the guard (torch.manual_seed(42)): S = 6 synthetic multivariate datasets, each C = 6 "
     "channels, T_total = 600 steps, covering lead-lag copies, instantaneous scaling, shared seasonality with "
     "channel-specific noise, a regime shift in correlation, and fully independent channels. On each: fit the frozen "
     "backbone, then optimize ONLY (param_m, b, c, head) with Adam (lr 5e-2, max 80 epochs, batch 64) to minimize the "
     "adapter's next-step MSE. Zero-shot evaluation: generate 2 fresh datasets (seed 7) with mixed patterns never used in "
     "pre-training; fit fresh frozen backbones; apply the pre-trained adapter; compare MSE on the last 20% of each series: "
     "backbone-only vs backbone + adapter. Print per-dataset relative MSE improvement. Success: the adapter improves or "
     "matches average MSE on both test datasets."),
    ("6. Reference",
     "Dongyuan Li, Renhe Jiang, Shun Zheng, Zheng Dong, Haotian Gao, Ying Zhang, Jiang Bian. Channel Adapter for Time "
     "Series Foundation Models in Zero-Shot Multivariate Forecasting. ICML 2026. OpenReview: "
     "https://openreview.net/forum?id=OJriSoFuDq . Code: https://github.com/Clearloveyuan/ChaTSFM"),
]


def build_pdf(path: Path, title: str, subtitle: str, sections: list[tuple[str, str]], csv_appendix: str | None = None):
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1x", parent=styles["Title"], fontSize=13, leading=16, spaceAfter=2)
    h2 = ParagraphStyle("h2x", parent=styles["Normal"], fontSize=9.5, textColor="#444444", spaceAfter=8)
    hs = ParagraphStyle("hsx", parent=styles["Heading2"], fontSize=11, spaceBefore=8, spaceAfter=3)
    body = ParagraphStyle("bodyx", parent=styles["Normal"], fontSize=9.5, leading=13.2)
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm, bottomMargin=14 * mm)
    story = [Paragraph(title, h1), Paragraph(subtitle, h2)]
    for head, text in sections:
        story += [Paragraph(head, hs), Paragraph(text, body), Spacer(1, 3)]
    if csv_appendix is not None:
        story += [Paragraph("Appendix A - Embedded dataset (CSV, parse this text)", hs)]
        story += [
            Paragraph(
                "Columns are 'Sector:TICKER'. Embed this CSV as a string constant inside the __main__ guard of model.py and "
                "parse it there. No network access is allowed anywhere.",
                body,
            )
        ]
        story += [Preformatted(csv_appendix, ParagraphStyle("csvx", parent=styles["Code"], fontName="Courier", fontSize=5.1, leading=6.4))]
    doc.build(story)
    print("wrote", path)


if __name__ == "__main__":
    build_pdf(
        HERE / "sample_stock_moe_experts.pdf",
        "Cross-Asset Stock Ranking with a Mixture of Experts: Sector, Dynamic-KNN and Global-Factor Experts under a Regime Router",
        "Model Research Report (Sample spec, PyTorch) &mdash; model_type: TimeSeries; "
        "dataset: real public US large-cap daily closes, 16 assets / 4 sectors / 256 trading days",
        MOE_SECTIONS,
        csv_appendix=CSV,
    )
    build_pdf(HERE / "sample_prime_attention.pdf", PRIME_TITLE, PRIME_SUBTITLE, PRIME_SECTIONS)
    build_pdf(HERE / "sample_chatsfm.pdf", CHAT_TITLE, CHAT_SUBTITLE, CHAT_SECTIONS)
