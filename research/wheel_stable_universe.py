#!/usr/bin/env python3
"""Stable-universe wheel test — does CSP->CC work on ESTABLISHED names (not memes)?

The shipped wheel_backtest.py ran SOFI/SNAP/RIVN/PLUG/NIO (meme names) -> negative.
This re-runs the SAME engine on stable, dividend-paying, liquid-option names to
answer the real question: is the wheel's failure a UNIVERSE artifact?
"""
import importlib.util, os, sys

os.chdir('/home/ubuntu/trading-system')
sys.path.insert(0, '/home/ubuntu/trading-system')

spec = importlib.util.spec_from_file_location('wheel_backtest', 'bot/wheel_backtest.py')
wb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wb)   # __name__ != '__main__', so main() does not auto-run

# stable, established, option-liquid names (many dividend payers). Prices span
# sub-$23 (affordable at $2.3k for ONE CSP) up to ~$60 (research only).
wb.SYMBOLS = ['F', 'T', 'INTC', 'WBA', 'PFE', 'KHC', 'VZ', 'XOM', 'GM', 'CSCO']
wb.main()
