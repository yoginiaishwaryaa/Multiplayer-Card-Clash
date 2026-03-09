export interface Card {
    rank: number;  // 1=Ace, 2-10, 11=Jack, 12=Queen, 13=King
    suit: string;  // '♠', '♥', '♣', '♦'
}

export interface StateUpdate {
    node_id: string;
    winner: string | null;
    game: {
        center_piles: Card[][];
        hand: Card[];
        deck_size: number;
    };
    token: {
        holder: string | null;
        has_token: boolean;
        sequence: number;
    };
    mutex: {
        state: string;
        replies: string[];
        deferred: string[];
    };
    snapshot: {
        is_active: boolean;
    };
    logs: LogEntry[];
}

export interface LogEntry {
    timestamp: number;
    category: string;
    message: string;
    details?: any;
}

export interface SnapshotComplete {
    type: "SNAPSHOT_COMPLETE";
    snapshot: {
        id: string;
        nodes: Record<string, {
            local: any;
            channels: Record<string, any[]>;
        }>;
    };
}
