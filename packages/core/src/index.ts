export interface PricePoint {
  bid: number;
  ask: number;
}

export function rawEdge(buyAsk: number, sellBid: number): number {
  return sellBid - buyAsk;
}

export function toPercent(value: number): number {
  return value * 100;
}
