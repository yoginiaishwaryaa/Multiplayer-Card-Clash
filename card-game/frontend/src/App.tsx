import React, { useState, useEffect, useRef } from 'react';
import './index.css';
import { StateUpdate, SnapshotComplete, Card } from './types';
import {
    Database, Lock, Key, Camera, RotateCcw, ArrowRight, ShieldCheck, Circle
} from 'lucide-react';

// ── Helpers ───────────────────────────────────────────────────────────────────

function rankLabel(rank: number): string {
    if (rank === 1) return 'A';
    if (rank === 11) return 'J';
    if (rank === 12) return 'Q';
    if (rank === 13) return 'K';
    return String(rank);
}

function isRed(suit: string): boolean {
    return suit === '♥' || suit === '♦';
}

function cardId(card: Card): string {
    return `${card.rank}-${card.suit}`;
}

function isSameCard(a: Card | null, b: Card): boolean {
    return a !== null && a.rank === b.rank && a.suit === b.suit;
}

// ── Playing Card Component ────────────────────────────────────────────────────

interface PlayingCardProps {
    card: Card;
    selected?: boolean;
    onClick?: () => void;
    size?: 'sm' | 'md' | 'lg';
}

const PlayingCard: React.FC<PlayingCardProps> = ({ card, selected, onClick, size = 'md' }) => {
    const dims = {
        sm: { w: 52, h: 74, corner: '0.6rem', centerSuit: '1.5rem', cornerRank: '0.65rem', cornerSuit: '0.55rem' },
        md: { w: 64, h: 90, corner: '0.75rem', centerSuit: '2rem', cornerRank: '0.78rem', cornerSuit: '0.65rem' },
        lg: { w: 100, h: 140, corner: '1rem', centerSuit: '3rem', cornerRank: '1.1rem', cornerSuit: '0.9rem' },
    }[size];

    if (!card) {
        return (
            <div
                className="playing-card empty-slot"
                style={{ width: dims.w, height: dims.h, borderRadius: dims.corner, border: '2px dashed #475569', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
            >
                <div style={{ color: '#475569', fontSize: '0.7rem', fontWeight: 600 }}>EMPTY</div>
            </div>
        );
    }

    const red = isRed(card.suit);
    const label = rankLabel(card.rank);
    const suit = card.suit;

    return (
        <div
            className={`playing-card${selected ? ' selected' : ''}`}
            style={{ width: dims.w, height: dims.h, borderRadius: dims.corner, cursor: onClick ? 'pointer' : 'default' }}
            onClick={onClick}
        >
            {/* Top-left corner */}
            <div className="card-corner card-corner-tl" style={{ color: red ? '#dc2626' : '#1e293b' }}>
                <span style={{ fontSize: dims.cornerRank, fontWeight: 800, lineHeight: 1 }}>{label}</span>
                <span style={{ fontSize: dims.cornerSuit, lineHeight: 1 }}>{suit}</span>
            </div>

            {/* Center suit */}
            <div className="card-center" style={{ fontSize: dims.centerSuit, color: red ? '#dc2626' : '#1e293b' }}>
                {suit}
            </div>

            {/* Bottom-right corner (rotated 180°) */}
            <div className="card-corner card-corner-br" style={{ color: red ? '#dc2626' : '#1e293b' }}>
                <span style={{ fontSize: dims.cornerRank, fontWeight: 800, lineHeight: 1 }}>{label}</span>
                <span style={{ fontSize: dims.cornerSuit, lineHeight: 1 }}>{suit}</span>
            </div>
        </div>
    );
};

// ── Face-Down Draw Deck ───────────────────────────────────────────────────────

const DrawDeck: React.FC<{ deckSize: number; onDraw: () => void }> = ({ deckSize, onDraw }) => (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.5rem' }}>
        <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 600 }}>
            Draw Pile
        </div>
        {/* Stacked card illusion */}
        <div
            style={{
                position: 'relative',
                width: 64,
                height: 90,
                cursor: deckSize > 0 ? 'pointer' : 'not-allowed'
            }}
            onClick={deckSize > 0 ? onDraw : undefined}
            title={deckSize > 0 ? `Draw a card (${deckSize} left)` : 'Deck empty'}
        >
            {deckSize > 2 && <div className="deck-shadow deck-shadow-3" />}
            {deckSize > 1 && <div className="deck-shadow deck-shadow-2" />}
            <div className={`deck-card-facedown${deckSize === 0 ? ' empty' : ''}`}
                style={{ cursor: deckSize > 0 ? 'pointer' : 'not-allowed', opacity: deckSize > 0 ? 1 : 0.35 }}>
                <div className="deck-pattern" />
                <div style={{ position: 'relative', zIndex: 1, textAlign: 'center' }}>
                    <div style={{ fontSize: '0.7rem', color: 'rgba(255,255,255,0.6)', fontWeight: 700, letterSpacing: '0.05em' }}>
                        {deckSize}
                    </div>
                    <div style={{ fontSize: '0.6rem', color: 'rgba(255,255,255,0.4)' }}>cards</div>
                </div>
            </div>
        </div>
        <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)' }}>
            {deckSize > 0 ? 'Click to draw' : 'Empty'}
        </div>
    </div>
);

// ── Winner Banner ─────────────────────────────────────────────────────────────

const WinnerBanner: React.FC<{ winner: string; myNodeId: string; onReset: () => void }> = ({ winner, myNodeId, onReset }) => {
    const isMe = winner === myNodeId;
    return (
        <div className="winner-overlay">
            <div className="winner-box">
                <div className="winner-emoji">{isMe ? '🏆' : '😔'}</div>
                <h1 className="winner-title">{isMe ? 'You Won!' : `${winner} Won!`}</h1>
                <p className="winner-sub">
                    {isMe
                        ? 'You emptied your hand first — congratulations!'
                        : `${winner} emptied their hand first.`}
                </p>
                <button className="btn btn-primary" style={{ marginTop: '1rem' }} onClick={onReset}>
                    <RotateCcw size={16} style={{ marginRight: 8 }} /> Reset Piles (need Token)
                </button>
            </div>
        </div>
    );
};

// ── Main App ──────────────────────────────────────────────────────────────────

const App: React.FC = () => {
    const [state, setState] = useState<StateUpdate | null>(null);
    const [selectedCard, setSelectedCard] = useState<Card | null>(null);
    const [snapshot, setSnapshot] = useState<SnapshotComplete['snapshot'] | null>(null);
    const [hint, setHint] = useState('');
    const ws = useRef<WebSocket | null>(null);

    useEffect(() => {
        const env = (import.meta as any).env;
        const backendPort = 8001; // Standard port for the centralized server
        const wsUrl = env.VITE_NODE_UI_WS || `ws://${window.location.hostname}:${backendPort}/ws/ui`;

        const connect = () => {
            const socket = new WebSocket(wsUrl);
            socket.onmessage = (event) => {
                const msg = JSON.parse(event.data);
                if (msg.type === 'STATE_UPDATE') setState(msg.data);
                else if (msg.type === 'SNAPSHOT_COMPLETE') setSnapshot(msg.snapshot);
            };
            socket.onclose = () => setTimeout(connect, 2000);
            ws.current = socket;
        };
        connect();
        return () => ws.current?.close();
    }, []);

    const sendAction = (action: string, payload: any = {}) =>
        ws.current?.send(JSON.stringify({ action, ...payload }));

    const handleSelectCard = (card: Card) => {
        setSelectedCard(isSameCard(selectedCard, card) ? null : card);
        setHint('');
    };

    const handlePlayCard = (pileIdx: number) => {
        if (!selectedCard) { setHint('Select a card from your hand first.'); return; }
        sendAction('play_card', { pile_idx: pileIdx, card: selectedCard });
        setSelectedCard(null);
        setHint('');
    };

    if (!state) return (
        <div className="app-container" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '100vh' }}>
            <div style={{ textAlign: 'center', color: 'var(--text-muted)' }}>
                <div style={{ fontSize: '3rem', marginBottom: '1rem', animation: 'spin 1s linear infinite' }}>⟳</div>
                Connecting to node...
            </div>
        </div>
    );

    return (
        <div className="app-container">
            {/* Winner overlay */}
            {state.winner && (
                <WinnerBanner
                    winner={state.winner}
                    myNodeId={state.node_id}
                    onReset={() => sendAction('shuffle')}
                />
            )}

            {/* Header */}
            <header className="header">
                <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                    <ShieldCheck size={32} color="var(--primary)" />
                    <h1 style={{ margin: 0, fontSize: '1.5rem' }}>
                        Speed Distributed — <span style={{ color: 'var(--primary)' }}>{state.node_id}</span>
                    </h1>
                </div>
                <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
                    <div className={`badge badge-token ${state.token.has_token ? 'active' : ''}`}>
                        <Database size={12} style={{ marginRight: 4 }} />
                        TOKEN HOLDER: {state.token.holder || 'NONE'}
                    </div>
                    <div className={`badge badge-mutex ${state.mutex.state === 'HELD' ? 'active' : ''}`}>
                        <Lock size={12} style={{ marginRight: 4 }} />
                        MUTEX: {state.mutex.state}
                    </div>
                </div>
            </header>

            <main className="main-layout">
                <section className="game-board">

                    {/* ── Center Piles ── */}
                    <div style={{ textAlign: 'center' }}>
                        <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: '0.75rem', fontWeight: 600 }}>
                            Center Piles — Click to Play Selected Card
                        </div>
                        <div className="piles-container">
                            {state.game.center_piles.map((pile, idx) => {
                                const topCard = pile[pile.length - 1];
                                return (
                                    <div key={idx} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '0.5rem' }}>
                                        <PlayingCard card={topCard} size="lg" onClick={() => handlePlayCard(idx)} />
                                        <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                                            Pile {idx + 1} · {pile.length} card{pile.length !== 1 ? 's' : ''}
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                        {hint && <div style={{ color: 'var(--warning)', fontSize: '0.82rem', marginTop: '0.5rem' }}>{hint}</div>}
                    </div>

                    {/* ── Hand + Draw Deck ── */}
                    <div style={{ display: 'flex', gap: '2.5rem', alignItems: 'flex-end', justifyContent: 'center', flexWrap: 'wrap' }}>
                        <div style={{ textAlign: 'center' }}>
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.5rem', marginBottom: '0.75rem' }}>
                                <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 600 }}>
                                    Your Hand
                                </span>
                                <span style={{ background: 'var(--primary)', color: '#000', borderRadius: '999px', padding: '0.1rem 0.5rem', fontSize: '0.72rem', fontWeight: 800 }}>
                                    {state.game.hand.length}
                                </span>
                            </div>
                            <div className="hand-container">
                                {state.game.center_piles.every(p => p.length === 0) ? (
                                    <div style={{ padding: '2rem', textAlign: 'center' }}>
                                        <p style={{ color: 'var(--text-muted)', marginBottom: '1.5rem' }}>The game has not started yet.</p>
                                        <button className="btn btn-primary btn-lg" onClick={() => sendAction('shuffle')}>
                                            <RotateCcw size={20} style={{ marginRight: 10 }} />
                                            Initialize Game System
                                        </button>
                                    </div>
                                ) : state.game.hand.length === 0 ? (
                                    <span style={{ color: 'var(--success)', fontWeight: 600, fontSize: '0.9rem' }}>
                                        🎉 No cards left!
                                    </span>
                                ) : (
                                    state.game.hand.map((card, idx) => (
                                        <PlayingCard
                                            key={`${cardId(card)}-${idx}`}
                                            card={card}
                                            size="md"
                                            selected={isSameCard(selectedCard, card)}
                                            onClick={() => handleSelectCard(card)}
                                        />
                                    ))
                                )}
                            </div>
                            {selectedCard && (
                                <div style={{ marginTop: '0.5rem', fontSize: '0.78rem', color: 'var(--primary)' }}>
                                    Selected: <strong style={{ color: isRed(selectedCard.suit) ? '#ef4444' : '#e2e8f0' }}>
                                        {rankLabel(selectedCard.rank)}{selectedCard.suit}
                                    </strong> — click a pile to play
                                </div>
                            )}
                        </div>

                        {/* Draw pile (face-down, count visible) */}
                        <DrawDeck deckSize={state.game.deck_size} onDraw={() => sendAction('draw_card')} />
                    </div>

                    {/* ── Controls ── */}
                    <div className="controls">
                        <button className="btn btn-primary" onClick={() => sendAction('snapshot')}>
                            <Camera size={16} style={{ marginRight: 8 }} /> Take Snapshot
                        </button>
                        <button className="btn btn-secondary" onClick={() => sendAction('shuffle')}>
                            <RotateCcw size={16} style={{ marginRight: 8 }} /> Reset/Start Game
                        </button>
                        <button className="btn btn-warning" onClick={() => sendAction('request_mutex')}>
                            <Key size={16} style={{ marginRight: 8 }} /> Request Mutex
                        </button>
                        <button className="btn btn-token" onClick={() => sendAction('pass_token')} disabled={!state.token.has_token}>
                            <ArrowRight size={16} style={{ marginRight: 8 }} /> Pass Token
                        </button>
                        <button className="btn btn-accent" onClick={() => sendAction('regenerate_token')}>
                            <RotateCcw size={16} style={{ marginRight: 8 }} /> Force Token
                        </button>
                    </div>
                </section>

                {/* Logs */}
                <aside className="side-panel">
                    <div className="logs-panel">
                        <h3 style={{ margin: '0 0 1rem 0', display: 'flex', alignItems: 'center' }}>
                            <Circle size={12} fill="var(--success)" style={{ marginRight: 8 }} /> Event Logs
                        </h3>
                        <div className="log-list">
                            {state.logs.map((log, i) => (
                                <div key={i} className={`log-entry log-category-${log.category}`}>
                                    <span style={{ opacity: 0.5 }}>[{log.timestamp}]</span> {log.message}
                                </div>
                            ))}
                        </div>
                    </div>
                </aside>
            </main>

            {/* Snapshot Modal */}
            {snapshot && (
                <div className="modal-overlay" onClick={() => setSnapshot(null)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                            <h2>Chandy-Lamport Global Snapshot: {snapshot.id}</h2>
                            <button className="btn btn-accent" onClick={() => setSnapshot(null)}>Close</button>
                        </div>
                        <div className="snapshot-grid">
                            {Object.entries(snapshot.nodes).map(([nodeId, data]) => (
                                <div key={nodeId} className="snapshot-card">
                                    <h4 style={{ color: 'var(--primary)', marginTop: 0 }}>Node: {nodeId}</h4>
                                    <div style={{ fontSize: '0.85rem' }}>
                                        <p>Hand ({(data.local.hand as Card[]).length}): {(data.local.hand as Card[]).map(c => `${rankLabel(c.rank)}${c.suit}`).join(', ') || '—'}</p>
                                        <p>Token: {data.local.has_token ? 'YES' : 'NO'}</p>
                                        <p>Mutex: {data.local.mutex_state}</p>
                                        <p>Center Tops: {(data.local.center_piles as Card[][]).map(pile => {
                                            const top = pile[pile.length - 1] as Card;
                                            return `${rankLabel(top.rank)}${top.suit}`;
                                        }).join(' | ')}</p>
                                        <div style={{ marginTop: '0.5rem', borderTop: '1px solid #475569', paddingTop: '0.5rem' }}>
                                            <strong>In-Transit:</strong>
                                            {Object.entries(data.channels).map(([src, msgs]) => (
                                                <div key={src} style={{ paddingLeft: '0.5rem', marginTop: '0.2rem' }}>
                                                    {src} → {nodeId}: {msgs.length} msg{msgs.length !== 1 ? 's' : ''}
                                                    {msgs.map((m, mi) => (
                                                        <div key={mi} style={{ fontSize: '0.7rem', opacity: 0.7 }}>• {m.type} (ts:{m.ts})</div>
                                                    ))}
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export default App;
