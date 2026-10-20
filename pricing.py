"""
pricing.py — Option pricing models and Greeks.

Every model uses the "generalized Black-Scholes-Merton" cost-of-carry b:
    stock paying continuous dividend yield q : b = r - q
    option on a future (Black-76)            : b = 0
    plain non-dividend stock                 : b = r
That one parameter lets a single set of functions price equity, index and
futures options consistently (the convention used in Haug, "The Complete
Guide to Option Pricing Formulas").

Notation used everywhere:
    S = underlying price, K = strike, T = years to expiry,
    r = risk-free rate, b = cost of carry, sigma = volatility,
    cp = +1 for a call, -1 for a put
"""
import numpy as np
from scipy.stats import norm, multivariate_normal
from scipy.optimize import brentq

N = norm.cdf    # standard normal CDF
n = norm.pdf    # standard normal PDF


# ---------------------------------------------------------------------------
# 1. Generalized Black-Scholes-Merton (European)
# ---------------------------------------------------------------------------
def _d1_d2(S, K, T, b, sigma):
    d1 = (np.log(S / K) + (b + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    return d1, d1 - sigma * np.sqrt(T)


def bsm(S, K, T, r, b, sigma, cp=1):
    """European option value. At expiry (T<=0) returns intrinsic value."""
    if T <= 0:
        return max(cp * (S - K), 0.0)
    d1, d2 = _d1_d2(S, K, T, b, sigma)
    return cp * (S * np.exp((b - r) * T) * N(cp * d1)
                 - K * np.exp(-r * T) * N(cp * d2))


def binary_cash_or_nothing(S, K, T, r, b, sigma, cp=1, payout=1.0):
    """Pays `payout` if the option finishes in the money, otherwise 0.
    Relevant to Cboe Clear's binary products: value = payout * e^{-rT} * N(cp*d2)."""
    if T <= 0:
        return payout if cp * (S - K) > 0 else 0.0
    _, d2 = _d1_d2(S, K, T, b, sigma)
    return payout * np.exp(-r * T) * N(cp * d2)


# ---------------------------------------------------------------------------
# 2. Cox-Ross-Rubinstein binomial tree (American or European)
# ---------------------------------------------------------------------------
def crr_binomial(S, K, T, r, b, sigma, cp=1, steps=500, american=True):
    """Backward induction on a recombining tree. Vectorized: each loop step
    rolls the whole layer of nodes back one period at once."""
    if T <= 0:
        return max(cp * (S - K), 0.0)
    dt = T / steps
    u = np.exp(sigma * np.sqrt(dt))
    d = 1 / u
    p = (np.exp(b * dt) - d) / (u - d)          # risk-neutral up probability
    disc = np.exp(-r * dt)
    j = np.arange(steps + 1)
    prices = S * u**(steps - j) * d**j           # terminal underlying prices
    values = np.maximum(cp * (prices - K), 0.0)  # terminal payoffs
    for i in range(steps - 1, -1, -1):
        values = disc * (p * values[:-1] + (1 - p) * values[1:])
        if american:
            prices = prices[:-1] / u             # step the price layer back
            values = np.maximum(values, cp * (prices - K))
    return float(values[0])


# ---------------------------------------------------------------------------
# 3. Bjerksund-Stensland (2002) American approximation
# ---------------------------------------------------------------------------
def _phi(S, T, gamma, H, I, r, b, sigma):
    lam = (-r + gamma * b + 0.5 * gamma * (gamma - 1) * sigma**2) * T
    d = -(np.log(S / H) + (b + (gamma - 0.5) * sigma**2) * T) / (sigma * np.sqrt(T))
    kappa = 2 * b / sigma**2 + 2 * gamma - 1
    return np.exp(lam) * S**gamma * (
        N(d) - (I / S)**kappa * N(d - 2 * np.log(I / S) / (sigma * np.sqrt(T))))


def _M(a, b_, rho):
    """Bivariate standard normal CDF with correlation rho."""
    return multivariate_normal.cdf([a, b_], mean=[0, 0], cov=[[1, rho], [rho, 1]])


def _psi(S, T2, gamma, H, I2, I1, t1, r, b, sigma):
    v = sigma
    e = (b + (gamma - 0.5) * v**2)
    e1 = (np.log(S / I1) + e * t1) / (v * np.sqrt(t1))
    e2 = (np.log(I2**2 / (S * I1)) + e * t1) / (v * np.sqrt(t1))
    e3 = (np.log(S / I1) - e * t1) / (v * np.sqrt(t1))
    e4 = (np.log(I2**2 / (S * I1)) - e * t1) / (v * np.sqrt(t1))
    f1 = (np.log(S / H) + e * T2) / (v * np.sqrt(T2))
    f2 = (np.log(I2**2 / (S * H)) + e * T2) / (v * np.sqrt(T2))
    f3 = (np.log(I1**2 / (S * H)) + e * T2) / (v * np.sqrt(T2))
    f4 = (np.log(S * I1**2 / (H * I2**2)) + e * T2) / (v * np.sqrt(T2))
    rho = np.sqrt(t1 / T2)
    lam = -r + gamma * b + 0.5 * gamma * (gamma - 1) * v**2
    kappa = 2 * b / v**2 + (2 * gamma - 1)
    return np.exp(lam * T2) * S**gamma * (
        _M(-e1, -f1, rho)
        - (I2 / S)**kappa * _M(-e2, -f2, rho)
        - (I1 / S)**kappa * _M(-e3, -f3, -rho)
        + (I1 / I2)**kappa * _M(-e4, -f4, -rho))


def _bs2002_call(S, K, T, r, b, sigma):
    if b >= r:                       # never optimal to exercise a call early
        return bsm(S, K, T, r, b, sigma, 1)
    v2 = sigma**2
    beta = (0.5 - b / v2) + np.sqrt((b / v2 - 0.5)**2 + 2 * r / v2)
    B_inf = beta / (beta - 1) * K
    B0 = max(K, r / (r - b) * K)
    t1 = 0.5 * (np.sqrt(5) - 1) * T  # the 2002 paper's split of the time axis
    h1 = -(b * t1 + 2 * sigma * np.sqrt(t1)) * K**2 / ((B_inf - B0) * B0)
    h2 = -(b * T + 2 * sigma * np.sqrt(T)) * K**2 / ((B_inf - B0) * B0)
    I1 = B0 + (B_inf - B0) * (1 - np.exp(h1))   # early-exercise boundary, part 1
    I2 = B0 + (B_inf - B0) * (1 - np.exp(h2))   # early-exercise boundary, part 2
    if S >= I2:
        return S - K                 # deep enough ITM: exercise now
    a1 = (I1 - K) * I1**(-beta)
    a2 = (I2 - K) * I2**(-beta)
    args = (r, b, sigma)
    return (a2 * S**beta - a2 * _phi(S, t1, beta, I2, I2, *args)
            + _phi(S, t1, 1, I2, I2, *args) - _phi(S, t1, 1, I1, I2, *args)
            - K * _phi(S, t1, 0, I2, I2, *args) + K * _phi(S, t1, 0, I1, I2, *args)
            + a1 * _phi(S, t1, beta, I1, I2, *args)
            - a1 * _psi(S, T, beta, I1, I2, I1, t1, *args)
            + _psi(S, T, 1, I1, I2, I1, t1, *args)
            - _psi(S, T, 1, K, I2, I1, t1, *args)
            - K * _psi(S, T, 0, I1, I2, I1, t1, *args)
            + K * _psi(S, T, 0, K, I2, I1, t1, *args))
    # NOTE: the two first-period phi terms use I1, not K. Several published
    # transcriptions print K there; that typo overprices by ~30%. Verified
    # against a 3,000-step binomial tree (see tests in README).


def bjerksund_stensland_2002(S, K, T, r, b, sigma, cp=1):
    """American option. Puts use the put-call transformation:
    P(S, K, T, r, b, sigma) = C(K, S, T, r - b, -b, sigma)."""
    if T <= 0:
        return max(cp * (S - K), 0.0)
    if cp == 1:   # floor at the European value (approximation can dip below)
        return max(_bs2002_call(S, K, T, r, b, sigma), bsm(S, K, T, r, b, sigma, 1))
    return max(_bs2002_call(K, S, T, r - b, -b, sigma), bsm(S, K, T, r, b, sigma, -1))


# ---------------------------------------------------------------------------
# 4. Single entry point used by the margin engine and the app
# ---------------------------------------------------------------------------
MODELS = {
    "Black-Scholes (European)": lambda S, K, T, r, b, v, cp: bsm(S, K, T, r, b, v, cp),
    "Bjerksund-Stensland 2002": bjerksund_stensland_2002,
    "Binomial CRR (American, 300 steps)": lambda S, K, T, r, b, v, cp:
        crr_binomial(S, K, T, r, b, v, cp, steps=300, american=True),
}


def price(model, S, K, T, r, b, sigma, cp):
    return MODELS[model](S, K, T, r, b, sigma, cp)


# ---------------------------------------------------------------------------
# 5. Greeks — analytic (BSM) for first and second order
# ---------------------------------------------------------------------------
def bsm_greeks(S, K, T, r, b, sigma, cp=1):
    """Returns a dict of Greeks. Units: vega per 1.00 vol (divide by 100 for
    per-vol-point), theta per year (divide by 365 for per-day)."""
    d1, d2 = _d1_d2(S, K, T, b, sigma)
    sqT = np.sqrt(T)
    carry = np.exp((b - r) * T)
    g = {}
    g["Delta"] = cp * carry * N(cp * d1)
    g["Gamma"] = carry * n(d1) / (S * sigma * sqT)
    g["Vega"] = S * carry * n(d1) * sqT
    g["Theta"] = (-S * carry * n(d1) * sigma / (2 * sqT)
                  - cp * (b - r) * S * carry * N(cp * d1)
                  - cp * r * K * np.exp(-r * T) * N(cp * d2))
    g["Rho"] = cp * K * T * np.exp(-r * T) * N(cp * d2)
    # second order
    g["Vanna"] = -carry * n(d1) * d2 / sigma                # dDelta/dVol
    g["Volga"] = g["Vega"] * d1 * d2 / sigma                # dVega/dVol
    g["Charm"] = cp * (b - r) * carry * N(cp * d1) \
        - carry * n(d1) * (b / (sigma * sqT) - d2 / (2 * T))  # dDelta/dTime (decay)
    g["Speed"] = -g["Gamma"] / S * (1 + d1 / (sigma * sqT))  # dGamma/dSpot
    return g


def fd_greeks(model, S, K, T, r, b, sigma, cp, hS=None, hV=1e-4):
    """Finite-difference Greeks for ANY model (needed for American models,
    where no closed form exists). Also used to validate the analytic ones."""
    hS = hS or S * 1e-3
    f = lambda s=S, v=sigma: price(model, s, K, T, r, b, v, cp)
    up, mid, dn = f(S + hS), f(), f(S - hS)
    return {
        "Delta": (up - dn) / (2 * hS),
        "Gamma": (up - 2 * mid + dn) / hS**2,
        "Vega": (f(v=sigma + hV) - f(v=sigma - hV)) / (2 * hV),
    }


# ---------------------------------------------------------------------------
# 6. Implied volatility
# ---------------------------------------------------------------------------
def implied_vol(target, S, K, T, r, b, cp=1, model="Black-Scholes (European)"):
    """Brent's method on [0.1%, 500%]; returns NaN if price is outside bounds."""
    f = lambda v: price(model, S, K, T, r, b, v, cp) - target
    try:
        return brentq(f, 1e-3, 5.0, xtol=1e-8)
    except ValueError:
        return float("nan")
