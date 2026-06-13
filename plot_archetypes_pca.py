"""
Project the 7 trader archetype trait vectors into 2D via PCA and annotate each.
Run from the repo root:  python plot_archetypes_pca.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from sklearn.decomposition import PCA

from backend.traits import TRAITS, to_list
from backend.personas import PERSONAS

# Build matrix: (n_personas, n_traits)
names  = [p["name"]  for p in PERSONAS]
blurbs = [p["blurb"] for p in PERSONAS]
matrix = np.array([to_list(p["traits"]) for p in PERSONAS])


# PCA to 2D
pca    = PCA(n_components=2, random_state=42)
coords = pca.fit_transform(matrix)        # (n_personas, 2)
var    = pca.explained_variance_ratio_



# --- Plot ---
fig, ax = plt.subplots(figsize=(10, 7))
fig.patch.set_facecolor("#0f1117")
ax.set_facecolor("#0f1117")

COLORS = [
    "#4fc3f7",  # cautious_saver   – sky blue
    "#81c784",  # index_autopilot  – green
    "#fff176",  # value_investor   – yellow
    "#ffb74d",  # growth_hunter    – orange
    "#ef5350",  # degen            – red
    "#ce93d8",  # crypto_native    – purple
    "#80cbc4",  # contrarian       – teal
]

scatter_kw = dict(s=220, zorder=5, edgecolors="white", linewidths=0.8)
for i, (x, y) in enumerate(coords):
    ax.scatter(x, y, color=COLORS[i], **scatter_kw)

# Annotate with wrapping blurb on second line
for i, (x, y) in enumerate(coords):
    short = names[i].replace("The ", "")
    label = f"$\\bf{{{short}}}$\n{blurbs[i]}"
    ax.annotate(
        label,
        xy=(x, y),
        xytext=(8, 8),
        textcoords="offset points",
        fontsize=7.5,
        color="white",
        bbox=dict(boxstyle="round,pad=0.3", fc="#1e2130", ec=COLORS[i], lw=0.8, alpha=0.85),
    )

# Draw loading arrows for each trait (biplot)
# Scale arrows to fit within ~half the data range
scale = 0.6 * np.max(np.abs(coords))
for j, trait in enumerate(TRAITS):
    dx = pca.components_[0, j] * scale
    dy = pca.components_[1, j] * scale
    if np.sqrt(dx**2 + dy**2) < 0.05 * scale:
        continue  # skip near-zero loadings
    ax.annotate(
        "",
        xy=(dx, dy), xytext=(0, 0),
        arrowprops=dict(arrowstyle="->", color="gray", lw=0.9),
    )
    ax.text(dx * 1.08, dy * 1.08, trait.replace("_", " "),
            fontsize=6.5, color="#aaaaaa", ha="center", va="center")

# Axis zero lines
ax.axhline(0, color="#333344", lw=0.7, ls="--")
ax.axvline(0, color="#333344", lw=0.7, ls="--")

ax.set_xlabel(f"PC1  ({var[0]:.0%} variance)", color="#aaaaaa", fontsize=9)
ax.set_ylabel(f"PC2  ({var[1]:.0%} variance)", color="#aaaaaa", fontsize=9)
ax.tick_params(colors="#555566")
for spine in ax.spines.values():
    spine.set_edgecolor("#333344")

ax.set_title("Trader Archetypes — PCA of Personality Trait Vectors",
             color="white", fontsize=12, pad=12)

plt.tight_layout()
out = os.path.join(os.path.dirname(__file__), "archetypes_pca.png")
plt.savefig(out, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
print(f"Saved -> {out}")
plt.show()
