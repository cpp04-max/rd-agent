"""Generates the bundled "paper playground" sample reports (run with reportlab):
   python3 web-extras/gen_paper_examples.py
Produces sample_prime_attention.pdf and sample_chatsfm.pdf in web-extras/.
"""
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

HERE = Path(__file__).parent


def build(path: str, title: str, subtitle: str, sections: list[tuple[str, str]]):
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1x", parent=styles["Title"], fontSize=14, leading=17, spaceAfter=2)
    h2 = ParagraphStyle("h2x", parent=styles["Normal"], fontSize=9.5, textColor="#444444", spaceAfter=8)
    hs = ParagraphStyle("hsx", parent=styles["Heading2"], fontSize=11, spaceBefore=8, spaceAfter=3)
    body = ParagraphStyle("bodyx", parent=styles["Normal"], fontSize=9.5, leading=13.2)
    doc = SimpleDocTemplate(path, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm)
    story = [Paragraph(title, h1), Paragraph(subtitle, h2)]
    for head, text in sections:
        story += [Paragraph(head, hs), Paragraph(text, body), Spacer(1, 3)]
    doc.build(story)
    print("wrote", path)


# ---------------------------------------------------------------- Prime Attention
build(
    str(HERE / "sample_prime_attention.pdf"),
    "Prime Attention for Multivariate Time Series Forecasting (Simplified Reproduction)",
    "Model Research Report (Sample) &mdash; based on Lee &amp; Clark, <i>Dynamic Relational Priming Improves Transformer in "
    "Multivariate Time Series</i> (arXiv:2509.12196)",
    [
        ("1. Overview",
         "This report describes a simplified reproduction of 'prime attention'. Standard attention presents the same static "
         "token representation in every pair-wise interaction. Prime attention instead modulates each key/value vector with a "
         "pair-specific 'primer' vector F_ij, so that different channel pairs (lead-lag pairs vs. instantaneously correlated "
         "pairs vs. independent pairs) interact through tailored representations, at the same asymptotic cost as standard "
         "attention. The paper reports up to 6.5% forecasting accuracy gains on MTS benchmarks. Task here: multivariate "
         "forecasting on synthetic data with heterogeneous inter-channel relationships. The implementation must run in pure "
         "NumPy/SciPy/scikit-learn (no PyTorch or TensorFlow)."),
        ("2. Model Formulation",
         "Data: C = 8 channels, T = 2000 timesteps, generated with seed 42. Channel 0 = sine wave + AR(1) driver. "
         "Channel 1 = channel 0 delayed by 3 steps plus small noise (lead-lag pair). Channel 2 = 0.8 * channel 0 plus noise "
         "(instantaneous correlation). Channel 3 = independent AR(1). Channels 4 and 5 = another lead-lag pair with lag 5 and "
         "different AR dynamics. Channels 6 and 7 = independent seasonal series plus noise. Build sliding windows with look-back "
         "L_in = 24 and horizon H = 4. For each window, embed each channel's look-back vector into a token z_c in R^d via a fixed "
         "seeded Gaussian random projection, with d_model = 16.<br/><br/>"
         "Standard attention: q_i = z_i Wq, k_j = z_j Wk, v_j = z_j Wv with fixed seeded random projection matrices W in R^(d x d); "
         "weights a_ij = softmax_j(q_i . k_j / sqrt(d)); output o_i = sum_j a_ij v_j.<br/><br/>"
         "Prime attention: compute lead-lag cross-correlation features R_ij in R^8 between the look-back series of channels i and j "
         "via FFT circular cross-correlation R = IFFT(FFT(x_j) * conj(FFT(x_i))), keeping the first 8 lags and applying tanh. The "
         "primer is F_ij = 1 + tanh(R_ij @ Wp), element-wise in R^d, where Wp in R^(8 x d) is the only learned matrix (initialized "
         "near zero so the primer starts as the identity modulation). Modulated key/value: k_tilde_j = k_j * F_ij and "
         "v_tilde_j = v_j * F_ij (element-wise). Output o_tilde_i = sum_j softmax_j(q_i . k_tilde_j / sqrt(d)) v_tilde_j.<br/><br/>"
         "Readout: predict the next H values of channel i with ridge regression on the attention output only: o_i "
         "for the standard variant or o_tilde_i for the prime variant (do NOT concatenate z_i, so the attention layer is the information bottleneck)."),
        ("3. Hyper-parameters",
         "d_model = 16; number of lag features = 8; ridge alpha = 1.0; look-back 24; horizon 4; all random projections seeded with 42. "
         "Since no autodiff framework is available, fit Wp by evaluating 20 seeded random candidate matrices (scaled to small norm) "
         "plus the zero matrix and keeping the one with the lowest validation MSE. Target runtime under 2 minutes on CPU."),
        ("4. Training and Evaluation",
         "Split windows chronologically 70% train / 15% validation / 15% test. Fit the ridge readout on train; select Wp on "
         "validation. Report average test MSE and MAE over channels and horizons for three models: (a) channel-independent ridge "
         "baseline (no attention, ridge on z_i only), (b) standard attention, (c) prime attention. Print a results table, the relative improvement "
         "of prime over standard attention, and a per-channel breakdown. Expect prime attention to beat standard attention (around 1% lower MSE on this data), with the clearest gains on "
         "the lead-lag channels 1 and 5."),
        ("5. Implementation Notes",
         "Implement in Python with numpy, scipy, scikit-learn and pandas only. Provide a class PrimeAttentionForecaster with "
         "fit(X) and predict(X) methods plus a runnable main.py demo script: if no CSV file is provided, generate the synthetic "
         "8-channel dataset described above with seed 42, run the full evaluation, and print the results table."),
        ("6. Reference",
         "Hunjae Lee, Corey Clark. Dynamic Relational Priming Improves Transformer in Multivariate Time Series. arXiv:2509.12196, 2025. "
         "Official code: https://github.com/timlee0131/Prime-Attention"),
    ],
)

# ---------------------------------------------------------------- ChaTSFM
build(
    str(HERE / "sample_chatsfm.pdf"),
    "ChaTSFM: Channel Adapter for Frozen Time Series Foundation Models (Simplified Reproduction)",
    "Model Research Report (Sample) &mdash; based on Li et al., <i>Channel Adapter for Time Series Foundation Models in Zero-Shot "
    "Multivariate Forecasting</i> (ChaTSFM, ICML 2026)",
    [
        ("1. Overview",
         "Time series foundation models (TSFMs) are typically pre-trained channel-independently, so they under-use inter-channel "
         "correlations. ChaTSFM is a lightweight plug-and-play adapter (well under 1% extra parameters) that lets a FROZEN backbone "
         "exploit multivariate correlations in a zero-shot manner. This simplified reproduction keeps the paper's three pillars: "
         "(1) a budgeted synthetic pre-training corpus covering diverse inter-channel dependency patterns; (2) data-derived "
         "per-channel 'domain descriptors' that condition an inter-channel similarity measure, reducing cross-domain metric "
         "distortion; (3) gated, sparse refinement that blends other channels' backbone forecasts into each channel's prediction "
         "without degrading intra-channel temporal dynamics. Implement in pure NumPy/SciPy/scikit-learn."),
        ("2. Model Formulation",
         "Frozen backbone (fit once, never updated afterwards): per channel, ridge regression from lag features (lags 1..12, plus "
         "sin/cos of time-of-day with period 24) predicting the next H = 4 values. Treat this as a stand-in for a frozen "
         "channel-independent TSFM.<br/><br/>"
         "Domain descriptors: for each channel compute the vector d_c = [mean, standard deviation, trend slope, lag-1 "
         "autocorrelation, spectral entropy of the periodogram, dominant-period strength], then z-score each component across the "
         "channels of the dataset.<br/><br/>"
         "Similarity measure: sim(i, j) = exp(-(d_i - d_j)^T M (d_i - d_j)) with M = diag(m), m a non-negative 6-vector learned "
         "during adapter pre-training (this is the dataset-conditioned metric).<br/><br/>"
         "Gated sparse refinement: for channel i, take the top k = 2 most similar other channels; final forecast "
         "y_hat_i = (1 - g_i) * f_i + g_i * sum_j w_ij f_j, where f denotes the frozen backbone forecast, w_ij is the normalized "
         "similarity weight, and the gate g_i = sigmoid(b + c * mean-similarity-to-top-k) with scalars b, c learned. Only "
         "(m, b, c) are trainable: 8 parameters total."),
        ("3. Hyper-parameters",
         "Horizon H = 4; lags 1..12; period 24; top-k = 2; ridge alpha = 1.0. Budgeted pre-training corpus: S = 6 synthetic "
         "multivariate datasets, each with C = 6 channels and T = 600 timesteps, covering these dependency patterns: lead-lag "
         "copies, instantaneous scaling, shared seasonality with channel-specific noise, a regime shift in correlation, and fully "
         "independent channels. Optimize (m, b, c) with scipy.optimize.minimize (Nelder-Mead, maxiter = 80), initializing "
         "m = ones(6), b = -2, c = 4. All data generation seeded with 42 (pre-training) and 7 (evaluation). Target runtime under "
         "3 minutes on CPU."),
        ("4. Training and Evaluation",
         "Zero-shot evaluation: generate 2 fresh synthetic multivariate test datasets (seed 7) with mixed dependency patterns that "
         "were never used during adapter pre-training. For each dataset fit a fresh frozen backbone, apply the pre-trained adapter, "
         "and compare MSE on the last 20% of the series: backbone-only vs backbone + adapter, per channel and averaged. Print the "
         "per-dataset average relative MSE improvement. Success criterion: the adapter improves (or at least matches) average MSE "
         "on both zero-shot test datasets, mirroring the paper's consistent gains across nine benchmarks."),
        ("5. Implementation Notes",
         "Implement in Python with numpy, scipy, scikit-learn and pandas only. Provide classes FrozenChannelIndependentForecaster "
         "(fit/predict) and ChaTSFMAdapter (pretrain(datasets), adapt(X, backbone)) plus a runnable main.py demo script: if no CSV "
         "file is provided, generate the pre-training and evaluation datasets with the fixed seeds, pre-train the adapter, run the "
         "zero-shot evaluation, and print the results."),
        ("6. Reference",
         "Dongyuan Li, Renhe Jiang, Shun Zheng, Zheng Dong, Haotian Gao, Ying Zhang, Jiang Bian. Channel Adapter for Time Series "
         "Foundation Models in Zero-Shot Multivariate Forecasting. ICML 2026. OpenReview: https://openreview.net/forum?id=OJriSoFuDq . "
         "Code: https://github.com/Clearloveyuan/ChaTSFM"),
    ],
)
