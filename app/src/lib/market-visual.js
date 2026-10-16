// Total market cap is expressed in 亿元 by the evidence layer. Normalize only
// inside the displayed graph: neither node order nor layout depends on this.
export const MARKET_VISUAL_LIMITS = Object.freeze({
  minSize: 1.35, maxSize: 3.75,
  minBrightness: 0.18, maxBrightness: 1.65,
  missingStrength: 0.2, equalStrength: 0.5,
});

const positiveCap = value => typeof value === 'number' && Number.isFinite(value) && value > 0;

/** Pure, order-preserving visual metrics; selection opacity remains separate. */
export function marketVisualsForNodes(nodes) {
  const logs = nodes.map(node => positiveCap(node.meta?.mv) ? Math.log(node.meta.mv) : null);
  const valid = logs.filter(value => value !== null);
  const min = valid.length ? Math.min(...valid) : 0;
  const max = valid.length ? Math.max(...valid) : 0;
  const range = max - min;
  const limits = MARKET_VISUAL_LIMITS;
  return logs.map(log => {
    const hasMarketCap = log !== null;
    const strength = !hasMarketCap ? limits.missingStrength : range > 0 ?
      Math.max(0, Math.min(1, (log - min) / range)) : limits.equalStrength;
    return {
      hasMarketCap, strength,
      size: limits.minSize + (limits.maxSize - limits.minSize) * strength,
      brightness: limits.minBrightness + (limits.maxBrightness - limits.minBrightness) * strength ** 1.5,
    };
  });
}
