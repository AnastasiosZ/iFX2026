from transformers import AutoTokenizer, AutoModel
import torch

trader_personality = {
    "risk_tolerance": "Willingness to accept losses in pursuit of higher returns; comfort with portfolio volatility",
    "risk_aversion": "Preference for stability and capital preservation over aggressive growth strategies",
    "patience": "Ability to hold positions through market fluctuations without impulsive decision-making",
    "impulsivity": "Tendency to make quick trading decisions based on recent price movements or emotional reactions",
    "discipline": "Adherence to a predetermined trading plan and risk management rules regardless of market conditions",
    "greed": "Desire to maximize profits that may override prudent risk management and position sizing",
    "confidence": "Self-belief in trading abilities and market analysis, which can enhance or undermine decision-making",
    "analytical_depth": "Inclination toward detailed research, technical analysis, and data-driven decision-making",
    "contrarian_tendency": "Propensity to go against market consensus and take positions opposing prevailing sentiment",
    "herd_mentality": "Inclination to follow the crowd and base decisions on majority market behavior rather than individual analysis",
}

