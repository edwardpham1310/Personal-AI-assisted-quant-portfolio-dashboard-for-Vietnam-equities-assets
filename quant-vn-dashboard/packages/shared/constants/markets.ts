export const VN_EXCHANGES = ["HOSE", "HNX", "UPCOM"] as const;
export type VnExchange = (typeof VN_EXCHANGES)[number];

export const VN_INDICES = ["VNINDEX", "VN30", "HNX30", "UPCOM"] as const;
export type VnIndex = (typeof VN_INDICES)[number];

/** Vietnam standard board lot. */
export const LOT_SIZE = 100;

/** Settlement cycle in trading days. */
export const SETTLEMENT_T_PLUS = 2;
